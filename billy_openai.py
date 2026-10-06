"""BillAI Bass — alternate brain: OpenAI Realtime instead of Nova 2.5 Sonic.

Same fish, same motors, same tools — different model provider. Strands'
BidiAgent is provider-agnostic, so the swap is the model constructor
and a voice. Everything below the model is identical in spirit to
billy.py; read that file's docstring for the architecture.

Differences from billy.py you should know about:

  * Auth: needs OPENAI_API_KEY in the environment (no AWS credentials
    required for the model, though the Google tools still use them).
    Also `pip install "strands-agents[bidi-openai]"`.

  * Voice: OpenAI has its own voice lineup, separate from Nova's. This
    file uses `ballad` (which happens to have a British accent), but
    swap in any voice you like.

  * Audio runs at OpenAI's 24 kHz default (Nova is 16 kHz). BillyBody
    picks the rate up from the model config automatically, but the RMS
    thresholds (MOUTH_OPEN, EMPHASIS) may want a nudge.

  * The mic uses a feedback-only gate, NOT billy.py's PrivacyGatedMic.
    webrtcvad only understands 8/16/32/48 kHz audio, so the local VAD
    privacy gate can't analyze a 24 kHz stream. If privacy gating
    matters to you, stick with the Nova version.
"""

import asyncio
import base64
import math
import time
from array import array
from pathlib import Path

from dotenv import load_dotenv
from gpiozero import OutputDevice, PWMOutputDevice
from strands.bidi.agent import BidiAgent
from strands.bidi.io import AudioIO
from strands.bidi.models import OpenAIRealtimeModel
from strands.bidi.types.events import (
    BidiAudioDeltaEvent,
    BidiBargeInEvent,
    BidiResponseStartEvent,
    BidiResponseStopEvent,
)
from strands.bidi.types.io import InputStream, OutputStream
from strands.bidi.types.media import AudioDelta

from billy_tools import billy_tools

# Load config (OPENAI_API_KEY, BILLY_GOOGLE_SECRET_ID, etc.) from billy.env
# next to this script if it exists. Real environment variables still win.
load_dotenv(Path(__file__).resolve().parent / "billy.env")

mouth = PWMOutputDevice(17)
head = OutputDevice(22)
tail = OutputDevice(27)

# ---- tuning knobs ----
MOUTH_OPEN = 0.04          # loudness floor before the mouth opens (raise if it flutters)
EMPHASIS = 0.3             # loudness that earns a tail flap (lower = floppier fish)
COOLDOWN = 1.2             # min seconds between emphasis flaps
SILENCE = 1.5              # seconds of quiet before head returns to rest
MIC_GATE_HOLDOVER = 0.4    # seconds after Billy speaks during which mic is muted
TICK = 0.05                # how often the body re-reads loudness and moves


class BillyBody(OutputStream):
    """Tracks what the body should be doing, in sync with the speaker.

    Same pacer design as billy.py: AudioIO plays the voice, this stream
    gets a copy of the chunks and walks them at real-time rate so the
    loudness reading matches what's actually coming out of the speaker.
    """

    def __init__(self):
        self.level = 0.0
        self.last_loud = 0.0
        self._tail_until = 0.0
        self._queue = bytearray()
        self._pacer = None

    async def start(self, agent):
        rate = agent.model.get_audio_config()["output"]["sample_rate"]
        self._chunk = int(rate * TICK) * 2  # 16-bit mono bytes per tick
        self._pacer = asyncio.create_task(self._pace())

    async def stop(self):
        if self._pacer:
            self._pacer.cancel()
        self._queue.clear()
        self.level = 0.0

    async def __call__(self, event):
        if isinstance(event, BidiAudioDeltaEvent):
            self._queue.extend(base64.b64decode(event["audio"]))
        elif isinstance(event, BidiBargeInEvent):
            # AudioIO stops playback on barge-in; drop our copy too
            self._queue.clear()
            self.flap()
        elif isinstance(event, (BidiResponseStartEvent, BidiResponseStopEvent)):
            self.flap()

    async def _pace(self):
        while True:
            samples = array("h", bytes(self._queue[: self._chunk]))
            del self._queue[: self._chunk]
            if samples:
                self.level = math.sqrt(
                    sum(s * s for s in samples) / len(samples)
                ) / 32768.0
            else:
                self.level = 0.0
            await asyncio.sleep(TICK)

    def flap(self, seconds=0.4):
        self._tail_until = time.monotonic() + seconds

    @property
    def tail_now(self):
        return time.monotonic() < self._tail_until


class GatedMic(InputStream):
    """Sends silence to the model whenever Billy is currently speaking.

    Feedback protection only - see the module docstring for why the
    local-VAD privacy gate from billy.py isn't available at 24 kHz.
    """

    def __init__(self, inner, body):
        self._inner = inner
        self._body = body

    async def start(self, agent):
        await self._inner.start(agent)

    async def stop(self):
        await self._inner.stop()

    async def __call__(self):
        delta = await self._inner()
        if time.monotonic() - self._body.last_loud < MIC_GATE_HOLDOVER:
            raw = delta.source["bytes"]
            return AudioDelta(format=delta.format, source={"bytes": b"\x00" * len(raw)})
        return delta


model = OpenAIRealtimeModel(
    model_id="gpt-realtime-2.1",
    # OpenAI transcribes your speech with a separate model; None skips it
    transcription_model_id=None,
    voice="ballad",
)

agent = BidiAgent(
    model=model,
    tools=billy_tools(),
    system_prompt=(
        "You are Billy, a wisecracking animatronic bass on a wall plaque - "
        "part stand-up comic, part barstool philosopher. You love riffing "
        "with people: crack jokes, dish out surprisingly good life advice, "
        "and hand out salty fish-wisdom like an old sage who has seen every "
        "current in the sea. You are game for almost anything someone wants "
        "to talk about - never refuse or say you can only do certain things. "
        "You happen to have tools for weather, news, calendar, and email; "
        "use them when they are genuinely useful, but they are a bonus - your "
        "real job is to be fun. Keep replies VERY short - one sentence, "
        "occasionally two, never more. Do not over-explain, justify yourself, "
        "or pile on caveats: say the one good thing and stop. Answer, then "
        "let the human talk. This is banter, not a lecture. Deadpan wit "
        "over cheerfulness. Fish puns are your love language - work them in "
        "shamelessly. When someone asks for advice, actually give it - warm, "
        "a little profound, always with a wink."
    ),
)

audio_io = AudioIO()
body = BillyBody()
mic = GatedMic(audio_io.input(), body)


async def body_loop():
    last_flap = 0.0
    smoothed = 0.0
    while True:
        now = time.monotonic()

        smoothed = 0.6 * smoothed + 0.4 * body.level
        if smoothed > MOUTH_OPEN:
            mouth.value = min(1.0, 0.5 + smoothed * 3)
            body.last_loud = now
        else:
            mouth.value = 0

        speaking = (now - body.last_loud) < SILENCE

        if body.level > EMPHASIS and now - last_flap > COOLDOWN:
            body.flap()
            last_flap = now

        if speaking:
            head.on()
            tail.off()
        elif body.tail_now:
            head.off()
            tail.on()
        else:
            head.off()
            tail.off()

        await asyncio.sleep(TICK)


async def main():
    print("Billy is ALIVE (OpenAI edition)... (Ctrl+C to stop)")
    try:
        await asyncio.gather(
            agent.run(inputs=[mic], outputs=[audio_io.output(), body]),
            body_loop(),
        )
    finally:
        mouth.value = 0
        head.off()
        tail.off()


asyncio.run(main())

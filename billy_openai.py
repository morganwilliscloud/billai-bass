"""BillAI Bass — alternate brain: OpenAI Realtime instead of Nova 2 Sonic.

Same fish, same motors, same tools — different model provider. Strands'
BidiAgent is provider-agnostic, so the swap is the model constructor, a
voice, and an accent line in the prompt. Everything below the model is
identical in spirit to billy.py; read that file's docstring for the
architecture.

Differences from billy.py you should know about:

  * Auth: needs OPENAI_API_KEY in the environment (no AWS credentials
    required for the model, though the Google tools still use them).
    Also `pip install websockets` — it isn't in requirements-frozen.txt.

  * Voice: OpenAI has its own voice lineup, separate from Nova's. This
    file uses `ballad` (which happens to have a British accent), but
    swap in any voice you like.

  * Audio runs at OpenAI's 24 kHz default (Nova is 16 kHz). The audio IO
    picks the rate up from the model config automatically, but the RMS
    thresholds (MOUTH_OPEN, EMPHASIS) may want a nudge.

  * The mic uses the original feedback-only gate, NOT billy.py's
    PrivacyGatedMic. webrtcvad only understands 8/16/32/48 kHz audio, so
    the local VAD privacy gate can't analyze a 24 kHz stream. If privacy
    gating matters to you, stick with the Nova version.
"""

import asyncio
import base64
import math
import time
from array import array

from gpiozero import OutputDevice, PWMOutputDevice
from strands.experimental.bidi import BidiAgent, BidiAudioIO
from strands.experimental.bidi.io.audio import _BidiAudioInput, _BidiAudioOutput
from strands.experimental.bidi.models import BidiOpenAIRealtimeModel
from strands.experimental.bidi.types.events import (
    BidiAudioInputEvent,
    BidiInterruptionEvent,
    BidiResponseCompleteEvent,
    BidiResponseStartEvent,
)

from billy_tools import billy_tools

mouth = PWMOutputDevice(17)
head = OutputDevice(22)
tail = OutputDevice(27)

# ---- tuning knobs ----
MOUTH_OPEN = 0.04          # loudness floor before the mouth opens (raise if it flutters)
EMPHASIS = 0.3             # loudness that earns a tail flap (lower = floppier fish)
COOLDOWN = 1.2             # min seconds between emphasis flaps
SILENCE = 1.5              # seconds of quiet before head returns to rest
MIC_GATE_HOLDOVER = 0.4    # seconds after Billy speaks during which mic is muted


class BillyBody(_BidiAudioOutput):
    """Plays the agent's voice AND tracks what the body should be doing."""

    def __init__(self, config):
        super().__init__(config)
        self.level = 0.0
        self.last_loud = 0.0
        self._tail_until = 0.0

    async def __call__(self, event):
        await super().__call__(event)
        if isinstance(
            event,
            (BidiResponseStartEvent, BidiResponseCompleteEvent, BidiInterruptionEvent),
        ):
            self.flap()

    def flap(self, seconds=0.4):
        self._tail_until = time.monotonic() + seconds

    @property
    def tail_now(self):
        return time.monotonic() < self._tail_until

    def _callback(self, in_data, frame_count, *args):
        data, flag = super()._callback(in_data, frame_count, *args)
        samples = array("h", data)
        if samples:
            self.level = math.sqrt(
                sum(s * s for s in samples) / len(samples)
            ) / 32768.0
        else:
            self.level = 0.0
        return (data, flag)


class GatedMic(_BidiAudioInput):
    """Sends silence to the model whenever Billy is currently speaking.

    Feedback protection only - see the module docstring for why the
    local-VAD privacy gate from billy.py isn't available at 24 kHz.
    """

    def __init__(self, config, body):
        super().__init__(config)
        self._body = body

    async def __call__(self):
        event = await super().__call__()
        if time.monotonic() - self._body.last_loud < MIC_GATE_HOLDOVER:
            raw = base64.b64decode(event["audio"])
            silence = base64.b64encode(b"\x00" * len(raw)).decode("utf-8")
            return BidiAudioInputEvent(
                audio=silence,
                channels=event["channels"],
                format=event["format"],
                sample_rate=event["sample_rate"],
            )
        return event


model = BidiOpenAIRealtimeModel(
    model_id="gpt-realtime",
    provider_config={
        "audio": {
            "voice": "ballad",
            "channels": 1,
            "format": "pcm",
        },
    },
)

agent = BidiAgent(
    model=model,
    tools=billy_tools(),
    system_prompt=(
        "You are Billy, a wisecracking animatronic singing bass on a wall "
        "plaque. RULE ONE: never say more than one short sentence at a time. "
        "5 to 12 words, then stop and let the human talk. This is rapid "
        "banter, not storytelling. Never list things, never explain, never "
        "monologue. Deadpan wit over enthusiasm. Fish puns are your love "
        "language - work them in shamelessly and often. You have tools for "
        "weather, news, Google Calendar, and email. Summarize tool results "
        "in one or two short spoken sentences - pick the few details that "
        "matter, never read lists or raw data aloud."
    ),
)

audio_io = BidiAudioIO()
body = BillyBody({})
mic = GatedMic({}, body)


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

        await asyncio.sleep(0.05)


async def main():
    print("Billy is ALIVE (OpenAI edition)... (Ctrl+C to stop)")
    try:
        await asyncio.gather(
            agent.run(inputs=[mic], outputs=[body]),
            body_loop(),
        )
    finally:
        mouth.value = 0
        head.off()
        tail.off()


asyncio.run(main())

"""BillAI Bass — the working voice-assistant fish.

Architecture:
    BidiAgent (Strands)  <-->  Nova 2.5 Sonic on Amazon Bedrock
        |
        +-- AudioIO            (Strands built-in)
        |       USB mic in, USB speaker out
        |
        +-- PrivacyGatedMic    (wraps AudioIO's input stream)
        |       sends silence to the model unless local VAD hears real
        |       speech (privacy: ambient audio never leaves the house),
        |       and whenever Billy is speaking, so he can't hear his
        |       own voice through the speaker
        |
        +-- BillyBody          (extra output stream, alongside AudioIO)
                receives the same audio chunks the speaker plays and
                paces through them at real-time rate, so its loudness
                reading tracks what's coming out of the speaker right
                now - that loudness drives the mouth, head, and tail

The mouth is PWM-driven from smoothed loudness. The head and tail share
one motor (Modern Billy hardware), so they're mutually exclusive: head
out while audio plays, tail flap on emphasis peaks and lifecycle events.

Everything here is the public strands.bidi API (GA since 1.58). The
agent also inherits two GA behaviors for free: barge-in (talk over
Billy and he stops) and automatic connection restarts, so conversations
can outlive Nova's eight-minute session limit.

Tuning knobs are at the top of the file. See BUILD_GUIDE.md sections
"Final-stage gotchas" and "Make it yours" for context.
"""

import asyncio
import base64
import math
import sys
import time
import webrtcvad
from array import array
from pathlib import Path

from dotenv import load_dotenv
from gpiozero import OutputDevice, PWMOutputDevice
from strands.bidi.agent import BidiAgent
from strands.bidi.io import AudioIO
from strands.bidi.models import BedrockNovaSonicModel
from strands.bidi.types.events import (
    BidiAudioDeltaEvent,
    BidiBargeInEvent,
    BidiResponseStartEvent,
    BidiResponseStopEvent,
)
from strands.bidi.types.io import InputStream, OutputStream
from strands.bidi.types.media import AudioDelta

from billy_tools import billy_tools

# Load config (BILLY_GOOGLE_SECRET_ID, BILLY_LATITUDE, etc.) from billy.env
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

    AudioIO plays the voice; this stream gets a copy of the same audio
    chunks. The model streams audio faster than real time, so measuring
    chunks as they arrive would move the mouth ahead of the sound.
    Instead, a pacer task walks the queued bytes at exactly the audio
    sample rate, keeping the loudness reading (and the mouth) in step
    with playback.
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


class PrivacyGatedMic(InputStream):
    """Gates the microphone locally using WebRTC VAD to protect user privacy.

    Wraps AudioIO's input stream: only passes real audio through when
    local voice is detected, otherwise substitutes silence. Also mutes
    the mic while Billy himself is speaking (feedback prevention) -
    his speaker and mic are separate USB devices inches apart, which
    defeats echo cancellation, so a hard gate it is.
    """

    def __init__(self, inner, body, vad_aggressiveness=3, timeout=5.0):
        self._inner = inner
        self._body = body
        self._vad = webrtcvad.Vad(vad_aggressiveness)
        self._timeout = timeout
        self._vad_buffer = b""
        self._last_speech_time = 0.0
        self._is_listening = False

    async def start(self, agent):
        rate = agent.model.get_audio_config()["input"]["sample_rate"]
        if rate != 16000:
            raise ValueError(f"webrtcvad gate expects 16 kHz mic audio, model wants {rate}")
        await self._inner.start(agent)

    async def stop(self):
        await self._inner.stop()

    async def __call__(self):
        delta = await self._inner()
        raw_audio = delta.source["bytes"]

        # 1. Check if the fish body is currently speaking (feedback prevention)
        if time.monotonic() - self._body.last_loud < MIC_GATE_HOLDOVER:
            return self._silence(delta, len(raw_audio))

        # 2. Run VAD analysis on the incoming chunk
        self._vad_buffer += raw_audio
        frame_size = 960  # 30ms frame at 16kHz 16-bit mono

        has_speech = False
        while len(self._vad_buffer) >= frame_size:
            frame = self._vad_buffer[:frame_size]
            self._vad_buffer = self._vad_buffer[frame_size:]

            # webrtcvad returns True if speech is detected
            if self._vad.is_speech(frame, 16000):
                has_speech = True
                break

        now = time.monotonic()
        if has_speech:
            if not self._is_listening:
                print("[VAD] Speech detected. Un-gating microphone.")
                self._is_listening = True
            self._last_speech_time = now
        elif self._is_listening and (now - self._last_speech_time > self._timeout):
            print("[VAD] No speech detected. Gating microphone.")
            self._is_listening = False

        # 3. Pass real audio in the Listening state; otherwise digital silence
        if self._is_listening:
            return delta
        return self._silence(delta, len(raw_audio))

    @staticmethod
    def _silence(delta, length):
        return AudioDelta(format=delta.format, source={"bytes": b"\x00" * length})


def _fish_boto_session():
    """Use the fish's IoT device certificate for AWS auth if it's installed.

    The optional iot-identity/ setup (see iot-identity/IOT_SETUP.md) gives the
    fish short-lived, auto-refreshing credentials scoped to just Nova Sonic, so
    no long-lived AWS key ever lives on the SD card. We detect it by the
    presence of the identity files; if they're there, the model gets a boto
    session backed by the certificate. If they're absent, we return None and
    the model falls back to the default AWS credential chain (an access key
    in ~/.aws, environment variables, etc.), so non-IoT builds are unaffected.
    A real failure (revoked cert, bad endpoint) is left to raise.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent / "iot-identity"))
    try:
        import fish_credentials
    except ImportError:
        return None
    if not (fish_credentials.IDENTITY_DIR / "endpoint.txt").exists():
        return None
    return fish_credentials.fish_boto_session()


_session = _fish_boto_session()
if _session is not None:
    # Make the fish's cert-backed session the process-wide default, so
    # billy_tools' Secrets Manager call (the Google token fetch) also
    # authenticates as the fish.
    import boto3

    boto3.DEFAULT_SESSION = _session

model = BedrockNovaSonicModel(
    model_id="amazon.nova-2-5-sonic",
    voice="matthew",
    params={"turnDetectionConfiguration": {"endpointingSensitivity": "LOW"}},
    **({"boto_session": _session} if _session is not None else {"region": "us-east-1"}),
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
mic = PrivacyGatedMic(audio_io.input(), body)


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
    print("Billy is ALIVE... (Ctrl+C to stop)")
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

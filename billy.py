"""BillAI Bass — the working voice-assistant fish.

Architecture:
    BidiAgent (Strands)  <-->  Nova 2 Sonic on Amazon Bedrock
        |
        +-- GatedMic       (subclass of _BidiAudioInput)
        |       sends silence to model whenever Billy is speaking,
        |       so he can't hear his own voice through the speaker
        |
        +-- BillyBody      (subclass of _BidiAudioOutput)
                plays Nova's audio AND measures RMS in the PyAudio
                callback to drive the mouth, head, and tail in sync
                with the bytes hitting the speaker right now

The mouth is PWM-driven from smoothed loudness. The head and tail share
one motor (Modern Billy hardware), so they're mutually exclusive: head
out while audio plays, tail flap on emphasis peaks and lifecycle events.

Tuning knobs are at the top of the file. See BUILD_GUIDE.md sections
"Final-stage gotchas" and "Make it yours" for context.

Note: subclasses two private classes from strands.experimental.bidi
(_BidiAudioInput, _BidiAudioOutput). Pin Strands to a known-good version
in requirements-frozen.txt; a future SDK release may break this.
"""

import asyncio
import base64
import math
import time
from array import array

from gpiozero import OutputDevice, PWMOutputDevice
from strands.experimental.bidi import BidiAgent, BidiAudioIO
from strands.experimental.bidi.io.audio import _BidiAudioInput, _BidiAudioOutput
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.types.events import (
    BidiAudioInputEvent,
    BidiInterruptionEvent,
    BidiResponseCompleteEvent,
    BidiResponseStartEvent,
)

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
    """Sends silence to the model whenever Billy is currently speaking."""

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


model = BidiNovaSonicModel(
    model_id="amazon.nova-2-sonic-v1:0",
    provider_config={
        "audio": {
            "input_rate": 16000,
            "output_rate": 16000,
            "voice": "matthew",
            "channels": 1,
            "format": "pcm",
        },
        "turn_detection": {"endpointingSensitivity": "LOW"},
    },
)

agent = BidiAgent(
    model=model,
    system_prompt=(
        "You are Billy, a wisecracking animatronic singing bass on a wall "
        "plaque. RULE ONE: never say more than one short sentence at a time. "
        "5 to 12 words, then stop and let the human talk. This is rapid "
        "banter, not storytelling. Never list things, never explain, never "
        "monologue. Deadpan wit over enthusiasm. Fish puns are your love "
        "language - work them in shamelessly and often."
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
    print("Billy is ALIVE... (Ctrl+C to stop)")
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

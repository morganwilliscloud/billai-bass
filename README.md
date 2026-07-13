# 🐟 BillAI Bass Builder Guide
### Powered by Strands Agents Bidirectional Streaming + Amazon Nova 2 Sonic


https://github.com/user-attachments/assets/02e84cd4-72e2-4b01-8b80-c83e910037e6


Turn a Big Mouth Billy Bass into a real-time voice assistant: you talk, the fish talks back — head swiveling, mouth lip-syncing to its own voice, tail flapping for emphasis. The fish runs a [Strands Agents](https://strandsagents.com) **bidirectional streaming agent** (`BidiAgent`) on a Raspberry Pi 5, streaming live audio to and from **Amazon Nova 2 Sonic** on Amazon Bedrock.

No robotics experience needed. No prior soldering experience needed. The person this guide is based on had never plugged in a Raspberry Pi before and got a talking fish in a weekend.

> Inspired by the excellent [billy-b-assistant](https://github.com/Thokoop/billy-b-assistant) project, rebuilt on Strands.

## What's in this repo

| File | What it is |
|---|---|
| `README.md` | This guide — start here, work top to bottom |
| `billy.py` | The final working Python — the talking fish |
| `motors.py` | Standalone motor test rig — run this before `billy.py` to verify wiring |
| `asoundrc.example` | The ALSA config that pins the USB mic + speaker as defaults |
| `requirements-frozen.txt` | Exact dependency versions from a known-good Pi build — `pip install -r` for guaranteed-working setup |
| `iot-identity/` | **Optional** production-grade credentials: CloudFormation template + walkthrough for X.509-cert auth instead of access keys |

## How to use this with an AI assistant

Paste this README into Claude (or another AI assistant) and say: *"I'm building this. Walk me through it one step at a time — wait for me to confirm each step before giving the next."* That's the way it was built; that's the way it builds best. See the **Build this WITH an AI Assistant** section below for what to send when stuck.

---

## 🤝 Build this WITH an AI Assistant

This project was created **with help from Claude Code** and you can use any AI assistant to help you get through.

**Paste this entire guide into your AI and say: "I'm building this. Walk me through it one step at a time — wait for me to confirm each step before giving the next."**

Your AI will pace the build to you, debug your exact error messages, and adapt when your hardware differs slightly from this guide. Things AI is great at during this build:

- **Paste your exact error message** — the scary 50-line Python traceback usually has one meaningful line, and AI will find it.
- **Send photos** — stuck identifying a motor? Can't tell which pin is which? Photograph it and ask. (In Claude Code on a Mac: drop the image file into the terminal, or say "look at ~/Downloads/IMG_1234.jpg".)
- **Say "I know nothing about X"** — AI will back up and explain. There are no dumb questions.
- **Ask before cutting/soldering anything you're unsure about.**

If you hit something this guide doesn't cover, that's not a failure of you. It's probably a gap in the guide. AI + your error message will get you through.

---

## 🛒 Shopping list

**If you got a kit: you have everything in this table already.** Building from scratch: this is the original Amazon order (~$240 total, January 2026 prices).

| Item | What it's for | ~Price |
|---|---|---|
| Big Mouth Billy Bass (current "Gemmy" version) | The fish. The modern version has 2 motors, which this guide assumes | $30 |
| Raspberry Pi 5, 8GB | The brain. 4GB would also work | $80 |
| 27W USB-C PD power supply (official Pi or RasTech GaN) | **Don't substitute a phone charger** — the Pi limits power to USB ports without a proper supply | $15 |
| Official Raspberry Pi 5 Active Cooler | Heatsink + fan. The Pi runs hot without it | $10 |
| MicroSD card, 64GB (e.g. Transcend USD340, any name brand) | The Pi's hard drive | $12 |
| USB mini speaker (e.g. HONKYOB) | Billy's voice | $15 |
| USB gooseneck mini microphone (e.g. CGS-M1) | Billy's ears | $13 |
| MX1508 dual H-bridge motor driver, 5-pack (e.g. Aideepen, sold as "L298N replacement") | Lets the Pi safely drive the motors. You need 1; the spares forgive mistakes | $9 |
| DuPont jumper wire kit, 120pc male/female mix (e.g. ELEGOO) | Connects driver board to Pi. You'll use ~6 female-to-female | $7 |
| Soldering iron kit, 60W adjustable with tips + solder | 10 solder joints total. Cheapest kit is fine | $20 |
| Flush cutters (e.g. KATA 2-pack) | Snipping and stripping wires | $9 |
| JST XH connector kit | *Optional* — handy for tidy splices, but the build works without it | $9 |

**Also needed, not in the kit:**
- A **personal computer** (Mac/Windows/Linux) to flash the SD card — ⚠️ corporate laptops often block USB storage; use a home machine
- A way to plug a microSD into that computer (most cards include an SD adapter)
- An **AWS account** (personal, not your employer's) with a payment method — you'll create a locked-down, fish-only IAM user in the prerequisites below
- Tape (electrical ideally, Scotch works), a small Phillips screwdriver
- Home WiFi that both your computer and the Pi can join

---

## ✅ Prerequisites (do these before build day)

### 1. AWS / Amazon Bedrock setup (least privilege — do it right)

**💸 No AWS account yet? The free tier covers this project.** New AWS accounts get $100 in credits (up to $200 with activities), and Amazon Bedrock is usable on the free plan with credits applied to Nova usage. Voice chat is cheap — roughly **a penny per few minutes of conversation** — so credits buy on the order of 100+ hours of fish banter. Two free-plan caveats:
- **Brand-new accounts sometimes start with Bedrock invocation quotas set to zero** (no payment history yet). If model access is granted but every call fails with `ValidationException: Operation not allowed`, that's the quota — file a (free) AWS support case asking for Nova Sonic on-demand quota, or upgrade to the paid plan (your remaining credits carry over).
- **Free-plan accounts auto-close after 6 months** (or when credits run out). Fine for a demo fish; if Billy's becoming a permanent housemate, upgrade to paid before the deadline — unused credits survive the upgrade.

Your AWS keys will live in a plaintext file on a Pi inside a fish. Fish get demoed, lent out, and left on desks; SD cards pop out. So the keys must be able to do **exactly one thing**: talk to Nova Sonic. If they leak, the worst case is someone chats with a fish on your dime — not someone mining crypto in your account.

**Step 1 — Enable model access:**
1. In the AWS console, switch region to **us-east-1 (N. Virginia)** — Nova Sonic lives there.
2. Go to **Amazon Bedrock → Model access** and request access to **Nova 2 Sonic** (`amazon.nova-2-sonic-v1:0`). Usually instant. (Not v1 — original Nova Sonic hits end-of-life September 2026.)

**Step 2 — Create a dedicated IAM user:**
1. Console → **IAM → Users → Create user**. Name it something honest like `billy-bass`.
2. **Do NOT check "Provide user access to the AWS Management Console"** — this user is a robot fish; it never logs into anything.
3. On the permissions screen, choose **"Attach policies directly"** but **don't select any** of the AWS-managed policies (no `AmazonBedrockFullAccess` — that grants far more than the fish needs). Just click through and create the user with zero permissions.

**Step 3 — Attach a policy that allows only Nova Sonic:**
1. Open the new user → **Permissions → Add permissions → Create inline policy** → **JSON** tab.
2. Paste:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Sid": "BillyTalksToNovaSonicOnly",
         "Effect": "Allow",
         "Action": "bedrock:InvokeModelWithBidirectionalStream",
         "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-sonic-v1:0"
       }
     ]
   }
   ```
3. Name it `billy-nova-sonic-only`, save.

That's one action on one model in one region. No S3, no EC2, no other Bedrock models, no ability to see or change anything else in your account. (If you later give Billy tools that touch AWS — say, reading a DynamoDB table — add *that specific permission* to this policy then, not broad access now.)

**Step 4 — Create the access key:**
1. User → **Security credentials → Create access key** → choose "Application running outside AWS".
2. Copy the **access key ID + secret** somewhere safe — the secret is shown exactly once. These go on the Pi later (§1.6).

**Step 5 — Optional but smart: set a billing alarm.** Console → Billing → Budgets → create a $10/month budget with an email alert. Casual Nova Sonic chat costs cents; the alarm is there so a stuck always-listening fish (or leaked key) can't surprise you.

If the keys ever leak or a kit fish goes missing: IAM → user `billy-bass` → Security credentials → **deactivate the access key**. One click, fish bricked, account safe.

### 2. Know the two paste gotchas (you WILL hit these)
When you paste code into a terminal/nano over SSH, two things love to go wrong:
- **Extra indentation**: every pasted line gains leading spaces. ALSA config shrugs; **Python explodes** (`IndentationError: unexpected indent` on line 1 is the signature). Fix: `sed -i 's/^  //' yourfile.py`, or re-paste into nano carefully.
- **Dropped/mangled characters**: a missing comma, or quotes turned into “smart quotes.”

**The habit that saves you**: after creating any Python file, run
```bash
python -m py_compile yourfile.py && echo OK
```
before running it for real. If it doesn't say OK, paste the error to Claude.

---

# Part 1 — The Brain (Raspberry Pi, no fish yet)

> **Strategy note:** we get the *entire* voice assistant working on the bare Pi first, and only then open the fish. Software problems and hardware problems are much easier to debug when they can't be each other.

## 1.1 Flash the SD card

On your personal computer:

1. Download **Raspberry Pi Imager** from [raspberrypi.com/software](https://raspberrypi.com/software), insert the microSD.
2. Choose: Device = **Raspberry Pi 5** · OS = **Raspberry Pi OS Lite (64-bit)** · Storage = your card.
   - ⚠️ **OS version matters**: you need an image with **Python 3.12+** (Nova Sonic requirement). The current "Trixie"-based Raspberry Pi OS ships 3.13 ✅. Old "Bookworm" images ship 3.11 ❌.
   - "Lite" = no desktop. Correct — you'll never plug in a monitor.
3. ⚠️ **Pick "Lite" carefully.** In the OS list, expand "Raspberry Pi OS (other)" and choose **Raspberry Pi OS Lite (64-bit)** — *not* the regular "Raspberry Pi OS (64-bit)" at the top of the list, which is the **Desktop** edition. The Desktop edition ships a Wayfire panel that aggressively rewrites `~/.asoundrc` on every login, breaking your audio config repeatedly with no obvious cause. Lite has no GUI and no panel.

   *Already installed Desktop by mistake?* It's fixable without re-flashing — `sudo systemctl set-default multi-user.target && sudo systemctl disable lightdm.service && sudo reboot` makes Desktop boot like Lite. But Lite from the start is cleaner.

4. When asked about **OS customisation, say yes** — this is the magic step:
   - Hostname: `billy`
   - Username + password: pick and **remember them**
   - WiFi: your network name + password, *exactly* right (a typo here = mystery no-show later)
   - Services tab: **enable SSH** (password authentication)
5. Write, wait, eject. ("Raspberry Pi Connect" prompt: skip it — you can add remote access later with one command if you ever demo this somewhere.)

## 1.2 First boot

1. MicroSD into the slot on the Pi's underside. Plug in the USB-C power supply — **there is no power button; plugging in = on.**
2. Wait **2–3 minutes** (first boot resizes things and joins WiFi).
3. From your computer's terminal:
   ```bash
   ssh yourusername@billy.local
   ```
   Type `yes` (lowercase) at the fingerprint prompt, then your password (the cursor won't move while typing a password — normal).

**Gotchas:**
- **`Connection reset` right after the fingerprint prompt** → the Pi is still finishing first-boot setup. Wait 1–2 minutes, try again. (If it then complains `REMOTE HOST IDENTIFICATION HAS CHANGED`: run `ssh-keygen -R billy.local` and retry — the Pi regenerated its key mid-setup, this is expected.)
- **`billy.local` not found** → wait longer; then check your router's device list for "billy" and SSH to its IP. Persistent no-show usually = WiFi password typo → re-flash.
- **When done for the day**: run `sudo shutdown now`, wait ~20s, then unplug. Don't just yank power.

## 1.3 System packages

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y python3-dev portaudio19-dev swig git
```

(`portaudio19-dev` → microphone/speaker access for Python. `swig` → needed to build the GPIO library later; installing it now avoids a confusing error.)

## 1.4 Audio devices

Plug the USB mic and USB speaker into the Pi, then:

```bash
arecord -l   # lists MICROPHONES — note your card name, e.g. "Device"
aplay -l     # lists SPEAKERS — note yours, e.g. "UACDemoV10" (ignore the two vc4hdmi entries)
```

⚠️ **Use card NAMES, never numbers** — the numbers shuffle between reboots (this bit the original build). Now make your USB devices the system default. Create the config with nano (heredocs + SSH paste = pain; nano is your friend):

```bash
nano ~/.asoundrc
```

Paste, substituting YOUR two card names:

```
pcm.!default {
    type asym
    playback.pcm "plug:hw:UACDemoV10"
    capture.pcm "plug:hw:Device"
}
ctl.!default {
    type hw
    card UACDemoV10
}
```

Save (Ctrl+O, Enter) and exit (Ctrl+X). Then **verify the file actually exists** — `cat ~/.asoundrc` should echo it back. (In the original build this file silently failed to save, which surfaced as a baffling crash *days* later. Trust nothing; `cat` everything.)

**The round-trip test** — record 3 seconds of yourself, play it back:

```bash
arecord -d 3 -f S16_LE -r 16000 test.wav && aplay test.wav
```

Hear yourself? **The hardest Pi-specific problem is now behind you.** (16000 Hz is deliberate — that's Nova Sonic's rate.)

## 1.5 Python environment + Strands

```bash
python3 -m venv ~/billy/.venv
source ~/billy/.venv/bin/activate
pip install "strands-agents[bidi,bidi-io]" gpiozero lgpio
```

Notes:
- `(.venv)` appearing in your prompt = venv active. **You must re-run the `source` line in every new SSH session** — if Python suddenly can't find strands, that's why.
- If `lgpio` fails to build mentioning `swig`: you skipped step 1.3's swig install. `sudo apt install -y swig`, retry.
- **Pin your version**: this build uses Strands' *experimental* bidi API and subclasses a private class. Run `pip freeze | grep strands` and write the version down. If a future upgrade breaks things, you can return to it.

## 1.6 AWS credentials — in a file, not exports

Use the keys from the dedicated `billy-bass` IAM user you created in the prerequisites (the one that can *only* call Nova Sonic) — never your personal/root AWS keys. Environment variables vanish every time you log out (this caused a crash mid-build), so do it permanently:

```bash
mkdir -p ~/.aws
nano ~/.aws/credentials
```
```
[default]
aws_access_key_id = YOUR_KEY_ID
aws_secret_access_key = YOUR_SECRET
```
```bash
nano ~/.aws/config
```
```
[default]
region = us-east-1
```
```bash
chmod 600 ~/.aws/credentials
```

## 1.7 First conversation 🎉

`nano ~/billy/billy.py`:

```python
import asyncio
from strands.experimental.bidi import BidiAgent, BidiAudioIO
from strands.experimental.bidi.models import BidiNovaSonicModel

model = BidiNovaSonicModel(
    model_id="amazon.nova-2-sonic-v1:0",
    provider_config={
        "audio": {
            "input_rate": 16000,
            "output_rate": 16000,
            "voice": "matthew",
            "channels": 1,
            "format": "pcm",
        }
    },
)

agent = BidiAgent(
    model=model,
    system_prompt=(
        "You are Billy, a wisecracking animatronic singing bass mounted on a "
        "wooden plaque. Keep responses short, punchy, and conversational."
    ),
)

audio_io = BidiAudioIO()

asyncio.run(agent.run(inputs=[audio_io.input()], outputs=[audio_io.output()]))
```

```bash
python -m py_compile ~/billy/billy.py && echo OK
python ~/billy/billy.py
```

Wait a few seconds, then just talk. **You should have a voice conversation.** Ctrl+C to stop.

**Gotchas:**
- A wall of `ALSA lib...` warnings at startup is **normal noise** — ignore anything that isn't a Python `Traceback`.
- `AccessDeniedException` → Bedrock model access not granted, or wrong region.
- `no AWS credentials found` → step 1.6 not done (or typo'd).
- `OSError: Invalid sample rate` → your `~/.asoundrc` is missing or has wrong card names (run `cat ~/.asoundrc` and `arecord -l` and compare).
- **Billy interrupts himself** → the mic hears the speaker and the model thinks you're barging in. Point the mic away from the speaker, lower the volume. Physical placement fixes this.

---

# Part 2 — The Body (open the fish)

## 2.1 Surgery 101

Remove the ~6 screws on Billy's backplate. **Take the batteries out and leave them out.** Inside you'll find a small zoo of black lumps; here's the field guide:

| Looks like | Is | Fate |
|---|---|---|
| Thumb-sized **silver cylinder + black gearbox**, 2 wires | **A motor** | KEEP |
| Round disc with grille holes (on the backplate) | Original speaker | retire |
| **Coin-sized flat silver disc**, 2 wires | Piezo buzzer (not a motor!) | retire |
| Small board where every wire terminates | Original control board | retire |
| Wires to a button on the front | The push button | KEEP (future "talk to me" trigger) |
| Wires to a little window/sensor on the front | Light/motion sensor | retire |

**Count the motors.** Modern Billy (sold today) = **2 motors**: one for the mouth, one shared motor that turns the **head when spun one way and flaps the tail when spun the other**. Classic Billy (1999–2005) = 3 separate motors (this guide covers Modern; for Classic, ask Claude to adapt — you'll need a second driver board and one more GPIO pin).

⚠️ **Trace wires with your finger; don't trust colors.** Editions vary. In the original build, the "obvious" guess about which motor was which was *backwards* — the motor visible near the tail was the body motor, the mouth motor was buried near the head.

Optional sanity check: with batteries in (fish closed), press the button — the factory song-and-dance proves both motors work. Do this once before surgery if you want peace of mind.

## 2.2 Disconnect & label

1. Free the **motor wires** and **button wires** from the original board — unplug if they're on connectors, otherwise snip **close to the board** (maximize wire length on the side you keep).
2. **Label each pair with tape flags immediately**: `MOUTH`, `BODY`, `BUTTON`. The colors are your only documentation once the board's gone.
3. The board, piezo, speaker, and sensor come out. Keep the button.

---

# Part 3 — Connecting Brain to Body

## 3.1 Meet the motor driver

The Pi's GPIO pins can *whisper* (3.3V signals) but motors need a *shout* (real current) — wiring a motor straight to the Pi kills the pin. The **MX1508 driver board** is the translator: the Pi whispers commands at its inputs, it shouts 5V at the motors. It has two channels (A and B) — one per motor. Convenient.

The board has **bare holes**, so this is where you solder: 10 joints total, the easiest kind there is. Watch any 3-minute "how to solder" video first if you've never done it. You have 5 boards — mistakes are free.

## 3.2 Prepare the wires

Take **6 female-to-female DuPont wires** in six distinct colors. For each: snip **one** plastic end off, strip ~5mm of insulation (bite gently with flush cutters, slide the sleeve off), twist the strands tight.

The color map used in this build (adjust to your colors, but **write yours down**):

| Wire | Driver hole | Job |
|---|---|---|
| yellow | **+** | 5V power |
| black | **−** | ground |
| white | IN1 | mouth (one direction) |
| grey | IN2 | mouth (other direction) |
| purple | IN3 | body motor → head |
| blue | IN4 | body motor → tail |

## 3.3 Solder

For each wire: poke the bare end **down through the top** of its hole (label side up), bend the protruding tip slightly so it stays, flip the board, then: iron tip touching **both the wire and the metal ring**, count two seconds, feed in solder, pull solder away then iron away. You want a small shiny cone gripping the wire.

Then the motor wires into the output holes (strip/twist/solder the same way):
- **mouth motor pair → MOTOR A** holes
- **body motor pair → MOTOR B** holes
- (Within a pair, either hole — backwards just reverses direction, which is fixed in software.)

**Quality control — do all three, on every joint:**
1. **Tug test**: pull each wire firmly. It must not budge.
2. **Wiggle test**: push it side to side. If the solder *blob itself* pivots on the board, it's not bonded — reheat 3 full seconds touching blob AND ring.
3. **Bridge check**: in raking light, confirm a gap between every neighboring blob — **especially between + and −** (that bridge = short circuit).

**Known failure modes from the original build (both fixable in 2 minutes):**
- *Wire pops out leaving a solder-plugged hole* → reheat the blob till liquid, push the wire back in, hold still 2 seconds.
- *"Surface tack"* — wire stuck onto the top of the blob instead of through the hole. It conducts… until it pops off inside the fish. Redo it properly.

## 3.4 Plug into the Pi

**Pi shut down (`sudo shutdown now`) and unplugged first.**

Orientation, with zero jargon: the Pi's 40 pins form **two long rows**. The pair of pins at the end **nearest the USB-C power connector** is the start. The row along the board's **edge** is the *even* row (2, 4, 6…); the **inner** row is *odd* (1, 3, 5…). Count positions from the power-connector end:

| Wire | Pi pin | Find it |
|---|---|---|
| yellow (+) | pin 4 | **edge row, 2nd position** |
| black (−) | pin 6 | edge row, 3rd (next to yellow) |
| white (IN1) | pin 9 | inner row, 5th |
| grey (IN2) | pin 11 | inner row, 6th |
| blue (IN4) | pin 13 | inner row, 7th |
| purple (IN3) | pin 15 | inner row, 8th |

Sanity-check the pattern: yellow+black as a pair near the start on the edge row; then white-grey-blue-purple as **one unbroken run of four** on the inner row. **Photograph it and ask Claude to verify before powering on** — this is the one step where a miscount matters (pin 4 carries 5V).

> Heads-up: the table above already includes a fix discovered during testing (white on 9, grey on 11). If your mouth turns out weak, see §3.6 — your motor may prefer the other direction, and the fix is swapping those two plugs.

## 3.5 Install the Active Cooler (while you're here)

Peel the film off the cooler's thermal pads, align it over the big silver chip, press the two spring push-pins through the board's mounting holes until they click (support the board from beneath), and plug the fan cable into the tiny **FAN** socket near the header's far end. The fan only spins when hot — silence is normal. Check with `vcgencmd measure_temp` (under 60°C = happy).

## 3.6 Power on + motor test

Power up. **The fish should be completely still.** (A motor running by itself = a wire on the wrong pin; unplug and recount.)

SSH in, venv on, then `nano ~/billy/motors.py`:

```python
import time

from gpiozero import OutputDevice, PWMOutputDevice

mouth = PWMOutputDevice(17)
head = OutputDevice(22)
tail = OutputDevice(27)

print("m = mouth (1s)  h = head (1s)  t = tail  b = both  q = quit")

while True:
    cmd = input("> ").strip().lower()
    if cmd == "q":
        break
    elif cmd == "m":
        mouth.value = 1.0
        time.sleep(1.0)
        mouth.value = 0
    elif cmd == "h":
        head.on()
        time.sleep(1.0)
        head.off()
    elif cmd == "t":
        tail.on()
        time.sleep(0.3)
        tail.off()
    elif cmd == "b":
        head.on()
        time.sleep(0.3)
        for _ in range(4):
            mouth.value = 1.0
            time.sleep(0.25)
            mouth.value = 0
            time.sleep(0.15)
        time.sleep(0.2)
        head.off()

mouth.value = 0
head.off()
tail.off()
```

`py_compile` it, run it, and try `m`, `h`, `t` with eyes on the fish.

**Motor-test gotchas (all hit in the original build):**
- **Wrong thing moves** → your IN-pin guesses met reality. No rewiring: tell Claude what each key did and swap the GPIO numbers (17/22/27) in software, or swap plugs at the Pi header.
- **"Where's the head motor?? I only have mouth and tail!"** → `h` and `t` are the *same motor*, opposite directions. Both work; never drive both at once (the script never does).
- **Mouth opens weakly while tail is strong** → ⭐ the classic one. The mouth fights a return spring AND these motors are often strong in only one direction. Fix: **swap the two mouth wires at the Pi header** (white ↔ grey in our map) so the code drives the strong direction. Secondary suspects: not using the 27W supply; 20-year-old gummy grease (work the jaw by hand 30 times).
- **Nothing at all on one key** → re-tug that wire's solder joints.

When `b` makes Billy raise his head and flap his mouth like he's talking — pause and enjoy it. That's the whole machine working.

---

# Part 4 — The Fusion (talking fish)

The trick that makes lip-sync work: Nova Sonic sends audio *much faster than it plays* (a 10-second sentence arrives in ~1 second), so you can't flap the mouth when data arrives. Instead, this code measures loudness inside the audio system's playback callback — the exact bytes hitting the speaker *right now* — and drives the mouth from that. Head position comes from "is audio currently playing," and the tail flaps on loud moments and conversation events.

`nano ~/billy/billy_final.py`:

```python
import asyncio
import math
import time
from array import array

from gpiozero import OutputDevice, PWMOutputDevice
from strands.experimental.bidi import BidiAgent, BidiAudioIO
from strands.experimental.bidi.io.audio import _BidiAudioOutput
from strands.experimental.bidi.models import BidiNovaSonicModel
from strands.experimental.bidi.types.events import (
    BidiInterruptionEvent,
    BidiResponseCompleteEvent,
    BidiResponseStartEvent,
)

mouth = PWMOutputDevice(17)
head = OutputDevice(22)
tail = OutputDevice(27)

# ---- tuning knobs ----
MOUTH_OPEN = 0.04   # loudness floor before the mouth opens (raise if it flutters)
EMPHASIS = 0.3      # loudness that earns a tail flap (lower = floppier fish)
COOLDOWN = 1.2      # min seconds between emphasis flaps
SILENCE = 1.5       # seconds of quiet before the head comes back down


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


model = BidiNovaSonicModel(
    model_id="amazon.nova-2-sonic-v1:0",
    provider_config={
        "audio": {
            "input_rate": 16000,
            "output_rate": 16000,
            "voice": "matthew",
            "channels": 1,
            "format": "pcm",
        }
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


async def body_loop():
    last_flap = 0.0
    smoothed = 0.0
    while True:
        now = time.monotonic()

        # mouth: smoothed loudness -> motor power
        smoothed = 0.6 * smoothed + 0.4 * body.level
        if smoothed > MOUTH_OPEN:
            mouth.value = min(1.0, 0.5 + smoothed * 3)
            body.last_loud = now
        else:
            mouth.value = 0

        speaking = (now - body.last_loud) < SILENCE

        # tail: flap on emphasis peaks (rate-limited)
        if body.level > EMPHASIS and now - last_flap > COOLDOWN:
            body.flap()
            last_flap = now

        # one motor drives head AND tail (opposite directions): head wins
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
            agent.run(inputs=[audio_io.input()], outputs=[body]),
            body_loop(),
        )
    finally:
        mouth.value = 0
        head.off()
        tail.off()


asyncio.run(main())
```

```bash
python -m py_compile ~/billy/billy_final.py && echo OK
python ~/billy/billy_final.py
```

Talk to your fish. Expected choreography: head rises as Billy answers → mouth lip-syncs every word → head drops ~1.5s after he finishes → cheeky tail flap → rest. Interrupt him mid-sentence and everything drops at once.

**Final-stage gotchas:**
- **Head goes up and never comes down** → that's why head state is based on *audio silence*, not the model's "response complete" event — live sessions don't reliably end responses. If you see it anyway, lower `SILENCE`.
- **Tail never flaps** → lower `EMPHASIS` (the voice may be too even-keeled). You proved the tail works in motors.py, so it's purely a threshold.
- **Mouth flutters during pauses** → raise `MOUTH_OPEN`.
- **Billy talks too much** → it's the system prompt. The hard rules in there ("never more than one short sentence", "banter, not storytelling") are what keep him snappy — vague "be concise" doesn't work. Tune the personality to taste; this is the fun part.

---

## 🎨 Make it yours / next steps

- **Personality**: the `system_prompt` is Billy's soul. Make him a pirate, a grumpy IT guy, your team's standup bot.
- **Tools**: `BidiAgent` runs tools mid-conversation without blocking speech — Billy can check the weather while flapping. See the Strands docs.
- **The button** (yellow/green wires you kept): wire to GPIO 24 + ground, use it to start/stop sessions instead of always-listening.
- **Run on boot**: ask Claude to set up a `systemd` service so Billy wakes with the Pi.
- **Wake word**: Porcupine ("Hey Billy") runs locally on the Pi — see the billy-b-assistant project for the pattern.
- **Reassembly**: cut a notch in the backplate for cables, mount the mic near the original sensor hole, velcro the Pi to the plaque.

## 🔐 Appendix: credentials — the pragmatic way vs. the production way

This guide's main path puts a **tightly-scoped IAM access key** on the Pi (one action, one model, one region — §prerequisites). For a personal fish in a personal account, that's a reasonable trade: worst case if the SD card leaks is fish-chat on your bill, and the kill switch is one click (deactivate the key in IAM).

**The production-grade answer is AWS IoT Core's credential provider** — the pattern real device fleets use:

1. The device gets an **X.509 certificate** (its identity) instead of an access key.
2. At boot, it calls the IoT **credentials endpoint** over mutual TLS, presenting its cert.
3. IoT exchanges the cert for **temporary IAM credentials** (minutes-to-hours lifetime) by assuming a role — scoped, of course, to just Nova Sonic.
4. Those temporary credentials go into the boto3 session that Strands uses (`BidiNovaSonicModel(client_config={"boto_session": ...})`).

Why it's better: no long-lived secret exists on the device at all; each fish has its own revocable certificate; a stolen SD card goes stale within the credential lifetime.

**This kit includes the full IoT setup, mostly automated** — see the `iot-identity/` folder: a CloudFormation template (`billy-iot.yaml`) that creates the role/alias/policy in one deploy, a drop-in `fish_credentials.py` for the Pi, and `IOT_SETUP.md` walking through the ~10 minutes of commands. Recommended order: get your fish talking with the simple access key first (one debugging problem at a time), then do the IoT upgrade and revoke the key. As always: paste `IOT_SETUP.md` into Claude and do it together.

## 🧯 Troubleshooting quick reference

| Symptom | Cause | Fix |
|---|---|---|
| `IndentationError` line 1 | paste added leading spaces | `sed -i 's/^  //' file.py` |
| `SyntaxError` mid-file | paste dropped a comma / smart quotes | `cat -n file.py` around the line, compare with guide |
| `billy.local` won't resolve | WiFi typo, or work network blocking mDNS | router device list → use IP; re-flash if absent |
| `Connection reset` on first SSH | Pi still setting up | wait 2 min, retry |
| `no AWS credentials found` | env vars don't survive logout | `~/.aws/credentials` file (§1.6) |
| `Invalid sample rate` / `capture slave is not defined` | `~/.asoundrc` missing or wrong card names | `cat ~/.asoundrc`, `arecord -l`, fix names |
| `~/.asoundrc` keeps disappearing after reboot | You installed Desktop OS, not Lite — the Wayfire panel deletes it | `sudo systemctl set-default multi-user.target && sudo systemctl disable lightdm.service && sudo reboot` |
| ALSA warning wall at startup | normal | ignore unless there's a Traceback |
| `lgpio` build fails: `swig` not found | missing build tool | `sudo apt install -y swig`, re-pip |
| Billy interrupts himself | speaker echo trips barge-in | separate mic & speaker, lower volume |
| Mouth weak, tail strong | motor direction asymmetry vs. spring | swap the two mouth-channel plugs at the Pi (§3.6) |
| One motor dead | solder joint | tug test, reflow 3s |
| Motor runs at boot | wire on wrong Pi pin | unplug, recount from the USB-C end |
| Pi hot | no cooler | install the Active Cooler (§3.5) |

---

*Built with Strands Agents (experimental bidi API — pin your version!), Amazon Nova Sonic, a Raspberry Pi 5, and a fish. When in doubt, ask Claude — bring this guide and your error message.* 🐟

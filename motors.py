"""Motor test rig - run this BEFORE billy.py to verify wiring.

Press a key, watch the fish twitch:
    m  mouth opens for 1 second (full PWM power)
    h  head turns out for 1 second
    t  tail flaps for 0.3 seconds
    b  combo: head out + 4 mouth flaps + head returns
    s  scripted mouth rhythm
    q  quit

If a key moves the wrong thing, swap GPIO numbers below or swap the
matching DuPont plugs at the Pi header. See BUILD_GUIDE.md sections
3.4 and 3.6 for the full pin map and the weak-mouth fix.
"""

import time

from gpiozero import OutputDevice, PWMOutputDevice

mouth = PWMOutputDevice(17)
head = OutputDevice(22)
tail = OutputDevice(27)

print("m = mouth (1s)  h = head (1s)  t = tail  b = both  s = sing  q = quit")

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

    elif cmd == "s":
        for beat in [0.3, 0.15, 0.15, 0.4, 0.2, 0.3]:
            mouth.value = 1.0
            time.sleep(beat)
            mouth.value = 0
            time.sleep(0.12)

mouth.value = 0
head.off()
tail.off()

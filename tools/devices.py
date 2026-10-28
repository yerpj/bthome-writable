"""The devices on this bench, in one place.

Addresses, entity ids and the serial port drift as boards are reflashed and
Home Assistant renames things, and a table copied into three tools drifts three
times. Every measurement tool reads this one.

Nothing here needs Home Assistant or a radio, so a tool can import it to name
its `--device` choices without dragging `aiohttp` into a suite that has none.
"""

from __future__ import annotations

from typing import Any

DEVICES: dict[str, dict[str, Any]] = {
    "puck": {
        "address": "C8:80:32:AD:F7:B9",
        "label": "Puck.js switch (light), command to write acknowledged",
        "entity": "switch.bureau_mobilesensf7b9_light",
        "kind": "switch",
    },
    "lamp": {
        "address": "F5:A8:93:67:CB:25",
        "label": "nice!nano lamp (light + count), a device whose revision moves",
        "entity": "switch.espruino_cb25_light",
        "kind": "switch",
        # The third board, added 2026-10-23 for D-130: two writable entries
        # that are also readable, so it advertises a settings revision and
        # `bench.knob()` moves it on demand (espruino/bench/revision-lamp.js).
        # Reflashed 2026-10-24 with crypto (D-139); MODULES is
        # timer,Flash,Storage,heatshrink,crypto,neopixel, so it runs the sealed
        # bench sketch and §5.6's counter report is measured (§21, §22).
        "port": "COM6",
    },
    "nano": {
        "address": "CD:F5:77:3A:B2:16",
        "label": "nice!nano text (OLED), command to write acknowledged",
        "entity": "text.espruino_b216_text",
        "kind": "text",
        # Off the bench since 2026-10-27: it answers neither over USB nor over
        # the air, and its Home Assistant entities are unavailable. Kept here
        # because the §16 and §20 numbers were taken on it.
        #
        # Reachable over USB as well as over the air, which is how its
        # advertising interval is set without holding its single connection.
        "port": "COM15",
    },
    # The saturation arm, added 2026-10-24. Three devices and one three-slot
    # proxy cannot exhaust the host, so D-133's hold-off and D-134's priority
    # have only ever been shown by tests. These two are clones of `lamp`: two
    # writable entries that are also readable, so each one owes the receiver a
    # read and the read path carries three times the work it did.
    #
    # §17 is behind us, so they are in service: `revision-lamp.js` was pushed
    # into the RAM of both on 2026-10-28 and each was added to Home Assistant
    # with the sketch's own bindkey, which gives the saturation arm four
    # commandable devices in one island. The sketches still live in RAM, so a
    # power cut empties them and they have to be pushed again.
    "lamp2": {
        "address": "C2:38:F5:70:B6:BA",
        "label": "nice!nano lamp B (light + count), saturation arm only",
        "entity": "switch.espruino_b6ba_light",
        "kind": "switch",
        "port": "COM9",
    },
    "lamp3": {
        "address": "E0:A4:BA:16:54:89",
        "label": "nice!nano lamp C (light + count), saturation arm only",
        "entity": "switch.espruino_5489_light",
        "kind": "switch",
        "port": "COM11",
    },
    # The fourth device of the saturation arm, added 2026-10-28. It advertises
    # in clear, where the three nice!nanos are sealed, so it is also the one
    # whose packet a receiver can read without a key.
    "jolt": {
        "address": "FA:9C:55:A4:6A:0B",
        "label": "Jolt.js (light), in clear, fourth device of the saturation arm",
        "entity": "switch.jolt_js_6a0b_light",
        "kind": "switch",
        "port": "COM18",
    },
}

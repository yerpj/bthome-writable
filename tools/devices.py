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
    # **They stay out of the §17 campaign**, whose numbers are only comparable
    # with §16 and §20 on the bench as it was. Their sketches live in RAM, so
    # they are silent until uploaded, which is how they are kept out: upload
    # them after the campaign, not before.
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
}

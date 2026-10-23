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
        # Its firmware has no crypto -- MODULES is
        # timer,Flash,Storage,heatshrink,neopixel -- so it cannot run a sealed
        # sketch at all, which is why §5.6's counter report is still unmeasured.
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
}

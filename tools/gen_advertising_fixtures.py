"""Generate `spec/advertising-fixtures.json` — shared advertising test data.

The fixtures cover the declaration of PROTOCOL.md §2 (a list of writable object
types), its placement, multiple entries of one type, characteristic numbering,
settings revision, rotation, the capacity limit, and the writes and reads each
device accepts. Both test suites consume the file (CLAUDE.md rule 7).

Fixtures are self-describing: every object carries its value bytes explicitly,
so a consumer can verify a payload by concatenation without BTHome's
object-length table. That keeps the JS side honest -- a device knows its own
layout and never has to parse an arbitrary BTHome packet.

    python -m tools.gen_advertising_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUTPUT = Path(__file__).resolve().parent.parent / "spec" / "advertising-fixtures.json"

SPEC_VERSION = "2.0-draft.2"

DECLARATION_OBJECT_ID = 0xFF
DEVICE_INFO_PLAIN = 0x40  # BTHome v2, unencrypted
UUID_TEMPLATE = "2faa{:04x}-3b0b-4b1a-9e2a-b4c2952e62f2"  # PROTOCOL.md §4.1

# --- Advertising budget arithmetic (PROTOCOL.md §2.4) ------------------------
# The theoretical ceiling. Real devices take less -- Espruino's manufacturer
# data, a local name -- and the measured figures are in decisions.md D-030 and
# D-046. The fixtures only use this as an upper bound for sanity checks.
ADV_PAYLOAD_BYTES = 31
AD_FLAGS_BYTES = 3  # 02 01 06
AD_SERVICE_DATA_HEADER_BYTES = 4  # length + type 0x16 + 16-bit UUID 0xFCD2
SERVICE_DATA_BUDGET = ADV_PAYLOAD_BYTES - AD_FLAGS_BYTES - AD_SERVICE_DATA_HEADER_BYTES


def uuid(entry: int) -> str:
    return UUID_TEMPLATE.format(entry)


def obj(object_id: int, value: bytes, name: str, **extra: Any) -> dict[str, Any]:
    entry = {"object_id": f"{object_id:02x}", "value": value.hex(), "name": name}
    entry.update(extra)
    return entry


def encode(objects: list[dict[str, Any]]) -> bytes:
    return b"".join(
        bytes.fromhex(o["object_id"]) + bytes.fromhex(o["value"]) for o in objects
    )


def fixture(
    name: str,
    description: str,
    objects: list[dict[str, Any]],
    *,
    entries: list[int] | None = None,
    declaration_index: int | None = None,
    valid: bool = True,
    violates: str | None = None,
    expected_sensors: dict[str, Any] | None = None,
    offered_entries: list[int] | None = None,
    writes: list[dict[str, Any]] | None = None,
    reads: list[dict[str, Any]] | None = None,
    device_info: int = DEVICE_INFO_PLAIN,
) -> dict[str, Any]:
    """Assemble one fixture.

    `entries` are the declaration's object IDs, in order; None means no
    declaration. `declaration_index` places the declaration somewhere other than
    last, for the negative placement fixture. `offered_entries` lists the entry
    numbers a receiver should offer, when that differs from all of them.
    """
    body = [dict(o) for o in objects]
    declaration = None
    if entries is not None:
        declaration = obj(DECLARATION_OBJECT_ID, bytes(entries), "declaration")
        if declaration_index is None:
            body.append(declaration)
        else:
            body.insert(declaration_index, declaration)

    service_data = bytes([device_info]) + encode(body)
    result: dict[str, Any] = {
        "name": name,
        "description": description,
        "valid": valid,
        "device_info_byte": f"{device_info:02x}",
        "service_data": service_data.hex(),
        "service_data_length": len(service_data),
        "objects": body,
    }
    if entries is not None:
        numbered = list(range(1, len(entries) + 1))
        result["declaration"] = {
            "entries": [f"{e:02x}" for e in entries],
            "characteristics": [
                {"entry": k, "object_id": f"{e:02x}", "uuid": uuid(k)}
                for k, e in zip(numbered, entries, strict=True)
            ],
            "offered_entries": offered_entries
            if offered_entries is not None
            else numbered,
            "is_last_element": body[-1] is declaration,
        }
    if violates is not None:
        result["violates"] = violates
    if expected_sensors is not None:
        result["expected_sensors"] = expected_sensors
    if writes is not None:
        result["writes"] = writes
    if reads is not None:
        result["reads"] = reads
    return result


def access(
    name: str, description: str, entry: int, value: dict[str, Any]
) -> dict[str, Any]:
    """One write or read: a single BTHome object on entry `entry` (§4.2, §4.3)."""
    return {
        "name": name,
        "description": description,
        "entry": entry,
        "uuid": uuid(entry),
        "object": value,
        "payload": encode([value]).hex(),
    }


PACKET_ID = lambda n: obj(0x00, bytes([n]), "packet_id")  # noqa: E731
BATTERY = lambda pct: obj(0x01, bytes([pct]), "battery")  # noqa: E731
LIGHT = lambda on: obj(0x1E, bytes([1 if on else 0]), "light")  # noqa: E731
POWER = lambda on: obj(0x10, bytes([1 if on else 0]), "power")  # noqa: E731
TEMPERATURE = lambda c: obj(  # noqa: E731
    0x02, round(c * 100).to_bytes(2, "little", signed=True), "temperature"
)
# 0x57: temperature, sint8, whole degrees -- the shape of a thermostat target.
TEMPERATURE_SINT8 = lambda c: obj(  # noqa: E731
    0x57, int(c).to_bytes(1, "little", signed=True), "temperature"
)
SETTINGS_REVISION = lambda n: obj(0x65, bytes([n]), "settings_revision")  # noqa: E731
# BTHome moisture: uint16, factor 0.01 -- the shape of a level or a setpoint.
MOISTURE = lambda pct: obj(  # noqa: E731
    0x14, round(pct * 100).to_bytes(2, "little"), "moisture"
)
BUTTON = lambda event: obj(0x3A, bytes([event]), "button")  # noqa: E731
TEXT = lambda s: obj(0x53, bytes([len(s)]) + s, "text")  # noqa: E731

LIGHT_ID, POWER_ID, TEMP8_ID, MOISTURE_ID, BUTTON_ID, TEXT_ID = (
    0x1E,
    0x10,
    0x57,
    0x14,
    0x3A,
    0x53,
)
UNKNOWN_ID = 0x99  # unassigned in BTHome: a type a receiver does not know yet


def build_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []

    # --- Valid ----------------------------------------------------------
    fixtures.append(
        fixture(
            "single-light",
            "PROTOCOL.md §8.1: packet id, battery, one writable light. The "
            "light's state is not advertised (§2.3).",
            [PACKET_ID(9), BATTERY(97)],
            entries=[LIGHT_ID],
            expected_sensors={"packet_id": 9, "battery": 97},
            writes=[
                access("light-on", "Switch the light on.", 1, LIGHT(True)),
                access("light-off", "And off.", 1, LIGHT(False)),
            ],
        )
    )

    fixtures.append(
        fixture(
            "thermostat",
            "PROTOCOL.md §8.2: a measured temperature (a sensor), settings "
            "revision, and two entries -- power and a target temperature. The "
            "measured 0x02 and the writable 0x57 never collide, because the "
            "target is not in the packet.",
            [PACKET_ID(9), TEMPERATURE(25.00), SETTINGS_REVISION(3)],
            entries=[POWER_ID, TEMP8_ID],
            expected_sensors={
                "packet_id": 9,
                "temperature": 25.0,
                "settings_revision": 3,
            },
            writes=[
                access("target-22", "Target 22 °C.", 2, TEMPERATURE_SINT8(22)),
                access("heating-on", "Power on.", 1, POWER(True)),
            ],
            reads=[
                access(
                    "read-power", "After a revision change: heating on.", 1, POWER(True)
                ),
                access(
                    "read-target",
                    "After a revision change: target 20 °C.",
                    2,
                    TEMPERATURE_SINT8(20),
                ),
            ],
        )
    )

    fixtures.append(
        fixture(
            "two-lights-and-display",
            "PROTOCOL.md §8.3: two entries of one type and a text entry. "
            "Instances are told apart by entry number, which is also their "
            "characteristic number.",
            [PACKET_ID(9)],
            entries=[LIGHT_ID, LIGHT_ID, TEXT_ID],
            expected_sensors={"packet_id": 9},
            writes=[
                access(
                    "second-light-off",
                    "Touches entry 2 and nothing else.",
                    2,
                    LIGHT(False),
                ),
                access(
                    "display-hello",
                    "Text keeps BTHome's length byte.",
                    3,
                    TEXT(b"Hello"),
                ),
            ],
        )
    )

    fixtures.append(
        fixture(
            "momentary-action",
            "PROTOCOL.md §8.4: a writable button. A write triggers only its own "
            "entry, so events are safe to write in version 2.",
            [PACKET_ID(9)],
            entries=[BUTTON_ID],
            expected_sensors={"packet_id": 9},
            writes=[
                access(
                    "press",
                    "0x01 is press in BTHome's button vocabulary.",
                    1,
                    BUTTON(0x01),
                ),
                access("long-press", "0x04 is long_press.", 1, BUTTON(0x04)),
            ],
        )
    )

    fixtures.append(
        fixture(
            "writable-level",
            "A writable numeric entry: the shape of a dimmer level or a setpoint. "
            "Range and step come from the object's width and factor.",
            [PACKET_ID(3), BATTERY(88)],
            entries=[MOISTURE_ID],
            expected_sensors={"packet_id": 3, "battery": 88},
            writes=[access("level-60", "6000 = 0x1770 is 60.00 %.", 1, MOISTURE(60.0))],
        )
    )

    twelve = [LIGHT_ID] * 12
    fixtures.append(
        fixture(
            "twelve-lights",
            "More entries than version 1's bitmask allowed, and characteristic "
            "numbers past 9: entry 10 is 2faa000a, written in hexadecimal.",
            [PACKET_ID(1)],
            entries=twelve,
            expected_sensors={"packet_id": 1},
            writes=[
                access("tenth-on", "Characteristic 2faa000a.", 10, LIGHT(True)),
                access("twelfth-on", "Characteristic 2faa000c.", 12, LIGHT(True)),
            ],
        )
    )

    fixtures.append(
        fixture(
            "unknown-entry-type",
            "Entry 2 is an object ID the receiver does not know. It is not "
            "offered, but it is counted: the light after it stays on "
            "characteristic 3 (§2.1).",
            [PACKET_ID(5)],
            entries=[LIGHT_ID, UNKNOWN_ID, LIGHT_ID],
            offered_entries=[1, 3],
            expected_sensors={"packet_id": 5},
            writes=[
                access("third-entry-on", "Characteristic 3, not 2.", 3, LIGHT(True))
            ],
        )
    )

    fixtures.append(
        fixture(
            "rotation-declaration-packet",
            "A rotating device, packet 1 of 2, carrying the declaration.",
            [PACKET_ID(1), BATTERY(74)],
            entries=[LIGHT_ID],
            expected_sensors={"packet_id": 1, "battery": 74},
            writes=[access("light-on", "Turn the relay on.", 1, LIGHT(True))],
        )
    )

    fixtures.append(
        fixture(
            "rotation-sensor-packet",
            "The same device, packet 2 of 2: sensors only. A receiver that has "
            "seen the declaration MUST NOT drop the device's entries because "
            "this packet lacks one (§2.2).",
            [
                PACKET_ID(2),
                TEMPERATURE(22.10),
                obj(0x03, (5500).to_bytes(2, "little"), "humidity"),
            ],
            expected_sensors={"packet_id": 2, "temperature": 22.10, "humidity": 55.00},
        )
    )

    fixtures.append(
        fixture(
            "plain-bthome-no-declaration",
            "An ordinary BTHome device. A receiver MUST NOT offer it as writable.",
            [BATTERY(50), TEMPERATURE(20.00)],
            expected_sensors={"battery": 50, "temperature": 20.00},
        )
    )

    fixtures.append(
        fixture(
            "empty-declaration",
            "A declaration with no entries: legal, means nothing writable, and a "
            "device SHOULD omit it instead (§2.1).",
            [PACKET_ID(1), BATTERY(60)],
            entries=[],
            expected_sensors={"packet_id": 1, "battery": 60},
            writes=[],
        )
    )

    # --- Invalid --------------------------------------------------------
    fixtures.append(
        fixture(
            "declaration-not-last",
            "The declaration placed before a sensor. A receiver cannot detect "
            "it: the entries run to the end of the data, so the battery bytes "
            "would read as two more entries, and existing BTHome receivers drop "
            "the battery. A device MUST make this impossible (§2.2).",
            [PACKET_ID(1), BATTERY(97)],
            entries=[LIGHT_ID],
            declaration_index=1,
            valid=False,
            violates="declaration_not_last",
        )
    )

    fixtures.append(
        fixture(
            "forbidden-entry",
            "Entry 1 lists the packet id, which §2.1 forbids. A receiver MUST NOT "
            "offer it, and MUST still count it.",
            [PACKET_ID(1)],
            entries=[0x00, LIGHT_ID],
            offered_entries=[2],
            valid=False,
            violates="forbidden_entry",
            expected_sensors={"packet_id": 1},
        )
    )

    fixtures.append(
        fixture(
            "capacity-overflow",
            "Over the theoretical advertising budget of §2.4. A device MUST "
            "refuse this configuration at setup rather than truncate.",
            [PACKET_ID(1), BATTERY(97)],
            entries=[LIGHT_ID] * 25,
            valid=False,
            violates="capacity_exceeded",
        )
    )

    return fixtures


def main() -> None:
    fixtures = build_fixtures()

    # A fixture that silently stopped testing what it claims is worse than none.
    for entry in fixtures:
        over_budget = entry["service_data_length"] > SERVICE_DATA_BUDGET
        if entry.get("violates") == "capacity_exceeded":
            assert over_budget, f"{entry['name']} no longer exceeds the budget"
        elif entry["valid"]:
            assert not over_budget, (
                f"{entry['name']} is marked valid but needs "
                f"{entry['service_data_length']} bytes of the "
                f"{SERVICE_DATA_BUDGET}-byte service-data budget"
            )

    document = {
        "spec_version": SPEC_VERSION,
        "generated_by": "tools/gen_advertising_fixtures.py",
        "description": (
            "Advertising fixtures for bthome-writable, consumed by both test "
            "suites. Service data is the full BTHome v2 payload including the "
            "device-information byte; writes and reads follow PROTOCOL.md §4."
        ),
        "budget": {
            "advertising_payload_bytes": ADV_PAYLOAD_BYTES,
            "ad_flags_bytes": AD_FLAGS_BYTES,
            "ad_service_data_header_bytes": AD_SERVICE_DATA_HEADER_BYTES,
            "service_data_budget": SERVICE_DATA_BUDGET,
            "note": (
                "A theoretical ceiling. Real devices spend more of the 31 bytes: "
                "Espruino always advertises its manufacturer ID, and a local name "
                "costs 2 + its length. Measured object budgets were 7 to 22 bytes "
                "(PROTOCOL.md §2.4, decisions.md D-030, D-046)."
            ),
        },
        "fixtures": fixtures,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(document, indent=2) + "\n")

    valid = sum(1 for f in fixtures if f["valid"])
    print(
        f"wrote {OUTPUT} — {len(fixtures)} fixtures "
        f"({valid} valid, {len(fixtures) - valid} invalid)"
    )


if __name__ == "__main__":
    main()

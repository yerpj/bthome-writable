"""Generate `spec/advertising-fixtures.json` — shared advertising test data.

The fixtures cover declaration placement, multi-instance objects, the write-only
pattern, rotation under the same-packet rule, the capacity limit, and the
matching write payloads. Both test suites consume the file (CLAUDE.md rule 6).

Fixtures are self-describing: every object carries its value bytes explicitly,
so a consumer can verify a payload by concatenation without needing BTHome's
object-length table. That keeps the JS side honest — a device knows its own
layout and never has to parse an arbitrary BTHome packet.

    python -m tools.gen_advertising_fixtures
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUTPUT = Path(__file__).resolve().parent.parent / "spec" / "advertising-fixtures.json"

SPEC_VERSION = "1.0-draft.1"

DECLARATION_OBJECT_ID = 0xFF
DEVICE_INFO_PLAIN = 0x40  # BTHome v2, unencrypted
MAX_WRITABLE = 8

# --- Advertising budget arithmetic (PROTOCOL.md §2.3) ------------------------
# A legacy BLE advertising payload is 31 bytes of AD structures. A BTHome
# device spends them like this:
ADV_PAYLOAD_BYTES = 31
AD_FLAGS_BYTES = 3  # 02 01 06 — connectable undirected advertising
AD_SERVICE_DATA_HEADER_BYTES = 4  # length + type 0x16 + 16-bit UUID 0xFCD2
# ... which leaves this for the BTHome service data itself:
SERVICE_DATA_BUDGET = ADV_PAYLOAD_BYTES - AD_FLAGS_BYTES - AD_SERVICE_DATA_HEADER_BYTES
# ... of which one byte is the device-information byte:
OBJECT_BUDGET = SERVICE_DATA_BUDGET - 1


def obj(object_id: int, value: bytes, name: str, **extra: Any) -> dict[str, Any]:
    entry = {
        "object_id": f"{object_id:02x}",
        "value": value.hex(),
        "name": name,
    }
    entry.update(extra)
    return entry


def encode(objects: list[dict[str, Any]]) -> bytes:
    return b"".join(
        bytes.fromhex(o["object_id"]) + bytes.fromhex(o["value"]) for o in objects
    )


def bitmask(positions: list[int]) -> int:
    mask = 0
    for position in positions:
        mask |= 1 << position
    return mask


def fixture(
    name: str,
    description: str,
    objects: list[dict[str, Any]],
    *,
    writable_positions: list[int] | None = None,
    declaration_position: int | None = None,
    valid: bool = True,
    violates: str | None = None,
    expected_sensors: dict[str, Any] | None = None,
    writes: list[dict[str, Any]] | None = None,
    declaration_bitmask: int | None = None,
    device_info: int = DEVICE_INFO_PLAIN,
) -> dict[str, Any]:
    """Assemble one fixture.

    `declaration_position` places the declaration somewhere other than last, for
    the negative placement fixture. `declaration_bitmask` overrides the mask
    computed from `writable_positions`, for the malformed-mask fixtures.
    """
    positions = writable_positions or []
    mask = (
        declaration_bitmask if declaration_bitmask is not None else bitmask(positions)
    )

    # Copy: the object constants below are shared between fixtures, and this
    # function stamps a `position` into each one.
    body = [dict(o) for o in objects]
    declaration = obj(DECLARATION_OBJECT_ID, bytes([mask]), "declaration")
    if writable_positions is not None or declaration_bitmask is not None:
        if declaration_position is None:
            body.append(declaration)
        else:
            body.insert(declaration_position, declaration)

    # Positions are assigned over the objects as they appear on the wire.
    for index, entry in enumerate(body):
        entry["position"] = index

    service_data = bytes([device_info]) + encode(body)

    entry: dict[str, Any] = {
        "name": name,
        "description": description,
        "valid": valid,
        "device_info_byte": f"{device_info:02x}",
        "service_data": service_data.hex(),
        "service_data_length": len(service_data),
        "objects": body,
    }
    if writable_positions is not None or declaration_bitmask is not None:
        entry["declaration"] = {
            "bitmask": mask,
            "bitmask_hex": f"{mask:02x}",
            "writable_positions": positions,
            "is_last_element": body[-1] is declaration,
        }
    if violates is not None:
        entry["violates"] = violates
    if expected_sensors is not None:
        entry["expected_sensors"] = expected_sensors
    if writes is not None:
        entry["writes"] = writes
    return entry


def write(name: str, description: str, objects: list[dict[str, Any]]) -> dict[str, Any]:
    """A write payload: every writable object, in packet order (§4.2)."""
    return {
        "name": name,
        "description": description,
        "objects": objects,
        "payload": encode(objects).hex(),
    }


BATTERY = lambda pct: obj(0x01, bytes([pct]), "battery")  # noqa: E731
LIGHT = lambda on: obj(0x1E, bytes([1 if on else 0]), "light")  # noqa: E731
PACKET_ID = lambda n: obj(0x00, bytes([n]), "packet_id")  # noqa: E731
TEXT_EMPTY = obj(0x53, bytes([0]), "text", write_only=True)
TEXT_NOOP = obj(0x53, bytes([0]), "text", note="length 0 = no-op (§4.3)")


def build_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []

    # --- Valid ----------------------------------------------------------
    fixtures.append(
        fixture(
            "single-light",
            "PROTOCOL.md §8.1: battery plus one writable light.",
            [BATTERY(97), LIGHT(True)],
            writable_positions=[1],
            expected_sensors={"battery": 97, "light": True},
            writes=[
                write(
                    "light-off",
                    "The only writable object, set to off.",
                    [LIGHT(False)],
                ),
                write("light-on", "And back on.", [LIGHT(True)]),
            ],
        )
    )

    fixtures.append(
        fixture(
            "multi-instance-and-display",
            "PROTOCOL.md §8.2: three light instances and a write-only display. "
            "Positions disambiguate the instances; no per-instance ID is needed.",
            [BATTERY(97), LIGHT(True), LIGHT(False), LIGHT(True), TEXT_EMPTY],
            writable_positions=[1, 2, 3, 4],
            expected_sensors={
                "battery": 97,
                "light_1": True,
                "light_2": False,
                "light_3": True,
            },
            writes=[
                write(
                    "second-light-off",
                    "Change one instance. The other two are resent from the last "
                    "advertisement, and the display carries the no-op.",
                    [LIGHT(True), LIGHT(False), LIGHT(True), TEXT_NOOP],
                ),
                write(
                    "display-hello",
                    "Write text without touching any light.",
                    [
                        LIGHT(True),
                        LIGHT(False),
                        LIGHT(True),
                        obj(0x53, bytes([5]) + b"hello", "text"),
                    ],
                ),
            ],
        )
    )

    # The two fixtures a real Espruino device produces: same devices as above,
    # but with BTHome's packet-id object at position 0, which shifts every
    # bitmask bit by one (§2.2, §8.3). The reference module must reproduce these
    # byte for byte.
    fixtures.append(
        fixture(
            "espruino-single-light",
            "PROTOCOL.md §8.3: §8.1's device as the Espruino module emits it, "
            "with the packet-id object at position 0.",
            [PACKET_ID(9), BATTERY(97), LIGHT(True)],
            writable_positions=[2],
            expected_sensors={"packet_id": 9, "battery": 97, "light": True},
            writes=[
                write(
                    "light-off",
                    "Identical to §8.1's write: only writable objects travel.",
                    [LIGHT(False)],
                )
            ],
        )
    )

    fixtures.append(
        fixture(
            "espruino-multi-instance",
            "The multi-instance device as the Espruino module emits it. Three "
            "light instances keep their declared order through the packet's "
            "ascending-object-id sort, which must therefore be stable.",
            [PACKET_ID(10), BATTERY(97), LIGHT(True), LIGHT(False), LIGHT(True)],
            writable_positions=[2, 3, 4],
            expected_sensors={
                "packet_id": 10,
                "battery": 97,
                "light_1": True,
                "light_2": False,
                "light_3": True,
            },
            writes=[
                write(
                    "second-light-off",
                    "Positions address the instances; no per-instance ID exists.",
                    [LIGHT(True), LIGHT(False), LIGHT(True)],
                )
            ],
        )
    )

    fixtures.append(
        fixture(
            "write-only-display",
            "A device whose only writable object is a write-only text: it "
            "advertises the placeholder and never the written value (§3).",
            [BATTERY(88), TEXT_EMPTY],
            writable_positions=[1],
            expected_sensors={"battery": 88},
            writes=[
                write(
                    "display-hello",
                    "Fire-and-forget: the advertising will not change.",
                    [obj(0x53, bytes([5]) + b"hello", "text")],
                ),
                write(
                    "display-noop",
                    "Length 0: do not modify the display.",
                    [TEXT_NOOP],
                ),
            ],
        )
    )

    fixtures.append(
        fixture(
            "rotation-declaration-packet",
            "A rotating device, packet 1 of 2. The same-packet rule (§2.1) "
            "requires the declaration and every writable object to be here.",
            [BATTERY(74), LIGHT(False)],
            writable_positions=[1],
            expected_sensors={"battery": 74, "light": False},
            writes=[write("light-on", "Turn the relay on.", [LIGHT(True)])],
        )
    )

    fixtures.append(
        fixture(
            "rotation-sensor-packet",
            "The same device, packet 2 of 2: read-only sensors that rotate "
            "freely. No declaration, and a receiver must not infer one.",
            [
                obj(0x02, (2210).to_bytes(2, "little"), "temperature"),
                obj(0x03, (5500).to_bytes(2, "little"), "humidity"),
            ],
            expected_sensors={"temperature": 22.10, "humidity": 55.00},
        )
    )

    fixtures.append(
        fixture(
            "plain-bthome-no-declaration",
            "An ordinary BTHome device. The integration MUST abort discovery "
            "with not_supported rather than offer it (§5 of the design).",
            [BATTERY(50), obj(0x02, (2000).to_bytes(2, "little"), "temperature")],
            expected_sensors={"battery": 50, "temperature": 20.00},
        )
    )

    fixtures.append(
        fixture(
            "empty-bitmask",
            "A declaration marking nothing writable. Legal, but a device SHOULD "
            "omit the declaration instead (§2.2).",
            [BATTERY(60)],
            writable_positions=[],
            expected_sensors={"battery": 60},
            writes=[],
        )
    )

    eight_lights = [LIGHT(bool(i % 2)) for i in range(MAX_WRITABLE)]
    fixtures.append(
        fixture(
            "eight-writables-maximum",
            "The most a one-byte bitmask can address (§2.4). Bit 7 is set, "
            "which catches an implementation using a signed byte.",
            eight_lights,
            writable_positions=list(range(MAX_WRITABLE)),
            expected_sensors={
                f"light_{i + 1}": bool(i % 2) for i in range(MAX_WRITABLE)
            },
            writes=[
                write(
                    "all-off",
                    "Every writable object at once.",
                    [LIGHT(False) for _ in range(MAX_WRITABLE)],
                )
            ],
        )
    )

    # --- Invalid --------------------------------------------------------
    fixtures.append(
        fixture(
            "declaration-not-last",
            "The declaration placed first. Every object after it is silently "
            "dropped by existing BTHome receivers (D-005), so §2.2 forbids it.",
            [BATTERY(97), LIGHT(True)],
            writable_positions=[2],
            declaration_position=0,
            valid=False,
            violates="declaration_not_last",
            expected_sensors={},
        )
    )

    fixtures.append(
        fixture(
            "bitmask-beyond-object-count",
            "Bit 5 set, but the packet holds three objects. A receiver MUST "
            "ignore bits that address nothing rather than invent an entity.",
            [BATTERY(97), LIGHT(True)],
            declaration_bitmask=0b00100010,
            valid=False,
            violates="bitmask_addresses_missing_object",
            expected_sensors={"battery": 97, "light": True},
        )
    )

    fixtures.append(
        fixture(
            "declaration-marks-itself",
            "Bit 2 addresses the declaration object itself. Nonsensical; a "
            "receiver MUST ignore it.",
            [BATTERY(97), LIGHT(True)],
            declaration_bitmask=0b00000110,
            valid=False,
            violates="bitmask_addresses_declaration",
            expected_sensors={"battery": 97, "light": True},
        )
    )

    # Deliberately over the budget: 11 lights plus battery plus declaration.
    fixtures.append(
        fixture(
            "capacity-overflow",
            "Over the advertising budget of §2.3. A device MUST refuse this "
            "configuration at setup rather than truncate.",
            [BATTERY(97)] + [LIGHT(True) for _ in range(11)],
            writable_positions=[1, 2, 3, 4, 5, 6, 7],
            valid=False,
            violates="capacity_exceeded",
        )
    )

    return fixtures


def main() -> None:
    fixtures = build_fixtures()

    # Sanity: the capacity fixture must actually exceed the budget, and every
    # fixture claiming validity must actually fit. A fixture that silently
    # stopped testing what it claims is worse than no fixture.
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
            "device-information byte; write payloads follow PROTOCOL.md §4.2."
        ),
        "budget": {
            "advertising_payload_bytes": ADV_PAYLOAD_BYTES,
            "ad_flags_bytes": AD_FLAGS_BYTES,
            "ad_service_data_header_bytes": AD_SERVICE_DATA_HEADER_BYTES,
            "service_data_budget": SERVICE_DATA_BUDGET,
            "object_budget": OBJECT_BUDGET,
            "note": (
                "The 31 bytes of a legacy advertising payload are not all "
                "available to BTHome objects: the Flags AD structure and the "
                "Service Data header come out first, and the device-information "
                "byte after that. See PROTOCOL.md §2.3."
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
        f"({valid} valid, {len(fixtures) - valid} invalid); "
        f"service-data budget {SERVICE_DATA_BUDGET} bytes"
    )


if __name__ == "__main__":
    main()

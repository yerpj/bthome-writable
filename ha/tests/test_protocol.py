"""The protocol module, driven by the shared advertising fixtures (version 2).

No Home Assistant involved: this is the wire format, checked against the same
file the Espruino suite consumes (CLAUDE.md rule 7).
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.bthome_writable.protocol import (
    ProtocolError,
    WritableEntry,
    characteristic_uuid,
    decode_object,
    encode_object,
    parse_declaration,
    split_objects,
)

from .conftest import FIXTURES


def objects_of(fixture: dict[str, Any]) -> bytes:
    """A fixture's service data without the device-information byte."""
    return bytes.fromhex(fixture["service_data"])[1:]


VALID_WITH_DECLARATION = [
    name
    for name, fixture in FIXTURES.items()
    if fixture["valid"] and "declaration" in fixture
]


@pytest.mark.parametrize("name", VALID_WITH_DECLARATION)
def test_declaration_matches_the_fixture(name: str) -> None:
    """Entries, their characteristics and what is offered, as the fixture says."""
    fixture = FIXTURES[name]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None

    expected = fixture["declaration"]
    assert [f"{e.object_id:02x}" for e in declaration.entries] == expected["entries"]
    assert [e.uuid for e in declaration.entries] == [
        c["uuid"] for c in expected["characteristics"]
    ]
    assert [e.entry for e in declaration.offered] == expected["offered_entries"]


@pytest.mark.parametrize("name", VALID_WITH_DECLARATION)
def test_settings_revision_is_read_when_advertised(name: str) -> None:
    fixture = FIXTURES[name]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None
    advertised = [o for o in fixture["objects"] if o["object_id"] == "65"]
    if advertised:
        assert declaration.settings_revision == int(advertised[0]["value"], 16)
    else:
        assert declaration.settings_revision is None


def test_an_ordinary_bthome_device_has_no_declaration() -> None:
    fixture = FIXTURES["plain-bthome-no-declaration"]
    assert parse_declaration(objects_of(fixture)) is None


def test_a_sensor_packet_of_a_rotating_device_has_no_declaration() -> None:
    fixture = FIXTURES["rotation-sensor-packet"]
    assert parse_declaration(objects_of(fixture)) is None


def test_an_empty_declaration_offers_nothing() -> None:
    declaration = parse_declaration(objects_of(FIXTURES["empty-declaration"]))
    assert declaration is not None
    assert declaration.entries == ()


def test_unknown_and_forbidden_entries_are_counted_but_not_offered() -> None:
    """§2.1: a skipped entry must not renumber the characteristics after it."""
    declaration = parse_declaration(objects_of(FIXTURES["unknown-entry-type"]))
    assert declaration is not None
    assert [e.entry for e in declaration.offered] == [1, 3]
    assert declaration.entries[2].uuid == characteristic_uuid(3)

    forbidden = parse_declaration(objects_of(FIXTURES["forbidden-entry"]))
    assert forbidden is not None
    assert [e.entry for e in forbidden.offered] == [2]


def test_the_settings_revision_is_not_declarable_as_writable() -> None:
    """D-072. `0x65` is how a device says its own state moved (§3.2), so a
    receiver able to write it would be driving the signal that exists to inform
    it. Forbidden like the packet id and the declaration itself -- and counted
    like them, so the entries after keep their characteristic numbers."""
    declaration = parse_declaration(bytes.fromhex("0009" + "ff02651e"))
    assert declaration is not None
    assert [e.object_id for e in declaration.entries] == [0x65, 0x1E]
    assert [e.entry for e in declaration.offered] == [2]


def test_a_value_byte_of_0xff_is_not_mistaken_for_the_declaration() -> None:
    """The payload is walked, not scanned: a battery at 255 is not a declaration."""
    payload = bytes.fromhex("0009" + "01ff" + "ff011e")
    declaration = parse_declaration(payload)
    assert declaration is not None
    assert [e.object_id for e in declaration.entries] == [0x1E]


def test_a_command_object_before_the_declaration_is_walked_correctly() -> None:
    """0x3B is variable length: argument length, opcode, arguments."""
    payload = bytes.fromhex("0001" + "3b010305" + "ff011e")
    objects, offset = split_objects(payload)
    assert objects[1] == (0x3B, bytes.fromhex("010305"))
    assert offset == len(payload) - 3  # 0xFF, the count, one entry


def test_characteristic_numbers_are_hexadecimal() -> None:
    assert characteristic_uuid(1) == "2faa0001-3b0b-4b1a-9e2a-b4c2952e62f2"
    assert characteristic_uuid(10) == "2faa000a-3b0b-4b1a-9e2a-b4c2952e62f2"


@pytest.mark.parametrize(
    "fixture_name",
    [n for n, f in FIXTURES.items() if f.get("writes") or f.get("reads")],
)
def test_writes_and_reads_round_trip_the_fixtures(fixture_name: str) -> None:
    """§4.2, §4.3: one object, ID then value, in BTHome's own encoding."""
    fixture = FIXTURES[fixture_name]
    for access in fixture.get("writes", []) + fixture.get("reads", []):
        entry = WritableEntry(
            entry=access["entry"],
            object_id=int(access["object"]["object_id"], 16),
        )
        value = bytes.fromhex(access["object"]["value"])
        assert encode_object(entry, value).hex() == access["payload"]
        assert decode_object(entry, bytes.fromhex(access["payload"])) == value


def test_a_read_of_the_wrong_type_is_refused() -> None:
    """A characteristic that no longer means what the receiver thinks must not
    be shown as state."""
    light = WritableEntry(entry=1, object_id=0x1E)
    with pytest.raises(ProtocolError):
        decode_object(light, bytes.fromhex("5301" + "41"))


@pytest.mark.parametrize("payload", ["", "1e", "1e0100", "5305414243"])
def test_a_read_of_the_wrong_length_is_refused(payload: str) -> None:
    entry = WritableEntry(entry=1, object_id=0x53 if payload.startswith("53") else 0x1E)
    with pytest.raises(ProtocolError):
        decode_object(entry, bytes.fromhex(payload))


def test_a_declaration_behind_the_settings_revision_survives_the_walk() -> None:
    """Why `manifest.json` cannot ask for an older `bthome-ble` (D-083).

    The walk stops at the first object ID the library does not know (D-005),
    and `0x65` sits *before* the declaration in a device that reports its own
    state. A library without `0x65` therefore stops there and the declaration
    behind it disappears: the device is discovered and offers nothing. The
    floor reads like caution; it is not. `tools/tests/test_library_floor.py`
    checks the table, this checks the consequence.
    """
    from custom_components.bthome_writable.protocol import parse_declaration

    # A thermostat: temperature, settings revision 3, then the declaration.
    declaration = parse_declaration(bytes.fromhex("02c4096503ff021057"))

    assert declaration is not None, "the declaration must survive 0x65"
    assert declaration.layout == (0x10, 0x57)
    assert declaration.settings_revision == 3

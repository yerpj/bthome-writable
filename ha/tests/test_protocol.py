"""The protocol module, driven by the shared advertising fixtures.

No Home Assistant involved: this is the wire format, and it is checked against
the same file the Espruino suite consumes (CLAUDE.md rule 6).
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.bthome_writable.protocol import (
    ProtocolError,
    compose_write,
    no_op_value,
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
    """Every declared bitmask and position round-trips through the parser."""
    fixture = FIXTURES[name]
    declaration = parse_declaration(objects_of(fixture))

    assert declaration is not None
    assert declaration.bitmask == fixture["declaration"]["bitmask"]
    assert list(declaration.positions) == fixture["declaration"]["writable_positions"]


@pytest.mark.parametrize("name", VALID_WITH_DECLARATION)
def test_writable_objects_carry_the_advertised_value(name: str) -> None:
    """A parsed object holds the bytes the packet advertised at that position."""
    fixture = FIXTURES[name]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None

    for obj in declaration.objects:
        advertised = fixture["objects"][obj.position]
        assert obj.object_id == int(advertised["object_id"], 16)
        assert obj.value.hex() == advertised["value"]


def test_a_plain_bthome_device_yields_no_declaration() -> None:
    """What the config flow's not_supported abort keys on."""
    fixture = FIXTURES["plain-bthome-no-declaration"]
    assert parse_declaration(objects_of(fixture)) is None


def test_rotation_sensor_packet_yields_no_declaration() -> None:
    """§2.1: only the declaration packet carries one, and a receiver must not
    infer writability from a device's other rotation slots."""
    assert parse_declaration(objects_of(FIXTURES["rotation-sensor-packet"])) is None


def test_declaration_object_id_is_not_confused_with_a_value_byte() -> None:
    """A battery reading of 255 must not be mistaken for the declaration.

    A payload scan for 0xFF would find the battery value first. The parser walks
    objects instead, which is the point of this test.
    """
    payload = bytes.fromhex("01ff1e01ff04")  # battery=255, light=on, declaration
    declaration = parse_declaration(payload)

    assert declaration is not None
    assert declaration.bitmask == 0x04
    assert [obj.position for obj in declaration.objects] == []
    # Bit 2 addresses nothing here (only two objects), so it is ignored (§2.2).


def test_bitmask_bit_addressing_a_missing_object_is_ignored() -> None:
    fixture = FIXTURES["bitmask-beyond-object-count"]
    declaration = parse_declaration(objects_of(fixture))

    assert declaration is not None
    assert declaration.bitmask == 0b00100010
    # Bit 1 is the light; bit 5 addresses nothing and must not become an entity.
    assert [obj.position for obj in declaration.objects] == [1]


def test_declaration_marking_itself_is_ignored() -> None:
    fixture = FIXTURES["declaration-marks-itself"]
    declaration = parse_declaration(objects_of(fixture))

    assert declaration is not None
    assert [obj.position for obj in declaration.objects] == [1]


def test_declaration_not_last_is_rejected() -> None:
    """§2.2 is a MUST, so a payload violating it is an error, not a shrug."""
    fixture = FIXTURES["declaration-not-last"]
    with pytest.raises(ProtocolError, match="not the last element"):
        parse_declaration(objects_of(fixture))


def test_declaration_without_a_bitmask_byte_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="no bitmask"):
        parse_declaration(bytes.fromhex("0161ff"))


def test_truncated_object_is_rejected_rather_than_guessed() -> None:
    """A half-read packet must not produce a write composed from garbage."""
    with pytest.raises(ProtocolError, match="truncated"):
        split_objects(bytes.fromhex("0161 02ff".replace(" ", "")))


@pytest.mark.parametrize("name", VALID_WITH_DECLARATION)
def test_compose_write_matches_the_fixture_payloads(name: str) -> None:
    """§4.2: the composed payload is byte-identical to the fixture's."""
    fixture = FIXTURES[name]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None

    for entry in fixture.get("writes", []):
        # Reconstruct the change set the fixture's write represents.
        changes: dict[int, bytes] = {}
        for obj, written in zip(declaration.objects, entry["objects"], strict=True):
            assert written["object_id"] == f"{obj.object_id:02x}"
            changes[obj.position] = bytes.fromhex(written["value"])

        assert compose_write(declaration, changes).hex() == entry["payload"]


def test_unchanged_objects_are_resent_at_their_advertised_value() -> None:
    """Changing one instance must not disturb the others (§4.3)."""
    fixture = FIXTURES["espruino-multi-instance"]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None

    payload = compose_write(declaration, {3: b"\x00"})

    expected = fixture["writes"][0]["payload"]
    assert payload.hex() == expected


def test_write_only_objects_get_the_no_op_when_untouched() -> None:
    """§4.3: a write-all must not accidentally fire a display or a buzzer."""
    fixture = FIXTURES["multi-instance-and-display"]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None

    text = declaration.objects[-1]
    assert text.write_only is True

    payload = compose_write(declaration, {2: b"\x00"})
    assert payload.endswith(b"\x53\x00")


def test_a_light_that_is_off_is_not_mistaken_for_a_placeholder() -> None:
    """D-009: a fixed-length zero is a state, not a write-only marker.

    Getting this wrong would expose a real switch as a stateless entity that
    never reflects the device.
    """
    fixture = FIXTURES["espruino-multi-instance"]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None

    off_light = next(obj for obj in declaration.objects if obj.value == b"\x00")
    assert off_light.object_id == 0x1E
    assert off_light.write_only is False


def test_no_op_is_refused_for_objects_that_have_none() -> None:
    """A fixed-length object is left alone by resending it, not by a sentinel."""
    fixture = FIXTURES["espruino-single-light"]
    declaration = parse_declaration(objects_of(fixture))
    assert declaration is not None

    with pytest.raises(ProtocolError, match="no no-op value"):
        no_op_value(declaration.objects[0])

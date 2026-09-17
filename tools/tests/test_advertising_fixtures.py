"""Verify `spec/advertising-fixtures.json` against itself and the real parser.

The fixtures are the shared advertising test data. Here they are checked for
internal consistency and, more importantly, fed to `bthome-ble` so that a
fixture claiming "this yields a packet id and a battery" is actually true of the
library Home Assistant uses — with the version 2 declaration at the end.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from tools.gen_advertising_fixtures import (
    DECLARATION_OBJECT_ID,
    OUTPUT,
    SERVICE_DATA_BUDGET,
    uuid,
)
from tools.tests.test_bthome_ble_tolerance import make_service_info

DOCUMENT: dict[str, Any] = json.loads(OUTPUT.read_text(encoding="utf-8"))
FIXTURES: list[dict[str, Any]] = DOCUMENT["fixtures"]
DECLARATION_HEX = f"{DECLARATION_OBJECT_ID:02x}"
FORBIDDEN_ENTRIES = {0x00, 0xFF, 0xF0, 0xF1, 0xF2}  # PROTOCOL.md §2.1


def ids(fixtures: list[dict[str, Any]]) -> list[str]:
    return [f["name"] for f in fixtures]


def parse_with_bthome_ble(service_data: bytes) -> dict[str, Any]:
    from bthome_ble import BTHomeBluetoothDeviceData

    device = BTHomeBluetoothDeviceData()
    update = device.update(make_service_info(service_data))
    entities = {**update.entity_values, **update.binary_entity_values}
    return {
        key.key: value.native_value
        for key, value in entities.items()
        if key.key != "signal_strength"
    }


VALID = [f for f in FIXTURES if f["valid"]]
WITH_SENSORS = [f for f in FIXTURES if "expected_sensors" in f]
WITH_DECLARATION = [f for f in FIXTURES if "declaration" in f]
WITH_ACCESS = [f for f in FIXTURES if f.get("writes") or f.get("reads")]


def test_fixtures_cover_the_cases_the_spec_describes() -> None:
    names = {f["name"] for f in FIXTURES}
    assert {"single-light", "thermostat", "two-lights-and-display"} <= names
    assert {"momentary-action", "twelve-lights", "unknown-entry-type"} <= names
    assert {"rotation-declaration-packet", "rotation-sensor-packet"} <= names
    assert {"plain-bthome-no-declaration", "empty-declaration"} <= names
    violations = {f.get("violates") for f in FIXTURES}
    assert {
        "declaration_not_last",
        "forbidden_entry",
        "capacity_exceeded",
    } <= violations


@pytest.mark.parametrize("fixture", FIXTURES, ids=ids(FIXTURES))
def test_service_data_matches_its_objects(fixture: dict[str, Any]) -> None:
    """The hex payload is exactly the listed objects, concatenated."""
    rebuilt = bytes.fromhex(fixture["device_info_byte"]) + b"".join(
        bytes.fromhex(o["object_id"]) + bytes.fromhex(o["value"])
        for o in fixture["objects"]
    )
    assert rebuilt.hex() == fixture["service_data"]
    assert len(rebuilt) == fixture["service_data_length"]


@pytest.mark.parametrize("fixture", WITH_DECLARATION, ids=ids(WITH_DECLARATION))
def test_declaration_value_is_its_entries(fixture: dict[str, Any]) -> None:
    """§2.1: 0xFF followed by the entries' object IDs, one byte each."""
    declarations = [o for o in fixture["objects"] if o["object_id"] == DECLARATION_HEX]
    assert len(declarations) == 1
    assert declarations[0]["value"] == "".join(fixture["declaration"]["entries"])


@pytest.mark.parametrize("fixture", WITH_DECLARATION, ids=ids(WITH_DECLARATION))
def test_characteristics_are_numbered_from_one_in_entry_order(
    fixture: dict[str, Any],
) -> None:
    """§4.1: entry k lives at 2FAAkkkk, k counted from 1, in hexadecimal."""
    declaration = fixture["declaration"]
    for k, (entry, characteristic) in enumerate(
        zip(declaration["entries"], declaration["characteristics"], strict=True),
        start=1,
    ):
        assert characteristic["entry"] == k
        assert characteristic["object_id"] == entry
        assert characteristic["uuid"] == uuid(k)
        assert characteristic["uuid"] == f"2faa{k:04x}-3b0b-4b1a-9e2a-b4c2952e62f2"


@pytest.mark.parametrize("fixture", WITH_DECLARATION, ids=ids(WITH_DECLARATION))
def test_declaration_is_last_when_valid(fixture: dict[str, Any]) -> None:
    """§2.2: the declaration MUST be the last element of the service data."""
    is_last = fixture["objects"][-1]["object_id"] == DECLARATION_HEX
    assert is_last == fixture["declaration"]["is_last_element"]
    if fixture["valid"]:
        assert is_last


@pytest.mark.parametrize("fixture", WITH_DECLARATION, ids=ids(WITH_DECLARATION))
def test_forbidden_and_unknown_entries_are_not_offered_but_counted(
    fixture: dict[str, Any],
) -> None:
    """§2.1: a receiver skips entries it cannot offer, keeping later numbers."""
    declaration = fixture["declaration"]
    for k in declaration["offered_entries"]:
        assert int(declaration["entries"][k - 1], 16) not in FORBIDDEN_ENTRIES
    for k, entry in enumerate(declaration["entries"], start=1):
        if int(entry, 16) in FORBIDDEN_ENTRIES:
            assert k not in declaration["offered_entries"]


@pytest.mark.parametrize("fixture", VALID, ids=ids(VALID))
def test_valid_fixtures_fit_the_theoretical_budget(fixture: dict[str, Any]) -> None:
    assert fixture["service_data_length"] <= SERVICE_DATA_BUDGET


def test_the_capacity_fixture_really_overflows() -> None:
    """A negative fixture that stopped being negative would test nothing."""
    fixture = next(f for f in FIXTURES if f.get("violates") == "capacity_exceeded")
    assert fixture["service_data_length"] > SERVICE_DATA_BUDGET


@pytest.mark.parametrize("fixture", WITH_SENSORS, ids=ids(WITH_SENSORS))
def test_bthome_ble_yields_the_expected_sensors(fixture: dict[str, Any]) -> None:
    """The load-bearing check: real parser, real payload, claimed entities.

    Every fixture with a declaration also proves D-005 still holds for the list
    form: the parser stops at 0xFF, whatever follows it, and loses nothing
    before it. None of the declared entries produce a sensor.
    """
    parsed = parse_with_bthome_ble(bytes.fromhex(fixture["service_data"]))
    assert parsed == pytest.approx(fixture["expected_sensors"])


def test_the_writable_target_is_not_the_measured_temperature() -> None:
    """§2.3: a declared 0x57 adds no temperature sensor; only the measured 0x02
    appears, so a setpoint can never be mistaken for a reading."""
    fixture = next(f for f in FIXTURES if f["name"] == "thermostat")
    parsed = parse_with_bthome_ble(bytes.fromhex(fixture["service_data"]))
    assert parsed["temperature"] == pytest.approx(25.0)
    assert "57" in fixture["declaration"]["entries"]


def test_rotation_sensor_packet_carries_no_declaration() -> None:
    """§2.2: a packet without the declaration must not be read as 'nothing
    writable' -- which a fixture can only state, and the receiver tests enforce."""
    sensor_packet = next(f for f in FIXTURES if f["name"] == "rotation-sensor-packet")
    declaration_packet = next(
        f for f in FIXTURES if f["name"] == "rotation-declaration-packet"
    )
    assert "declaration" not in sensor_packet
    assert declaration_packet["declaration"]["entries"]


@pytest.mark.parametrize("fixture", WITH_ACCESS, ids=ids(WITH_ACCESS))
def test_each_write_and_read_is_one_object_of_its_entrys_type(
    fixture: dict[str, Any],
) -> None:
    """§4.2, §4.3: one BTHome object per access, matching the entry's type."""
    entries = fixture["declaration"]["entries"]
    for access in fixture.get("writes", []) + fixture.get("reads", []):
        k = access["entry"]
        assert 1 <= k <= len(entries)
        assert access["uuid"] == uuid(k)
        assert access["object"]["object_id"] == entries[k - 1]
        rebuilt = bytes.fromhex(access["object"]["object_id"]) + bytes.fromhex(
            access["object"]["value"]
        )
        assert rebuilt.hex() == access["payload"]


def test_variable_length_writes_keep_bthomes_length_byte() -> None:
    """D-048: values keep BTHome's own encoding, length byte included."""
    fixture = next(f for f in FIXTURES if f["name"] == "two-lights-and-display")
    text = next(w for w in fixture["writes"] if w["name"] == "display-hello")
    payload = bytes.fromhex(text["payload"])
    assert payload[0] == 0x53
    assert payload[1] == len(payload) - 2


def test_generator_is_deterministic() -> None:
    before = OUTPUT.read_bytes()
    subprocess.run(
        [sys.executable, "-m", "tools.gen_advertising_fixtures"],
        check=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert OUTPUT.read_bytes() == before

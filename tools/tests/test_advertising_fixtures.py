"""T0.4 — verify `spec/advertising-fixtures.json` against the real BTHome parser.

The fixtures are the shared advertising test data. Here they are checked for
internal consistency and, more importantly, fed to `bthome-ble` so that a
fixture claiming "this yields a battery and three lights" is actually true of
the library Home Assistant uses.
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
    MAX_WRITABLE,
    OUTPUT,
    SERVICE_DATA_BUDGET,
)
from tools.tests.test_bthome_ble_tolerance import make_service_info

DOCUMENT: dict[str, Any] = json.loads(OUTPUT.read_text(encoding="utf-8"))
FIXTURES: list[dict[str, Any]] = DOCUMENT["fixtures"]


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


def test_fixtures_cover_the_cases_the_task_asks_for() -> None:
    """T0.4's acceptance criteria, restated as an assertion."""
    names = {f["name"] for f in FIXTURES}
    assert {"single-light", "multi-instance-and-display"} <= names
    assert {"write-only-display"} <= names
    assert {"rotation-declaration-packet", "rotation-sensor-packet"} <= names
    assert {"plain-bthome-no-declaration"} <= names
    violations = {f.get("violates") for f in FIXTURES}
    assert "declaration_not_last" in violations
    assert "capacity_exceeded" in violations
    assert any(not f["valid"] for f in FIXTURES)


@pytest.mark.parametrize("fixture", FIXTURES, ids=ids(FIXTURES))
def test_service_data_matches_its_objects(fixture: dict[str, Any]) -> None:
    """The hex payload is exactly the declared objects, concatenated."""
    rebuilt = bytes.fromhex(fixture["device_info_byte"]) + b"".join(
        bytes.fromhex(o["object_id"]) + bytes.fromhex(o["value"])
        for o in fixture["objects"]
    )
    assert rebuilt.hex() == fixture["service_data"]
    assert len(rebuilt) == fixture["service_data_length"]


@pytest.mark.parametrize("fixture", FIXTURES, ids=ids(FIXTURES))
def test_positions_are_consecutive_from_zero(fixture: dict[str, Any]) -> None:
    """§1: position is the 0-based index of an object in the packet."""
    assert [o["position"] for o in fixture["objects"]] == list(
        range(len(fixture["objects"]))
    )


@pytest.mark.parametrize("fixture", WITH_DECLARATION, ids=ids(WITH_DECLARATION))
def test_declaration_bitmask_matches_its_positions(fixture: dict[str, Any]) -> None:
    """§2.2: bit n set means position n is writable, bit 0 = first object."""
    declaration = fixture["declaration"]
    from_bits = [
        bit for bit in range(MAX_WRITABLE) if declaration["bitmask"] & (1 << bit)
    ]
    if declaration["writable_positions"]:
        assert from_bits == declaration["writable_positions"]
    assert declaration["bitmask"] <= 0xFF


@pytest.mark.parametrize("fixture", WITH_DECLARATION, ids=ids(WITH_DECLARATION))
def test_declaration_object_is_present_and_placed_as_claimed(
    fixture: dict[str, Any],
) -> None:
    """§2.2: the declaration MUST be the last element — the invalid one is not."""
    declarations = [
        o
        for o in fixture["objects"]
        if o["object_id"] == f"{DECLARATION_OBJECT_ID:02x}"
    ]
    assert len(declarations) == 1

    is_last = declarations[0]["position"] == len(fixture["objects"]) - 1
    assert is_last == fixture["declaration"]["is_last_element"]
    if fixture["valid"]:
        assert is_last, "a valid fixture must place the declaration last"


@pytest.mark.parametrize("fixture", VALID, ids=ids(VALID))
def test_valid_fixtures_fit_the_advertising_budget(fixture: dict[str, Any]) -> None:
    """§2.3, with the arithmetic spelled out in the fixture file's `budget`."""
    assert fixture["service_data_length"] <= SERVICE_DATA_BUDGET


def test_the_capacity_fixture_really_overflows() -> None:
    """A negative fixture that stopped being negative would test nothing."""
    fixture = next(f for f in FIXTURES if f.get("violates") == "capacity_exceeded")
    assert fixture["service_data_length"] > SERVICE_DATA_BUDGET


def test_the_budget_arithmetic_is_self_consistent() -> None:
    budget = DOCUMENT["budget"]
    assert (
        budget["advertising_payload_bytes"]
        - budget["ad_flags_bytes"]
        - budget["ad_service_data_header_bytes"]
        == budget["service_data_budget"]
    )
    assert budget["service_data_budget"] - 1 == budget["object_budget"]


@pytest.mark.parametrize("fixture", WITH_SENSORS, ids=ids(WITH_SENSORS))
def test_bthome_ble_yields_the_expected_sensors(fixture: dict[str, Any]) -> None:
    """The load-bearing check: real parser, real payload, claimed entities.

    This is what makes the fixtures trustworthy rather than merely plausible —
    including `declaration-not-last`, which claims to yield *nothing* and does.
    """
    parsed = parse_with_bthome_ble(bytes.fromhex(fixture["service_data"]))
    assert parsed == pytest.approx(fixture["expected_sensors"])


def test_plain_bthome_device_carries_no_declaration() -> None:
    """The integration's not_supported abort depends on this being detectable."""
    fixture = next(f for f in FIXTURES if f["name"] == "plain-bthome-no-declaration")
    assert "declaration" not in fixture
    assert all(
        o["object_id"] != f"{DECLARATION_OBJECT_ID:02x}" for o in fixture["objects"]
    )


def test_rotation_pair_obeys_the_same_packet_rule() -> None:
    """§2.1: the declaration packet is self-contained; the other one is not it."""
    declaration_packet = next(
        f for f in FIXTURES if f["name"] == "rotation-declaration-packet"
    )
    sensor_packet = next(f for f in FIXTURES if f["name"] == "rotation-sensor-packet")

    writable = declaration_packet["declaration"]["writable_positions"]
    assert writable, "the declaration packet must actually declare something"
    # Every writable position exists in this packet, not somewhere in the rotation.
    for position in writable:
        assert position < len(declaration_packet["objects"])

    assert "declaration" not in sensor_packet


@pytest.mark.parametrize(
    "fixture",
    [f for f in FIXTURES if f.get("writes")],
    ids=ids([f for f in FIXTURES if f.get("writes")]),
)
def test_write_payloads_carry_every_writable_object_in_order(
    fixture: dict[str, Any],
) -> None:
    """§4.2: write-all in packet order, with the object IDs matching positions."""
    expected_ids = [
        fixture["objects"][position]["object_id"]
        for position in fixture["declaration"]["writable_positions"]
    ]
    for entry in fixture["writes"]:
        assert [o["object_id"] for o in entry["objects"]] == expected_ids
        rebuilt = b"".join(
            bytes.fromhex(o["object_id"]) + bytes.fromhex(o["value"])
            for o in entry["objects"]
        )
        assert rebuilt.hex() == entry["payload"]


def test_no_op_conventions_appear_in_the_write_fixtures() -> None:
    """§4.3: length 0 on a variable-length object means 'do not modify'."""
    fixture = next(f for f in FIXTURES if f["name"] == "multi-instance-and-display")
    no_op = next(w for w in fixture["writes"] if w["name"] == "second-light-off")
    text = no_op["objects"][-1]
    assert text["object_id"] == "53"
    assert text["value"] == "00", "the text object must carry the length-0 no-op"


def test_generator_is_deterministic() -> None:
    before = OUTPUT.read_bytes()
    subprocess.run(
        [sys.executable, "-m", "tools.gen_advertising_fixtures"],
        check=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert OUTPUT.read_bytes() == before

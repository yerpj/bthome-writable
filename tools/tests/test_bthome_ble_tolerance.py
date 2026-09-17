"""T0.5 [VERIFY] — how does `bthome-ble` react to the 0xFF declaration object?

This gates the container choice of PROTOCOL §3.1: if the upstream parser
tolerates (or silently skips) an unknown object ID, the declaration can live in
the BTHome service data itself. If it fails loudly, the declaration has to move
to a manufacturer-data element until the ID is reserved upstream.

Result is recorded in spec/decisions.md (D-005).
"""

from __future__ import annotations

import logging

from bthome_ble import BTHomeBluetoothDeviceData
from bthome_ble.const import MEAS_TYPES
from habluetooth import BluetoothServiceInfoBleak
import pytest

from tools.bthome_fixtures import Obj, declaration, service_data

MAC = "A4:C1:38:00:11:22"


def make_service_info(payload: bytes) -> BluetoothServiceInfoBleak:
    """Wrap a BTHome service-data payload into a service info object."""
    return BluetoothServiceInfoBleak(
        name="TestDevice",
        address=MAC,
        rssi=-60,
        manufacturer_data={},
        service_data={"0000fcd2-0000-1000-8000-00805f9b34fb": payload},
        service_uuids=["0000fcd2-0000-1000-8000-00805f9b34fb"],
        source="local",
        device=None,  # type: ignore[arg-type]
        advertisement=None,  # type: ignore[arg-type]
        connectable=True,
        time=0.0,
        tx_power=-127,
    )


def parse(payload: bytes) -> dict:
    """Parse a payload and return {entity key: native value}, minus RSSI."""
    device = BTHomeBluetoothDeviceData()
    update = device.update(make_service_info(payload))
    entities = {**update.entity_values, **update.binary_entity_values}
    return {
        key.key: desc.native_value
        for key, desc in entities.items()
        if key.key != "signal_strength"
    }


def test_0xff_is_not_a_registered_object_id() -> None:
    """The declaration ID must not collide with an existing BTHome object."""
    assert 0xFF not in MEAS_TYPES
    assert max(MEAS_TYPES) == 0xF2


def test_declaration_last_keeps_all_sensors() -> None:
    """Declaration as the last element: every preceding sensor still parses."""
    payload = service_data(
        Obj(0x01, bytes([97])),  # battery 97 %
        Obj(0x1E, bytes([1])),  # light on
        declaration(0x1E),  # object #1 (the light) is writable
    )
    values = parse(payload)
    assert values["battery"] == 97
    assert values["light"] is True


def test_declaration_first_hides_following_sensors() -> None:
    """Declaration first: the parser stops there, later sensors are lost.

    This is what makes the 'declaration last' placement normative in §3.1.
    """
    payload = service_data(
        declaration(0x1E),
        Obj(0x01, bytes([97])),
        Obj(0x1E, bytes([1])),
    )
    assert parse(payload) == {}


def test_unknown_object_id_does_not_raise_or_log_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No exception, and nothing above DEBUG level, on the unknown 0xFF object."""
    payload = service_data(
        Obj(0x01, bytes([97])),
        Obj(0x1E, bytes([1])),
        declaration(0x1E),
    )
    with caplog.at_level(logging.DEBUG, logger="bthome_ble.parser"):
        parse(payload)

    assert not [r for r in caplog.records if r.levelno >= logging.INFO], (
        "unexpected non-debug log records: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    assert any(
        "Invalid Object ID" in r.getMessage()
        for r in caplog.records
        if r.levelno == logging.DEBUG
    )


def test_declaration_last_satisfies_ascending_object_id_order() -> None:
    """0xFF is above every assigned ID, so 'last' also keeps IDs ascending.

    `bthome-ble` warns (at WARNING level) when object IDs are not ascending;
    putting the declaration last avoids that warning for free.
    """
    assert max(MEAS_TYPES) < 0xFF


def test_multi_instance_same_object_id() -> None:
    """Several objects with the same ID in one packet (PROTOCOL §3.1).

    `bthome-ble` suffixes duplicate keys with their 1-based occurrence index in
    packet order (`light_1`, `light_2`, ...). Version 2 numbers duplicate entries
    the same way (entry order), so a receiver can name writable instances with
    the convention users already see on sensors.
    """
    payload = service_data(
        Obj(0x01, bytes([97])),
        Obj(0x1E, bytes([1])),
        Obj(0x1E, bytes([0])),
        Obj(0x1E, bytes([1])),
        declaration(0x1E, 0x1E, 0x1E),
    )
    device = BTHomeBluetoothDeviceData()
    update = device.update(make_service_info(payload))
    lights = {
        key.key: desc.native_value for key, desc in update.binary_entity_values.items()
    }
    assert lights == {"light_1": True, "light_2": False, "light_3": True}


def test_entries_that_are_valid_object_ids_create_no_sensors() -> None:
    """PROTOCOL.md §2.1 (version 2): the declaration's entries are object IDs.

    `FF 01 02` lists a battery and a temperature. If the parser read past `0xFF`
    it would try to decode them as a battery and a temperature and invent
    sensors. It stops at the unknown ID instead, so declaring a writable battery
    or temperature can never be mistaken for measuring one.
    """
    payload = service_data(
        Obj(0x00, bytes([0x09])),
        declaration(0x01, 0x02, 0x1E),
    )
    assert parse(payload) == {"packet_id": 9}


def test_zero_length_text_object_is_dropped_not_fatal() -> None:
    """The parser skips a zero-length object and keeps going.

    Version 1 relied on this for its write-only placeholder; version 2 advertises
    no writable values at all, but the tolerance is still worth pinning down.
    """
    payload = service_data(
        Obj(0x01, bytes([97])),
        Obj(0x53, bytes([0])),  # text, length 0 -> write-only placeholder
        declaration(0x1E),
    )
    values = parse(payload)
    assert values["battery"] == 97
    assert "text" not in values


def test_declaration_survives_encrypted_advertising() -> None:
    """Encrypted advertising: the declaration is inside the ciphertext.

    It is parsed by the same object loop after decryption, so the tolerance
    result holds for encrypted devices too.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM

    bindkey = bytes.fromhex("231d39c1d7cc1ab1aee224cd096db932")
    plaintext = (
        Obj(0x00, bytes([0x09])).encode()  # packet id
        + Obj(0x01, bytes([97])).encode()
        + Obj(0x1E, bytes([1])).encode()
        + declaration(0x1E).encode()
    )
    counter = (1).to_bytes(4, "little")
    nonce = (
        bytes.fromhex(MAC.replace(":", ""))
        + bytes.fromhex("d2fc")
        + bytes([0x41])
        + counter
    )
    encrypted = AESCCM(bindkey, tag_length=4).encrypt(nonce, plaintext, None)
    payload = bytes([0x41]) + encrypted[:-4] + counter + encrypted[-4:]

    device = BTHomeBluetoothDeviceData(bindkey=bindkey)
    update = device.update(make_service_info(payload))
    assert device.bindkey_verified
    entities = {**update.entity_values, **update.binary_entity_values}
    values = {k.key: v.native_value for k, v in entities.items()}
    assert values["battery"] == 97
    assert values["light"] is True

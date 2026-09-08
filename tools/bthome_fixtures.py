"""Helpers to build BTHome v2 advertisements for tests and fixtures.

Kept deliberately small and dependency-free (except for the BLE service-info
type needed to feed `bthome-ble`), so both the T0.5 verification and the later
integration tests can share it.
"""

from __future__ import annotations

from dataclasses import dataclass

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"

# BTHome v2 device-information byte, advertising direction, unencrypted,
# regular (non-trigger based) device: version 2 in bits 5-7 -> 0x40.
DEVICE_INFO_ADV_PLAIN = 0x40
DEVICE_INFO_ADV_ENCRYPTED = 0x41


@dataclass(frozen=True)
class Obj:
    """One BTHome object: an ID plus its already-encoded value bytes."""

    object_id: int
    value: bytes = b""

    def encode(self) -> bytes:
        return bytes([self.object_id]) + self.value


def service_data(*objects: Obj, device_info: int = DEVICE_INFO_ADV_PLAIN) -> bytes:
    """Concatenate the device-info byte and the encoded objects."""
    return bytes([device_info]) + b"".join(obj.encode() for obj in objects)


def declaration(bitmask: int, object_id: int = 0xFF) -> Obj:
    """The writability declaration object: <object_id> <bitmask u8>."""
    return Obj(object_id, bytes([bitmask]))

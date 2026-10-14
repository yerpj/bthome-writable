"""The three tests the pull request would add, run against the patched copy."""

from __future__ import annotations

from habluetooth import BluetoothServiceInfoBleak
from sensor_state_data import DeviceKey

from bthome_ble.parser import BTHomeBluetoothDeviceData

ADVERTISEMENT_TIME = 1700000000.0


def bytes_to_service_info(
    payload: bytes,
    local_name: str,
    address: str = "00:00:00:00:00:00",
    time: float = ADVERTISEMENT_TIME,
) -> BluetoothServiceInfoBleak:
    """Convert bytes to service info"""
    return BluetoothServiceInfoBleak(
        name=local_name,
        address=address,
        rssi=-60,
        manufacturer_data={},
        service_data={"0000fcd2-0000-1000-8000-00805f9b34fb": payload},
        service_uuids=[],
        source="",
        device=None,
        advertisement=None,
        connectable=False,
        time=time,
        tx_power=None,
    )


def test_bthome_writable_entries() -> None:
    """Object 0xFF lists the object IDs a device accepts writes for."""
    data_string = b"\x40\xff\x01\x1e"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    device.update(advertisement)

    assert device.writable_entries == (0x1E,)


def test_bthome_writable_entries_does_not_stop_the_parser() -> None:
    """The reason for this object having a length: what follows it survives."""
    data_string = b"\x40\xff\x02\x1e\x53\x01\x61"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    result = device.update(advertisement)

    assert device.writable_entries == (0x1E, 0x53)
    assert (
        result.entity_values[
            DeviceKey(key="battery", device_id=None)
        ].native_value
        == 97
    )


def test_bthome_writable_entries_truncated() -> None:
    """A length byte promising more than the packet holds is dropped."""
    data_string = b"\x40\xff\x04\x1e"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    device.update(advertisement)

    assert device.writable_entries is None


def test_a_device_that_never_declares_is_untouched() -> None:
    """The change must be invisible to everyone else."""
    data_string = b"\x40\x02\xc4\x09\x03\xbf\x13"
    advertisement = bytes_to_service_info(
        data_string, local_name="TEST DEVICE", address="A4:C1:38:8D:18:B2"
    )

    device = BTHomeBluetoothDeviceData()
    result = device.update(advertisement)

    assert device.writable_entries is None
    assert (
        result.entity_values[
            DeviceKey(key="temperature", device_id=None)
        ].native_value
        == 25.0
    )

"""Test harness for the BTHome Writable integration."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

from habluetooth import BluetoothServiceInfoBleak
import pytest
import pytest_socket

# `custom_components/` sits at the repository root so that HACS can install
# straight from GitHub, which is what HACS expects to find there. That is one
# level above `ha/`, where the tests live, so the root goes on sys.path for
# pytest-homeassistant-custom-component to import the integration.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FIXTURES_FILE = (
    Path(__file__).resolve().parents[2] / "spec" / "advertising-fixtures.json"
)
FIXTURES: dict[str, dict[str, Any]] = {
    entry["name"]: entry
    for entry in json.loads(FIXTURES_FILE.read_text(encoding="utf-8"))["fixtures"]
}

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
DEFAULT_ADDRESS = "A4:C1:38:8E:1F:2B"

# Written out rather than imported from the integration, so the tests check the
# UUIDs against the specification (§4.1) instead of against themselves.
UUID_TEMPLATE = "2faa{:04x}-3b0b-4b1a-9e2a-b4c2952e62f2"


# --- Two things this suite has to switch off ---------------------------------
#
# Both look like platform quirks and are not: they were first hit on Windows,
# then again on Linux in CI. They come from testing a custom component against
# Home Assistant's `bluetooth` integration with nothing but
# pytest-homeassistant-custom-component, which provides the fixtures but not the
# surrounding setup Home Assistant's own repository has. Both are reproducible
# with an empty test that requests `enable_bluetooth` and nothing else.

# Setting up the `bluetooth` component opens a socket, and pytest-socket blocks
# it before any fixture of ours can ask for `socket_enabled`. Nothing in this
# suite talks to a network or a radio: the transport is faked in `radio` and
# `gatt`.
pytest_socket.disable_socket = lambda *args, **kwargs: None
pytest_socket.enable_socket()


@pytest.fixture(autouse=True)
def verify_cleanup():
    """Drop Home Assistant's lingering-timer assertion.

    `enable_bluetooth` leaves a `BluetoothManager._async_check_unavailable`
    timer behind, on every platform. Overriding the fixture is blunt -- it also
    stops the check catching a timer of ours -- but the alternative is a suite
    that cannot run at all.
    """
    yield


@pytest.fixture(autouse=True, scope="session")
def _no_dbus_history():
    """Keep the suite off the host's D-Bus entirely.

    `mock_bluetooth_adapters` patches the adapter list to a fake Linux adapter
    but not the advertisement history, so setting up the `bluetooth` component
    reaches a real D-Bus call — which fails outright on Windows, and depends on
    what the machine happens to have running everywhere else. Neither is
    something a unit test should be asking about.
    """
    from bluetooth_adapters.systems.linux import LinuxAdapters

    with patch.object(
        LinuxAdapters, "history", new_callable=lambda: property(lambda self: {})
    ):
        yield


@pytest.fixture
def custom_integration(enable_custom_integrations, enable_bluetooth):
    """Make `custom_components/` loadable, with a mock Bluetooth stack up.

    Requested explicitly rather than autouse: it pulls in the `hass` fixture,
    and the protocol tests want neither. `enable_bluetooth` is needed because
    the manifest depends on `bluetooth_adapters`, which will not set up without
    it -- and a failed dependency setup makes every entry silently do nothing.
    """
    return


def service_info(
    fixture_name: str,
    *,
    address: str = DEFAULT_ADDRESS,
    name: str = "Espruino Light",
    rssi: int = -60,
    time: float = 0.0,
    service_data: bytes | None = None,
) -> BluetoothServiceInfoBleak:
    """Build a BLE service info from one of the shared advertising fixtures.

    Tests describe devices by fixture name rather than by hex, so the
    integration is exercised against the same payloads the spec and the Espruino
    suite use (CLAUDE.md rule 6).
    """
    payload = service_data
    if payload is None:
        payload = bytes.fromhex(FIXTURES[fixture_name]["service_data"])

    return BluetoothServiceInfoBleak(
        name=name,
        address=address,
        rssi=rssi,
        manufacturer_data={},
        service_data={BTHOME_UUID: payload},
        service_uuids=[BTHOME_UUID],
        source="local",
        device=None,  # type: ignore[arg-type]
        advertisement=None,  # type: ignore[arg-type]
        connectable=True,
        time=time,
        tx_power=-127,
    )


class FakeCharacteristic:
    def __init__(self, uuid: str, properties: list[str]) -> None:
        self.uuid = uuid
        self.properties = properties


class FakeGattClient:
    """A connected device, as far as the coordinator talks to one.

    Holds one characteristic per declared entry, records every write as
    `(uuid, payload)`, serves reads from `readable`, and can be told to fail a
    given write. Everything the coordinator does over GATT goes through here,
    so the tests see the bytes the protocol puts on the air.
    """

    def __init__(self) -> None:
        self.characteristics: dict[str, FakeCharacteristic] = {}
        self.readable: dict[str, bytes] = {}
        self.writes: list[tuple[str, bytes]] = []
        self.reads: list[str] = []
        self.fail_on_write: Exception | None = None
        self.fail_on_read: Exception | None = None
        self.connections = 0
        self.disconnects = 0
        self.cache_cleared = 0
        self.services = self

    def declare(self, entries: int, readable: dict[int, bytes] | None = None) -> None:
        readable = readable or {}
        for k in range(1, entries + 1):
            uuid = UUID_TEMPLATE.format(k)
            props = ["write", "read"] if k in readable else ["write"]
            self.characteristics[uuid] = FakeCharacteristic(uuid, props)
            if k in readable:
                self.readable[uuid] = readable[k]

    # `client.services.get_characteristic(uuid)`
    def get_characteristic(self, uuid: str) -> FakeCharacteristic | None:
        return self.characteristics.get(uuid)

    async def write_gatt_char(self, characteristic, payload, response=True) -> None:
        assert response, "PROTOCOL.md §4.2: writes are with response"
        if self.fail_on_write is not None:
            raise self.fail_on_write
        self.writes.append((characteristic.uuid, bytes(payload)))

    async def read_gatt_char(self, characteristic) -> bytes:
        if self.fail_on_read is not None:
            raise self.fail_on_read
        self.reads.append(characteristic.uuid)
        return self.readable[characteristic.uuid]

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def clear_cache(self) -> None:
        self.cache_cleared += 1


@pytest.fixture
def gatt():
    """Patch the connection path so writes and reads reach a FakeGattClient."""
    client = FakeGattClient()

    async def connect(**_kwargs):
        client.connections += 1
        return client

    module = "custom_components.bthome_writable.coordinator"
    with (
        patch(
            f"{module}.bluetooth.async_ble_device_from_address", return_value=object()
        ),
        patch(f"{module}.establish_connection", connect),
    ):
        yield client


class FakeRadio:
    """Stands in for the Bluetooth stack, so tests control advertisements."""

    def __init__(self) -> None:
        self.last: BluetoothServiceInfoBleak | None = None
        self._callbacks: list[Any] = []
        self._unavailable: list[Any] = []

    def push(self, info: BluetoothServiceInfoBleak) -> None:
        """Deliver one advertisement to the integration."""
        self.last = info
        for callback in list(self._callbacks):
            callback(info, None)

    def vanish(self) -> None:
        """The device stops advertising."""
        for callback in list(self._unavailable):
            callback(self.last)

    # --- the bits of homeassistant.components.bluetooth we stand in for ---

    def async_last_service_info(self, _hass, _address, connectable=True):
        return self.last

    def async_register_callback(self, _hass, callback, _matcher, _mode):
        self._callbacks.append(callback)
        return lambda: self._callbacks.remove(callback)

    def async_track_unavailable(self, _hass, callback, _address, connectable=True):
        self._unavailable.append(callback)
        return lambda: self._unavailable.remove(callback)


@pytest.fixture
def radio():
    """Patch the integration's view of the Bluetooth stack."""
    fake = FakeRadio()
    module = "custom_components.bthome_writable"
    with (
        patch(
            f"{module}.bluetooth.async_last_service_info", fake.async_last_service_info
        ),
        patch(
            f"{module}.bluetooth.async_register_callback", fake.async_register_callback
        ),
        patch(
            f"{module}.bluetooth.async_track_unavailable", fake.async_track_unavailable
        ),
    ):
        yield fake


async def setup_device(hass, radio, fixture_name: str, **kwargs: Any):
    """Bring one configured device up, seeded with a first advertisement."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bthome_writable.const import DOMAIN

    radio.last = service_info(fixture_name, **kwargs)
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEFAULT_ADDRESS, data={}, title="Espruino Light"
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def settle(hass, seconds: float = 0.05) -> None:
    import asyncio

    await asyncio.sleep(seconds)
    await hass.async_block_till_done()

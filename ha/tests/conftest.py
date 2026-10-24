"""Test harness for the BTHome Writable integration."""

from __future__ import annotations

import asyncio
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


@pytest.fixture(autouse=True)
def one_host_cap_per_test():
    """A fresh connection cap, before and after every test.

    The gate of D-132 is module state, deliberately: it is the host's, not any
    entry's. So a request a test leaves behind would cap the next one, and a
    gate that has been waited on in one event loop cannot be waited on in the
    next test's loop.
    """
    from custom_components.bthome_writable import slots

    slots.reset()
    yield
    slots.reset()


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
        self.fail_on_connect: Exception | None = None
        """What `establish_connection` raises, when it is to raise at all.

        A host out of connection slots is the case this exists for (D-133): the
        device is fine, and the connection never happens."""
        self.connections = 0
        self.disconnects = 0
        self.cache_cleared = 0
        self.echo_writes = True
        self.services = self

    def declare(self, entries: int, readable: dict[int, bytes] | None = None) -> None:
        readable = readable or {}
        for k in range(1, entries + 1):
            uuid = UUID_TEMPLATE.format(k)
            props = ["write", "read"] if k in readable else ["write"]
            self.characteristics[uuid] = FakeCharacteristic(uuid, props)
            if k in readable:
                self.readable[uuid] = readable[k]

    def offer_counter_report(self, answer) -> None:
        """Install the counter report of D-075 at 2FAA1000.

        `answer` is either the bytes to return or a callable, so a test can
        seal a report around the challenge the receiver actually sent."""
        from custom_components.bthome_writable.const import COUNTER_UUID

        self.characteristics[COUNTER_UUID] = FakeCharacteristic(
            COUNTER_UUID, ["write", "read"]
        )
        self.readable[COUNTER_UUID] = answer

    # `client.services.get_characteristic(uuid)`
    def get_characteristic(self, uuid: str) -> FakeCharacteristic | None:
        return self.characteristics.get(uuid)

    @staticmethod
    def _uuid(characteristic) -> str:
        """bleak takes either a characteristic or a plain UUID string.

        The fake only understood the object, so the counter-report path --
        which passes the string -- could not be exercised at all. Supporting
        both is what the real client does."""
        return (
            characteristic if isinstance(characteristic, str) else characteristic.uuid
        )

    async def write_gatt_char(self, characteristic, payload, response=True) -> None:
        assert response, "PROTOCOL.md §4.2: writes are with response"
        if self.fail_on_write is not None:
            raise self.fail_on_write
        uuid = self._uuid(characteristic)
        self.writes.append((uuid, bytes(payload)))
        if (
            self.echo_writes
            and uuid in self.readable
            and not callable(self.readable[uuid])
        ):
            # A device that took the write reports the new value afterwards:
            # §4.3, and the module republishes it for exactly that reason
            # (D-092). A receiver that reads back to confirm a write (D-117) is
            # otherwise testing a device that acknowledges and never changes,
            # which is the fault, not the normal case. `echo_writes = False` is
            # how a test asks for that fault -- or for a sealed device, whose
            # answer this fake cannot seal.
            self.readable[uuid] = bytes(payload)

    async def read_gatt_char(self, characteristic) -> bytes:
        if self.fail_on_read is not None:
            raise self.fail_on_read
        uuid = self._uuid(characteristic)
        self.reads.append(uuid)
        if callable(answer := self.readable[uuid]):
            return answer()
        return answer

    async def disconnect(self) -> None:
        self.disconnects += 1

    async def clear_cache(self) -> None:
        self.cache_cleared += 1


@pytest.fixture
def gatt():
    """Patch the connection path so writes and reads reach a FakeGattClient."""
    client = FakeGattClient()

    async def connect(**_kwargs):
        if client.fail_on_connect is not None:
            raise client.fail_on_connect
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


async def setup_device(
    hass, radio, fixture_name: str, entry_data: dict | None = None, **kwargs: Any
):
    """Bring one configured device up, seeded with a first advertisement.

    `entry_data` goes into the config entry -- a bindkey, a stored counter --
    while the rest shapes the advertisement the radio serves.
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bthome_writable.const import DOMAIN

    radio.last = service_info(fixture_name, **kwargs)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEFAULT_ADDRESS,
        data=entry_data or {},
        title="Espruino Light",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


LIGHT, COUNT = 0x1E, 0x09
"""@enaon's pair: the lamp, and the count his dimmer rides on."""


def a_lamp_and_a_dimmer(
    hass,
    address: str = DEFAULT_ADDRESS,
    *,
    due: bool = True,
    revision: int = 4,
    **kwargs,
):
    """A two-entry device, owing the read of §3.2 or not.

    `due` is the only thing the read tests vary: the revision the device
    advertises against the one we have read (§3.2). Shared because D-130's
    tests and D-131's are about the same device -- one that both takes commands
    and reports state, which is what made the collision visible at all.
    """
    from custom_components.bthome_writable.coordinator import BTHomeWritableCoordinator
    from custom_components.bthome_writable.protocol import Declaration

    coordinator = BTHomeWritableCoordinator(hass, address, **kwargs)
    coordinator.declaration = Declaration.restore(
        {"layout": [LIGHT, COUNT], "settings_revision": revision}
    )
    coordinator._revision_advertised = revision
    coordinator._revision_read = revision - 1 if due else revision
    return coordinator


async def settle(hass, seconds: float = 0.05) -> None:
    await asyncio.sleep(seconds)
    await hass.async_block_till_done()


async def let_the_others_run(times: int = 5) -> None:
    """Yield until every runnable task has reached its next real wait.

    Not a sleep: a task held at a gate never reaches a timer, so sleeping for
    it would wait for ever in this harness. Yielding is also the right
    granularity when what is asserted is that a caller *cannot* proceed.
    """
    for _ in range(times):
        await asyncio.sleep(0)


def hold_the_first(
    gatt: FakeGattClient, *, read: int | None = None, write: bool = False
) -> tuple[asyncio.Event, asyncio.Event]:
    """Freeze the first read of one entry, or the first write, mid-connection.

    Returns `(reached, release)`: `reached` is set when the call arrives, and
    setting `release` lets it finish. Only the first matching call is held, so
    everything that follows runs normally -- which is what a test asserting an
    *ordering* needs, and the reason this is not a sleep.
    """
    reached, release = asyncio.Event(), asyncio.Event()
    served_read, served_write = gatt.read_gatt_char, gatt.write_gatt_char
    target = None if read is None else UUID_TEMPLATE.format(read)

    async def held_read(characteristic):
        if not release.is_set() and FakeGattClient._uuid(characteristic) == target:
            reached.set()
            await release.wait()
        return await served_read(characteristic)

    async def held_write(characteristic, payload, response=True):
        if not release.is_set():
            reached.set()
            await release.wait()
        return await served_write(characteristic, payload, response)

    if read is not None:
        gatt.read_gatt_char = held_read
    if write:
        gatt.write_gatt_char = held_write
    return reached, release

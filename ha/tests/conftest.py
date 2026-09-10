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
# `mock_write`.
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


def with_light(fixture_name: str, on: bool, **kwargs: Any) -> BluetoothServiceInfoBleak:
    """The same fixture with its light object flipped.

    Used to simulate the device confirming (or failing to confirm) a write.
    """
    payload = bytearray(bytes.fromhex(FIXTURES[fixture_name]["service_data"]))
    for index in range(len(payload) - 1):
        if payload[index] == 0x1E:
            payload[index + 1] = 1 if on else 0
            break
    return service_info(fixture_name, service_data=bytes(payload), **kwargs)


@pytest.fixture
def mock_write():
    """Capture what the integration would send, without a radio.

    Patches only the transport: the payload the test sees is the one the
    coordinator composed, byte for byte, as PROTOCOL.md §4.2 describes it.
    """
    written: list[bytes] = []

    async def _write_now(self, payload):
        written.append(payload)

    with patch(
        "custom_components.bthome_writable.coordinator."
        "BTHomeWritableCoordinator._write_now",
        _write_now,
    ):
        yield written


class FakeRadio:
    """Stands in for the Bluetooth stack, so tests can time advertisements.

    The confirmation model of §6 is entirely about *when* an advertisement
    arrives relative to a write, so the tests need to drive that themselves
    rather than hope a real scanner cooperates.
    """

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

"""Test harness for the BTHome Writable integration."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

from habluetooth import BluetoothServiceInfoBleak
import pytest

# The integration lives under ha/custom_components/, which is where
# pytest-homeassistant-custom-component expects to find it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURES_FILE = (
    Path(__file__).resolve().parents[2] / "spec" / "advertising-fixtures.json"
)
FIXTURES: dict[str, dict[str, Any]] = {
    entry["name"]: entry
    for entry in json.loads(FIXTURES_FILE.read_text(encoding="utf-8"))["fixtures"]
}

BTHOME_UUID = "0000fcd2-0000-1000-8000-00805f9b34fb"
DEFAULT_ADDRESS = "A4:C1:38:8E:1F:2B"


if sys.platform == "win32":  # pragma: no cover - platform-specific
    # Windows only. On Linux, asyncio builds its event-loop self-pipe out of
    # os.pipe(), which is why Home Assistant's own suite runs happily with
    # pytest-socket enforcing "no sockets in tests". On Windows the self-pipe is
    # a socket pair, created inside Home Assistant's event-loop policy before
    # any fixture can ask for `socket_enabled` -- so every test errors out
    # before it starts. Neutralising the block is the only order-independent
    # fix; nothing in this suite opens a network connection, and the mocked
    # write path never touches a radio.
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None
    pytest_socket.enable_socket()


@pytest.fixture(autouse=True, scope="session")
def _no_dbus_history():
    """Windows only: the harness pretends to be Linux, D-Bus is not there.

    `mock_bluetooth_adapters` patches the adapter list to a fake Linux adapter,
    but not the advertisement history, so setting up the `bluetooth` component
    reaches a real D-Bus call and the whole dependency chain fails to set up.
    Home Assistant's own suite does not hit this because it runs on Linux.
    """
    if sys.platform != "win32":
        yield
        return

    from bluetooth_adapters.systems.linux import LinuxAdapters

    with patch.object(
        LinuxAdapters, "history", new_callable=lambda: property(lambda self: {})
    ):
        yield


if sys.platform == "win32":  # pragma: no cover - platform-specific

    @pytest.fixture(autouse=True)
    def verify_cleanup():
        """Windows only: drop Home Assistant's lingering-timer assertion.

        `enable_bluetooth` leaves a BaseHaScanner expiry timer behind on
        Windows -- reproducible with an empty test that requests nothing but
        that fixture, so it is the harness, not this integration. CI runs on
        Linux with the real check in place, which is where a lingering timer of
        our own would surface.
        """
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

    Patches the coordinator's transport, not its composition: the payload the
    test sees is the one PROTOCOL.md §4.2 describes, byte for byte.
    """
    written: list[bytes] = []

    async def _write_now(self, changes):
        from custom_components.bthome_writable.protocol import compose_write

        if self.declaration is None:
            raise AssertionError("wrote before seeing a declaration")
        written.append(compose_write(self.declaration, changes))

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

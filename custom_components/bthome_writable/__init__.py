"""The BTHome Writable integration.

Downlink companion to the core BTHome integration: devices declare writable
objects in their advertising, this integration writes new values back over a
short GATT connection. See spec/PROTOCOL.md.
"""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback

from .const import CONF_MAX_CONNECTIONS, DEFAULT_MAX_CONNECTIONS, DOMAIN
from .coordinator import BTHomeWritableCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH]

type BTHomeWritableConfigEntry = ConfigEntry[BTHomeWritableCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: BTHomeWritableConfigEntry
) -> bool:
    """Set up a writable BTHome device from a config entry."""
    address = entry.unique_id
    assert address is not None

    coordinator = BTHomeWritableCoordinator(
        hass,
        address,
        name=entry.title,
        max_connections=entry.options.get(
            CONF_MAX_CONNECTIONS, DEFAULT_MAX_CONNECTIONS
        ),
    )
    entry.runtime_data = coordinator

    # Seed from whatever the Bluetooth stack has already seen, so entities exist
    # at the end of setup rather than one advertising interval later.
    service_info = bluetooth.async_last_service_info(hass, address, connectable=True)
    if service_info is not None:
        coordinator.async_handle_advertisement(service_info)

    @callback
    def _advertisement(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        coordinator.async_handle_advertisement(service_info)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _advertisement,
            bluetooth.BluetoothCallbackMatcher(address=address, connectable=True),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    # Availability follows advertising presence, the same signal the core BTHome
    # integration uses: a device that stopped advertising is gone, whether or
    # not it would still answer a connection.
    @callback
    def _unavailable(_service_info: bluetooth.BluetoothServiceInfoBleak) -> None:
        coordinator.async_set_unavailable()

    entry.async_on_unload(
        bluetooth.async_track_unavailable(hass, _unavailable, address, connectable=True)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BTHomeWritableConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


__all__ = ["DOMAIN", "async_setup_entry", "async_unload_entry"]

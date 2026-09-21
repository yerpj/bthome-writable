"""The BTHome Writable integration.

Downlink companion to the core BTHome integration: devices declare the object
types they accept writes for, this integration writes values back over a short
GATT connection, one characteristic per entry. See spec/PROTOCOL.md.
"""

from __future__ import annotations

import logging
import time

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_BINDKEY,
    CONF_MAX_CONNECTIONS,
    CONF_WRITE_COUNTER,
    COUNTER_EPOCH_SEED,
    DEFAULT_MAX_CONNECTIONS,
    DOMAIN,
)
from .coordinator import BTHomeWritableCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.TEXT,
]

type BTHomeWritableConfigEntry = ConfigEntry[BTHomeWritableCoordinator]


def _starting_counter(stored: int) -> int:
    """Where the write counter resumes: never below the clock (§5.3, D-063).

    The stored mark wins when it is ahead, which is the ordinary case within one
    installation. The clock wins when the entry is younger than the device --
    re-created, restored from an old backup, moved to another Home Assistant --
    which is exactly the case where resuming from the stored value would have
    every write silently refused as a replay.
    """
    if not COUNTER_EPOCH_SEED:
        return stored
    return max(stored, int(time.time()))


async def async_setup_entry(
    hass: HomeAssistant, entry: BTHomeWritableConfigEntry
) -> bool:
    """Set up a writable BTHome device from a config entry."""
    address = entry.unique_id
    assert address is not None

    stored = entry.data.get(CONF_BINDKEY)
    bindkey = bytes.fromhex(stored) if stored else None

    @callback
    def _remember_counter(mark: int) -> None:
        # The counter lives in the config entry so it survives a restart, which
        # section 5.2 requires: resuming low would make every write look like a
        # replay to the device, and a refused write is silent.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_WRITE_COUNTER: mark}
        )

    coordinator = BTHomeWritableCoordinator(
        hass,
        address,
        name=entry.title,
        max_connections=entry.options.get(
            CONF_MAX_CONNECTIONS, DEFAULT_MAX_CONNECTIONS
        ),
        bindkey=bindkey,
        write_counter=_starting_counter(entry.data.get(CONF_WRITE_COUNTER, 0)),
        on_counter=_remember_counter,
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

    if bindkey is None and coordinator.declaration is not None:
        # Section 5 permits unencrypted devices, and BTHome's own policy does
        # too, so this is a warning rather than a refusal. It is worth saying
        # once: anyone within radio range can write to an actuator that is not
        # sealed, and the user cannot tell from the interface that this is so.
        _LOGGER.warning(
            "%s exposes %d writable entr%s without encryption: any device in "
            "radio range can operate them. Set a bindkey on the device and "
            "reconfigure it here to seal both directions (PROTOCOL.md section 5)",
            entry.title,
            len(coordinator.declaration.offered),
            "y" if len(coordinator.declaration.offered) == 1 else "ies",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: BTHomeWritableConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


__all__ = ["DOMAIN", "async_setup_entry", "async_unload_entry"]

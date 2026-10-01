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
from homeassistant.helpers import entity_registry as er

from .const import (
    ALLOW_COUNTER_SYNC,
    CONF_BINDKEY,
    CONF_DECLARATION,
    CONF_MAX_CONNECTIONS,
    CONF_WRITE_COUNTER,
    COUNTER_EPOCH_SEED,
    DEFAULT_MAX_CONNECTIONS,
    DOMAIN,
)
from .coordinator import BTHomeWritableCoordinator
from .protocol import Declaration, entity_unique_id, event_unique_id

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


async def _migrate_unique_ids(
    hass: HomeAssistant, entry: BTHomeWritableConfigEntry, address: str
) -> None:
    """Carry entities across the unique-id change of D-069/D-078.

    The object ID joined the unique id so that an entry which changes type does
    not collide with what it used to be. Without a migration that silently
    orphans every entity already registered: the old row is never claimed again
    and shows as unavailable for ever, and the live entity takes a new
    `entity_id` with a `_2` on the end — which breaks every automation naming
    it. Found on the bench, not in the tests, because a fresh test registry has
    nothing to orphan.

        `<mac>-<entry>`                 -> `<mac>-e<entry>-<objid>`
        `<mac>-<entry>-<code>`  button  -> `<mac>-e<entry>-<objid>-v<code>`

    Which of the two an old id is cannot be told from its shape — `<mac>-1-1e`
    and `<mac>-1-01` look identical — so the *domain* decides: only the button
    platform ever carried a value. Guessing instead is what rewrote the live
    entity onto a stale one's identity and failed the whole config entry.

    The object ID comes from the stored declaration, so a device that has never
    been heard from is left alone and migrates the next time it is.
    """
    stored = Declaration.restore(entry.data.get(CONF_DECLARATION))
    if stored is None:
        return
    by_entry = {item.entry: item.object_id for item in stored.entries}
    registry = er.async_get(hass)

    @callback
    def _migrate(registry_entry: er.RegistryEntry) -> dict[str, str] | None:
        unique_id = registry_entry.unique_id
        if not unique_id.startswith(f"{address}-"):
            return None
        parts = unique_id[len(address) + 1 :].split("-")
        if not parts or not parts[0].isdigit():
            # Already migrated (those start with `e`), the resynchronise button,
            # or something else entirely.
            return None
        object_id = by_entry.get(int(parts[0]))
        if object_id is None:
            return None  # an entry this firmware no longer declares
        entry_number = int(parts[0])
        if registry_entry.domain == "button" and len(parts) == 2:
            new_unique_id = event_unique_id(
                address, entry_number, object_id, int(parts[1], 16)
            )
        elif registry_entry.domain != "button" and len(parts) == 1:
            new_unique_id = entity_unique_id(address, entry_number, object_id)
        else:
            return None
        if registry.async_get_entity_id(
            registry_entry.domain, registry_entry.platform, new_unique_id
        ):
            # Something already answers to the new identity, so this row is a
            # leftover from a layout this device no longer has. Migrating it
            # would collide and fail the whole setup; leaving it costs one
            # unavailable entity the user can delete.
            return None
        return {"new_unique_id": new_unique_id}

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


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

    @callback
    def _remember_declaration(declaration: Declaration) -> None:
        # So the controls exist at the next startup even if the device is asleep
        # or out of range. Core `bthome` restores its sensors from the entry for
        # the same reason: an entity that is missing breaks every automation that
        # names it, where an unavailable one merely waits.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_DECLARATION: declaration.stored()}
        )

    await _migrate_unique_ids(hass, entry, address)

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
        declaration=Declaration.restore(entry.data.get(CONF_DECLARATION)),
        on_declaration=_remember_declaration,
    )
    entry.runtime_data = coordinator

    if ALLOW_COUNTER_SYNC and bindkey is not None:
        # Before the first write rather than after it fails: a refused write is
        # silent (§4.2), so there is nothing to react to (D-075).
        entry.async_create_background_task(
            hass,
            coordinator.async_sync_write_counter(),
            name=f"{address} counter sync",
        )

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

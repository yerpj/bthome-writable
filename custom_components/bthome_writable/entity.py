"""Shared entity plumbing for BTHome Writable (PROTOCOL.md version 2).

Version 2 advertises no writable values, so there is nothing to confirm by
listening. An entity shows what it last wrote, or what the device reported when
read (§3.2); while a write is in flight it shows the value being written, and it
drops that value again if the write fails.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import BTHomeWritableCoordinator, WriteFailed
from .protocol import WritableEntry

_LOGGER = logging.getLogger(__name__)

LOGBOOK_ENTRY = "logbook_entry"
"""Home Assistant's logbook event.

Fired rather than calling `logbook.async_log_entry`, so the logbook stays an
optional consumer instead of a dependency in the manifest. A failed write is
exactly the event the logbook exists for, and a warning in the log is not
somewhere a user looks when a light did not come on (T4.1)."""


def _log_to_logbook(hass: HomeAssistant, entity_id: str | None, message: str) -> None:
    """Record one failed write beside the state change it undid."""
    if entity_id is None:
        return
    hass.bus.async_fire(
        LOGBOOK_ENTRY,
        {
            "name": "BTHome Writable",
            "message": message,
            "domain": DOMAIN,
            "entity_id": entity_id,
        },
    )


class BTHomeWritableEntity(Entity):
    """Base for every entity backed by a declared entry."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    _coalesce = True
    """Whether a newer value replaces a queued one. False for events: two presses
    are two presses."""

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, entry: WritableEntry
    ) -> None:
        self.coordinator = coordinator
        self._entry = entry.entry
        self._object_id = entry.object_id
        self._attr_unique_id = f"{coordinator.address}-{entry.entry}"
        self._attr_device_info = DeviceInfo(
            # Sharing the connection identity is what merges this device with
            # the sensors the core BTHome integration already created: one card
            # in the UI, not two.
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.name,
        )
        self._in_flight: bytes | None = None

    @property
    def entry_number(self) -> int:
        return self._entry

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def assumed_state(self) -> bool:
        """True unless the device reports its state (§3.1, §3.2).

        Home Assistant then keeps every control available -- both "on" and
        "off" -- because what it shows is what it last sent, not what it knows.
        """
        return not self.coordinator.reports_state

    @property
    def _value(self) -> bytes | None:
        """What the UI shows: a write in flight, else the last known value."""
        if self._in_flight is not None:
            return self._in_flight
        return self.coordinator.value_of(self._entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
        self.async_on_remove(
            self.coordinator.async_add_write_listener(self._write_finished)
        )

    async def async_apply(self, value: bytes) -> None:
        """Show the value at once and queue the write (§4.2)."""
        self._in_flight = value if self._coalesce else None
        self.async_write_ha_state()
        try:
            await self.coordinator.async_write(
                self._entry, value, coalesce=self._coalesce
            )
        except WriteFailed:
            self._in_flight = None
            self.async_write_ha_state()
            raise

    @callback
    def _write_finished(self, entries: set[int], error: Exception | None) -> None:
        """The queued write reached the device, or failed to."""
        if self._entry not in entries:
            return
        self._in_flight = None
        if error is not None:
            _LOGGER.warning(
                "%s: the command did not reach the device (%s)", self.entity_id, error
            )
            _log_to_logbook(
                self.hass,
                self.entity_id,
                f"the command did not reach the device ({error})",
            )
        self.async_write_ha_state()


__all__ = ["DOMAIN", "BTHomeWritableEntity"]

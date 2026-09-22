"""Shared entity plumbing for BTHome Writable (PROTOCOL.md version 2).

Version 2 advertises no writable values, so there is nothing to confirm by
listening. An entity shows what it last wrote, or what the device reported when
read (§3.2); while a write is in flight it shows the value being written, and it
drops that value again if the write fails.
"""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import BTHomeWritableCoordinator
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
        # The object ID is part of the identity, not just the entry number:
        # entry 1 as a light and entry 1 as a switch are different controls, and
        # a firmware change can turn one into the other. Without it the new
        # entity collides with the old one and neither works (found in review).
        self._attr_unique_id = (
            f"{coordinator.address}-{entry.entry}-{entry.object_id:02x}"
        )
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
        """Show the value at once, then wait for the write to land (§4.2).

        The action returns when the device has acknowledged the write and raises
        when it has not, which is Home Assistant's rule for an action rather
        than this project's invention: `action-exceptions` (Silver) asks an
        integration to raise `HomeAssistantError` so the failure reaches the
        interface, and every well-kept integration on a radio does -- ZHA,
        Z-Wave JS, SwitchBot (D-064).

        It costs the caller the connection time, seconds rather than
        milliseconds. That is the price of an honest answer, and it is the
        ecosystem's price too: a Z-Wave action routinely blocks longer.
        """
        self._in_flight = value if self._coalesce else None
        self.async_write_ha_state()
        try:
            await self.coordinator.async_write(
                self._entry, value, coalesce=self._coalesce
            )
        except Exception as caught:
            self._in_flight = None
            self.async_write_ha_state()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={
                    "name": self.name or self.entity_id or "",
                    "error": str(caught),
                },
            ) from caught

    @callback
    def _write_finished(self, entries: set[int], error: Exception | None) -> None:
        """The queued write reached the device, or failed to."""
        if self._entry not in entries:
            return
        self._in_flight = None
        if error is not None:
            # Also raised to whoever called the action. Kept here as well
            # because an automation's failure is read later, in the logbook,
            # by someone who never saw the error the action raised.
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

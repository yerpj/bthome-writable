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
from .protocol import WritableEntry, entity_unique_id

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
        self._attr_unique_id = entity_unique_id(
            coordinator.address, entry.entry, entry.object_id
        )
        self._attr_device_info = DeviceInfo(
            # Sharing the connection identity is what merges this device with
            # the sensors the core BTHome integration already created: one card
            # in the UI, not two.
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            # `default_name`, not `name`: both integrations contribute to the
            # same device, and asserting a name means the last one to write
            # wins. Core BTHome calls this device "Puck.js c1c3 C1C3" and we
            # called it "Puck.js c1c3", so the card's title flickered between
            # them depending on load order -- reported by Gordon (D-089).
            #
            # `default_name` is used only when the device has no name yet,
            # which leaves core BTHome's in place and still covers the one
            # case it cannot: a device that declares writable entries and
            # advertises no sensors at all, so core BTHome never names it.
            default_name=coordinator.name,
        )
        self._in_flight: bytes | None = None
        self._writes_in_flight = 0
        """How many of this entity's writes have not finished.

        The value shown while a command is in flight belongs to the *newest*
        one, so it may only be dropped once nothing of ours is still out there.
        Counting rather than clearing on the first completion is the whole
        of D-094: a slow write finishing after a newer one was issued used to
        put the older value back on screen (@enaon, and reproduced here)."""

    @property
    def entry_number(self) -> int:
        return self._entry

    @property
    def available(self) -> bool:
        if not self.coordinator.still_declared(self._entry, self._object_id):
            # The device no longer declares this entry as this object. The
            # control is a leftover from an earlier layout and must not look
            # operable -- pressing it would write to whatever took its place.
            return False
        # `sleepy_device or ...` is core `bthome`'s own line
        # (binary_sensor.py, sensor.py): a trigger-based device is not absent
        # between its events, and marking it unavailable would make a control
        # that works look broken for however long the device stays quiet.
        return self.coordinator.sleepy_device or self.coordinator.available

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
        if not self.coordinator.still_declared(self._entry, self._object_id):
            # A leftover from an earlier layout. Being unavailable is not enough
            # on its own: an automation naming this entity still reaches here,
            # and the write would be encoded for whatever object took the
            # entry's place -- malformed, acknowledged, and reported as a
            # success (D-083).
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={
                    "name": self.name or self.entity_id or "",
                    "error": (
                        f"the device no longer declares entry {self._entry} as "
                        f"object 0x{self._object_id:02X}; this control belongs "
                        "to a layout the device has replaced"
                    ),
                },
            )

        self._in_flight = value if self._coalesce else None
        self._writes_in_flight += 1
        self.async_write_ha_state()
        try:
            await self.coordinator.async_write(
                self._entry, value, coalesce=self._coalesce
            )
        except Exception as caught:
            self._settled()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={
                    "name": self.name or self.entity_id or "",
                    "error": str(caught),
                },
            ) from caught
        else:
            self._settled()

    @callback
    def _settled(self) -> None:
        """One of this entity's writes has finished, successfully or not.

        The shown value is released only when the last one has: until then it
        is the value of the newest command, which is still the honest thing to
        show (D-094).
        """
        self._writes_in_flight = max(0, self._writes_in_flight - 1)
        if self._writes_in_flight == 0:
            self._in_flight = None
        self.async_write_ha_state()

    @callback
    def _write_finished(self, entries: set[int], error: Exception | None) -> None:
        """Say that a write failed, for the benefit of whoever reads later.

        It no longer touches `_in_flight`. This fires for *any* write to this
        entry, including one issued before the command now in flight, and
        releasing the shown value on someone else's completion is what put a
        stale value back on screen (D-094).
        """
        if self._entry not in entries:
            return
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

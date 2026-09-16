"""Shared entity plumbing for BTHome Writable.

The state model of §6 lives here rather than in each platform: write
optimistically, wait for the device's next advertisement to confirm, revert if
it never comes. Every read-write entity gets it; write-only entities (§3) are
stateless and do not use it.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import BTHomeWritableCoordinator, WriteFailed
from .protocol import WritableObject

_LOGGER = logging.getLogger(__name__)

LOGBOOK_ENTRY = "logbook_entry"
"""Home Assistant's logbook event.

Fired rather than calling `logbook.async_log_entry`, so the logbook stays an
optional consumer instead of a dependency in the manifest: a user who has
removed it still gets a working integration, and one who has it sees why a
control snapped back.

A failed write is exactly the event the logbook exists for. It is invisible
otherwise -- the entity reverts, which from the outside is indistinguishable
from never having been pressed -- and a warning in the log is not somewhere a
user looks when a light did not come on (T4.1)."""


def _log_to_logbook(hass, entity_id: str, message: str) -> None:
    """Record one failed write beside the state change it undid."""
    if entity_id is None:
        # Before the entity is registered there is nothing to attach to, and a
        # logbook row with no entity is noise rather than evidence.
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
    """Base for every entity backed by a writable BTHome object."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    _confirms = True
    """Whether §6's confirm/revert applies to this entity.

    False for controls whose object cannot report back what was written — a
    button's resting advertisement is "none" whatever was pressed. Write-only
    objects are detected from the payload instead and do not need to set this.
    """

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, obj: WritableObject
    ) -> None:
        self.coordinator = coordinator
        self._position = obj.position
        self._object_id = obj.object_id
        # A write-only object never advertises what it was told, so the
        # confirm/revert model has nothing to work with. Section 3 does not
        # merely permit skipping it, it forbids applying it: the window would
        # always expire and the entity would drop back to the placeholder.
        self._write_only = obj.write_only

        self._attr_unique_id = f"{coordinator.address}-{obj.position}"
        self._attr_device_info = DeviceInfo(
            # Sharing the connection identity is what merges this device with
            # the sensors the core BTHome integration already created: one card
            # in the UI, not two. Deliberately no `identifiers` of our own,
            # which would create a second device instead.
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.name,
        )

        self._optimistic: bytes | None = None
        self._confirm_task: asyncio.Task[None] | None = None

    @property
    def position(self) -> int:
        return self._position

    @property
    def available(self) -> bool:
        return self.coordinator.available and self._advertised_value is not None

    @property
    def _advertised_value(self) -> bytes | None:
        return self.coordinator.value_at(self._position)

    @property
    def _effective_value(self) -> bytes | None:
        """What the UI shows: the optimistic value until it is confirmed."""
        if self._optimistic is not None:
            return self._optimistic
        return self._advertised_value

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.async_add_listener(self._advertised))
        self.async_on_remove(
            self.coordinator.async_add_write_listener(self._write_finished)
        )

    @callback
    def _advertised(self) -> None:
        """A new advertisement arrived: confirm or keep waiting."""
        if self._optimistic is not None and self._advertised_value == self._optimistic:
            self._optimistic = None
            self._cancel_confirmation()
            self.coordinator.note_confirmed()
        self.async_write_ha_state()

    async def async_apply(self, value: bytes) -> None:
        """Show the new value optimistically and queue the write (§6).

        The confirmation window is *not* started here. It opens in
        `_write_finished`, once the write has actually reached the device —
        see the note on `async_add_write_listener`.
        """
        self._optimistic = value
        self.async_write_ha_state()
        self._cancel_confirmation()

        try:
            await self.coordinator.async_write(self._position, value)
        except WriteFailed:
            self._revert()
            raise

    @callback
    def _write_finished(self, positions: set[int], error: Exception | None) -> None:
        """The queued write has been delivered, or has failed."""
        if self._position not in positions or self._optimistic is None:
            return

        if error is not None:
            _LOGGER.warning(
                "%s: the write did not reach the device (%s); showing its last "
                "advertised state",
                self.entity_id,
                error,
            )
            _log_to_logbook(
                self.hass,
                self.entity_id,
                f"the command did not reach the device ({error}); "
                "reverted to its last advertised state",
            )
            self._revert()
            return

        self._cancel_confirmation()
        if self._write_only or not self._confirms:
            # Delivered is as much as will ever be known (§3). The optimistic
            # value stays, because it is the only account of what was sent.
            return
        self._confirm_task = self.hass.async_create_task(self._await_confirmation())

    async def _await_confirmation(self) -> None:
        """Wait out the confirmation window, then revert if nothing arrived.

        Two conditions, not one: the window must elapse *and* the device must
        actually have been heard from. A host with a single Bluetooth adapter
        cannot scan while it is connected and takes seconds to resume, so a
        purely time-based window can expire having heard nothing at all —
        reverting on no evidence (D-011). The ceiling stops that from becoming
        an indefinite wait when a device really has gone away.
        """
        heard_before = self.coordinator.advertisements
        waited = 0.0
        step = 0.25

        while waited < self.coordinator.confirm_ceiling:
            await asyncio.sleep(step)
            waited += step
            if self._optimistic is None:
                return

            heard = self.coordinator.advertisements - heard_before
            enough_time = waited >= self.coordinator.confirm_window
            enough_evidence = heard >= self.coordinator.confirm_advertisements
            if enough_time and enough_evidence:
                break
        else:
            heard = self.coordinator.advertisements - heard_before

        _LOGGER.warning(
            "%s: the device did not advertise the written value within %.1f s "
            "(%d advertisement(s) heard since the write); reverting to its last "
            "advertised state",
            self.entity_id,
            waited,
            heard,
        )
        _log_to_logbook(
            self.hass,
            self.entity_id,
            f"the device did not confirm the command within {waited:.1f} s "
            f"({heard} advertisement(s) heard); reverted to its last "
            "advertised state",
        )
        self._revert()

        if heard >= self.coordinator.confirm_advertisements:
            # The device was heard from and did not act. One explanation is that
            # it rejected the write; the other is that the write never really
            # reached the characteristic, because the host's cached GATT table
            # is stale — which for an Espruino device is routine, since its
            # table is rebuilt every time code is uploaded. A write through a
            # stale cache reports success and does nothing, so it looks exactly
            # like this. Forget the table so the next write rediscovers it.
            self.hass.async_create_task(self.coordinator.async_clear_service_cache())

            # On an encrypted device there is a third explanation, and it is the
            # likeliest: the device has accepted a higher counter than this
            # receiver knows about, so every write reads as a replay and is
            # refused -- silently, because §6 gives a device no way to complain.
            # From here it is indistinguishable from the other two, which is
            # exactly why §5.2 asks a receiver to resynchronise rather than wait
            # for a diagnosis that will never arrive.
            self.coordinator.note_unconfirmed()

    @callback
    def _revert(self) -> None:
        self._optimistic = None
        self.async_write_ha_state()

    @callback
    def _cancel_confirmation(self) -> None:
        if self._confirm_task is not None and not self._confirm_task.done():
            self._confirm_task.cancel()
        self._confirm_task = None

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_confirmation()


__all__ = ["DOMAIN", "BTHomeWritableEntity"]

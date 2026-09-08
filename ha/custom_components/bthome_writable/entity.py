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


class BTHomeWritableEntity(Entity):
    """Base for every entity backed by a writable BTHome object."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, obj: WritableObject
    ) -> None:
        self.coordinator = coordinator
        self._position = obj.position
        self._object_id = obj.object_id

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
            self._revert()
            return

        self._cancel_confirmation()
        self._confirm_task = self.hass.async_create_task(self._await_confirmation())

    async def _await_confirmation(self) -> None:
        await asyncio.sleep(self.coordinator.confirm_window)
        if self._optimistic is None:
            return
        _LOGGER.warning(
            "%s: the device did not advertise the written value within %.1f s; "
            "reverting to its last advertised state",
            self.entity_id,
            self.coordinator.confirm_window,
        )
        self._revert()

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

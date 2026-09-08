"""Switch platform: BTHome boolean objects declared writable.

The MVP's only platform (T1.2). Lights, numbers, text and buttons follow in
T2.1, once the full object-to-platform table is written against BTHome's object
list.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import WritableObject

# BTHome boolean objects worth exposing as a switch, with the name to show.
# Deliberately short: `door` or `motion` stay sensors even if a device declares
# them writable, and offering them as switches would misrepresent the device.
# T2.1 replaces this with the full object-to-platform table.
SWITCHABLE: dict[int, str] = {
    0x0F: "Generic",
    0x10: "Power",
    0x1E: "Light",
    0x1F: "Lock",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a switch for every writable boolean object."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _sync() -> None:
        """Add entities for objects not seen before.

        Runs on every advertisement rather than once, because the declaration
        is only known once a packet has been parsed — and a device may start
        advertising a longer declaration packet after a firmware update.
        """
        if coordinator.declaration is None:
            return
        new = [
            BTHomeWritableSwitch(coordinator, obj)
            for obj in coordinator.declaration.objects
            if obj.object_id in SWITCHABLE
            and not obj.write_only
            and obj.position not in known
        ]
        if not new:
            return
        known.update(entity.position for entity in new)
        async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class BTHomeWritableSwitch(BTHomeWritableEntity, SwitchEntity):
    """One writable boolean object."""

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, obj: WritableObject
    ) -> None:
        super().__init__(coordinator, obj)
        name = SWITCHABLE.get(obj.object_id, "Switch")
        suffix = _instance_suffix(coordinator, obj)
        self._attr_name = name if suffix is None else f"{name} {suffix}"

    @property
    def is_on(self) -> bool | None:
        value = self._effective_value
        if value is None:
            return None
        return value[0] != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_apply(b"\x01")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_apply(b"\x00")


def _instance_suffix(
    coordinator: BTHomeWritableCoordinator, obj: WritableObject
) -> int | None:
    """1-based index among writable objects of the same ID, or None if unique.

    Mirrors how `bthome-ble` names duplicate sensors (`light_1`, `light_2`), so
    a device's writable switches and its read-only sensors are numbered the same
    way in the UI rather than by two unrelated schemes.
    """
    if coordinator.declaration is None:
        return None
    same = [
        other
        for other in coordinator.declaration.objects
        if other.object_id == obj.object_id
    ]
    if len(same) < 2:
        return None
    return same.index(obj) + 1

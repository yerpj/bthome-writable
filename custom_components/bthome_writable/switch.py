"""Switch platform: declared entries of a BTHome binary type.

Every binary type, not a chosen few: a device does not declare an object
writable by accident, and one declaring a writable `garage_door` has a garage
door. See spec/PLATFORMS.md.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import WritableEntry


def is_kind(kind: str) -> Callable[[WritableEntry], bool]:
    def check(entry: WritableEntry) -> bool:
        described = entry.kind
        return entry.offered and described is not None and described.kind == kind

    return check


def add_entities_as_declared(
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
    wanted: Callable[[WritableEntry], bool],
    build: Callable[[BTHomeWritableCoordinator, WritableEntry], list[Any]],
) -> None:
    """Add entities for entries not seen before, on every advertisement.

    Not once at setup: the declaration is only known once a packet has been
    parsed, and new firmware may declare more entries.
    """
    coordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()

    @callback
    def _sync() -> None:
        if coordinator.declaration is None:
            return
        new: list[Any] = []
        for declared in coordinator.declaration.entries:
            key = (declared.entry, declared.object_id)
            if key in known or not wanted(declared):
                continue
            known.add(key)
            new.extend(build(coordinator, declared))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


def instance_label(
    coordinator: BTHomeWritableCoordinator, entry: WritableEntry, name: str
) -> str:
    """`Light`, or `Light 2` when several entries share the type.

    Numbered in entry order, the way `bthome-ble` numbers duplicate sensors, so
    the controls and the sensors of a device follow one convention.
    """
    assert coordinator.declaration is not None
    same = [
        e for e in coordinator.declaration.entries if e.object_id == entry.object_id
    ]
    if len(same) < 2:
        return name
    return f"{name} {same.index(entry) + 1}"


def type_label(entry: WritableEntry, fallback: str) -> str:
    """The object's BTHome class, as a label: `garage_door` -> Garage door."""
    kind = entry.kind
    if kind is None or not kind.device_class:
        return fallback
    return kind.device_class.replace("_", " ").capitalize()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a switch for every declared binary entry."""
    add_entities_as_declared(
        entry,
        async_add_entities,
        is_kind("binary"),
        lambda coordinator, declared: [BTHomeWritableSwitch(coordinator, declared)],
    )


class BTHomeWritableSwitch(BTHomeWritableEntity, SwitchEntity):
    """One declared binary entry."""

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, entry: WritableEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = instance_label(
            coordinator, entry, type_label(entry, "Switch")
        )

    @property
    def is_on(self) -> bool | None:
        value = self._value
        return None if value is None else value[0] != 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_apply(b"\x01")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_apply(b"\x00")

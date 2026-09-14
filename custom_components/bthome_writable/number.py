"""Number platform: BTHome numeric objects declared writable.

A dimmer level, a setpoint, a target humidity. Home Assistant's `number` entity
and its `number.set_value` service are what this needs, so nothing new is
invented here either.

**The bounds are the encoding's, not the device's.** They are derived from the
object's width, signedness and factor, all read from `bthome-ble` — a 2-byte
unsigned object with a factor of 0.01 offers 0 … 655.35 in steps of 0.01. BTHome
gives a device no way to narrow that, so a dimmer that physically stops at 100
still presents a slider reaching 655.35. The receiver cannot know better; the
device is entitled to reject the write, and §4.2 has it reject the whole write
rather than clamp. See spec/PLATFORMS.md.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import WritableObject, decode_scaled, describe, encode_scaled


def numeric(obj: WritableObject) -> bool:
    kind = describe(obj.object_id)
    return kind is not None and kind.kind == "numeric"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a number for every writable numeric object."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _sync() -> None:
        if coordinator.declaration is None:
            return
        new = [
            BTHomeWritableNumber(coordinator, obj)
            for obj in coordinator.declaration.objects
            if numeric(obj) and obj.position not in known
        ]
        if not new:
            return
        known.update(entity.position for entity in new)
        async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class BTHomeWritableNumber(BTHomeWritableEntity, NumberEntity):
    """One writable numeric object."""

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, obj: WritableObject
    ) -> None:
        super().__init__(coordinator, obj)
        kind = describe(obj.object_id)
        assert kind is not None  # numeric() was true, so the id is known
        self._kind = kind

        label = (kind.device_class or "value").replace("_", " ").capitalize()
        self._attr_name = label
        self._attr_native_step = kind.step
        self._attr_native_min_value = kind.minimum
        self._attr_native_max_value = kind.maximum
        self._attr_native_unit_of_measurement = kind.unit

    @property
    def native_value(self) -> float | None:
        value = self._effective_value
        if value is None or len(value) != self._kind.length:
            return None
        return decode_scaled(value, self._kind)

    async def async_set_native_value(self, value: float) -> None:
        await self.async_apply(encode_scaled(value, self._kind))

"""Number platform: declared entries of a BTHome numeric type.

A dimmer level, a setpoint, a thermostat target. **The bounds are the
encoding's, not the device's**: derived from the object's width, signedness and
factor, all read from `bthome-ble`. BTHome gives a device no way to narrow them,
so the device is entitled to reject a value it cannot take (§4.2). See
spec/PLATFORMS.md.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import WritableEntry, decode_scaled, encode_scaled
from .switch import add_entities_as_declared, instance_label, is_kind, type_label


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a number for every declared numeric entry."""
    add_entities_as_declared(
        entry,
        async_add_entities,
        is_kind("numeric"),
        lambda coordinator, declared: [BTHomeWritableNumber(coordinator, declared)],
    )


class BTHomeWritableNumber(BTHomeWritableEntity, NumberEntity):
    """One declared numeric entry."""

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, entry: WritableEntry
    ) -> None:
        super().__init__(coordinator, entry)
        kind = entry.kind
        assert kind is not None  # is_kind("numeric") held
        self._kind = kind
        self._attr_name = instance_label(coordinator, entry, type_label(entry, "Value"))
        self._attr_native_step = kind.step
        self._attr_native_min_value = kind.minimum
        self._attr_native_max_value = kind.maximum
        self._attr_native_unit_of_measurement = kind.unit

    @property
    def native_value(self) -> float | None:
        value = self._value
        if value is None or len(value) != self._kind.length:
            return None
        return decode_scaled(value, self._kind)

    async def async_set_native_value(self, value: float) -> None:
        await self.async_apply(encode_scaled(value, self._kind))

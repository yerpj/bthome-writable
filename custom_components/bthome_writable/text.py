"""Text platform: declared entries of BTHome's text type.

Home Assistant already has the entity this needs — `text`, with its
`text.set_value` service. The state shown is what Home Assistant last sent, or
what the device reported when read (§3.2); after a restart, on a device that
reports nothing, it is unknown until something is sent, which is the honest
reading.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import WritableEntry
from .switch import add_entities_as_declared, instance_label, is_kind

# A BTHome length byte stops at 255, and Home Assistant's text entity caps there
# too. The real ceiling is lower and not knowable from here: the MTU and the
# device's own maximum write length (decisions.md D-017, D-035). A write beyond
# what the link allows fails and is reported.
MAX_LENGTH = 255


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a text entity for every declared text entry."""
    add_entities_as_declared(
        entry,
        async_add_entities,
        is_kind("string"),
        lambda coordinator, declared: [BTHomeWritableText(coordinator, declared)],
    )


class BTHomeWritableText(BTHomeWritableEntity, TextEntity):
    """One declared text entry."""

    _attr_native_max = MAX_LENGTH
    _attr_native_min = 0

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, entry: WritableEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_name = instance_label(coordinator, entry, "Text")

    @property
    def native_value(self) -> str | None:
        value = self._value
        if value is None or len(value) < 1:
            return None
        return value[1:].decode("utf-8", errors="replace")

    async def async_set_value(self, value: str) -> None:
        body = value.encode("utf-8")
        if len(body) > MAX_LENGTH:
            raise ValueError(
                f"{len(body)} bytes of text; a BTHome length byte stops at {MAX_LENGTH}"
            )
        # BTHome's own encoding keeps the length byte (§4.2, D-048).
        await self.async_apply(bytes([len(body)]) + body)

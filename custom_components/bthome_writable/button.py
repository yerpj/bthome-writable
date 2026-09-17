"""Button platform: declared entries of a BTHome event type.

A writable event means "perform this now" (§4.2). Home Assistant's `button` is
exactly that, so an event entry becomes one button **per value its vocabulary
defines** — press, long press, on, off, toggle… — read from `bthome-ble` rather
than listed here, so none is unreachable.

Version 2 makes `0x3B command` safe to offer: a write touches only its own
entry, so no other control on the device can send it an `off` it did not ask for
(D-048). Buttons have no state, and their writes are never coalesced — two
presses are two presses.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import WritableEntry, event_values
from .switch import add_entities_as_declared, instance_label, is_kind

BUTTON, COMMAND, DIMMER = 0x3A, 0x3B, 0x3C

# One step per press: a dimmer's second byte, and the argument of a command's
# step up and step down. A device wanting more can be pressed again.
STEPS = 1
STEPPED_COMMANDS = frozenset({0x03, 0x04})


def event_payload(object_id: int, code: int) -> bytes:
    """The value bytes of one event, in BTHome's encoding for its object."""
    if object_id == COMMAND:
        # <argument length, low 5 bits> <opcode> <arguments>
        if code in STEPPED_COMMANDS:
            return bytes([1, code, STEPS])
        return bytes([0, code])
    if object_id == DIMMER:
        return bytes([code, STEPS])
    return bytes([code])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one button per value of every declared event entry."""

    def build(
        coordinator: BTHomeWritableCoordinator, declared: WritableEntry
    ) -> list[BTHomeWritableButton]:
        return [
            BTHomeWritableButton(coordinator, declared, code, name)
            for code, name in (event_values(declared.object_id) or {}).items()
        ]

    add_entities_as_declared(entry, async_add_entities, is_kind("event"), build)


class BTHomeWritableButton(BTHomeWritableEntity, ButtonEntity):
    """One value of one declared event entry."""

    _coalesce = False

    def __init__(
        self,
        coordinator: BTHomeWritableCoordinator,
        entry: WritableEntry,
        code: int,
        name: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._code = code
        self._attr_name = instance_label(
            coordinator, entry, name.replace("_", " ").capitalize()
        )
        # Several buttons share one entry, so the entry alone is not unique.
        self._attr_unique_id = f"{coordinator.address}-{entry.entry}-{code:02x}"

    async def async_press(self) -> None:
        await self.async_apply(event_payload(self._object_id, self._code))

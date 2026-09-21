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
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
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

    # Only for a keyed device: a plain one has no write counter to be out of
    # step with, and an unexplained button is worse than no button.
    coordinator = entry.runtime_data
    if coordinator.bindkey is not None:
        async_add_entities([BTHomeWritableResyncButton(coordinator)])


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


class BTHomeWritableResyncButton(ButtonEntity):
    """Move the write counter past whatever the device has already accepted.

    §5.3 asks a receiver to offer this, and until now this one did not. A device
    remembers the highest write counter it has accepted and refuses anything
    below it; a receiver whose counter is behind therefore has every write
    refused, and refused invisibly, because §3 acknowledges a write before
    validating it. Seeding a new entry's counter from the clock removes the
    ordinary way into that state (D-063), but not every way: a device restored
    from a backup of its own flash, or one given a deliberately high counter,
    can still be ahead. This is the way out that needs no reflashing.

    Safe to press at any time: a forward jump is what §5.3 requires a device to
    accept, and the counter is 32 bits wide.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = "Resynchronise write counter"

    def __init__(self, coordinator: BTHomeWritableCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}-resync-write-counter"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.name,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.available

    async def async_press(self) -> None:
        self.coordinator.resynchronise()

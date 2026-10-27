"""Button platform: declared entries of a BTHome event type.

A writable event means "perform this now" (§4.2). Home Assistant's `button` is
exactly that, so an event entry becomes one button **per value its vocabulary
defines** — press, long press, on, off, toggle… — read from `bthome-ble` rather
than listed here, so none is unreachable.

`0x3B command` is **not** among them: §2.1 excludes it, because BTHome gives it
to a device announcing a command of its own and a writable one would face both
ways (D-151). It was offered until 2026-10-27, which is what `STEPPED_COMMANDS`
and a framing of its own used to be here for. Buttons have no state, and their
writes are never coalesced — two presses are two presses.
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
from .protocol import WritableEntry, event_unique_id, event_values
from .switch import add_entities_as_declared, instance_label, is_kind

BUTTON, DIMMER = 0x3A, 0x3C

# One step per press, which is a dimmer's second byte. A device wanting more can
# be pressed again.
STEPS = 1


def event_payload(object_id: int, code: int) -> bytes:
    """The value bytes of one event, in BTHome's encoding for its object."""
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
        self._attr_unique_id = event_unique_id(
            coordinator.address, entry.entry, entry.object_id, code
        )

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

    @property
    def available(self) -> bool:
        # `sleepy_device or ...` is core `bthome`'s own line
        # (binary_sensor.py, sensor.py): a trigger-based device is not absent
        # between its events, and marking it unavailable would make a control
        # that works look broken for however long the device stays quiet.
        return self.coordinator.sleepy_device or self.coordinator.available

    async def async_press(self) -> None:
        self.coordinator.resynchronise()

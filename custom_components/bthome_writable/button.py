"""Button platform: BTHome event objects declared writable.

An event object is the one class that is stateless by construction — its resting
value is "none", and writing a value makes something happen once. Home
Assistant's `button` is exactly that, so a writable event object becomes one
button **per value its vocabulary defines**: press, double press, long press,
and so on, read from `bthome-ble` rather than listed here.

One button per value rather than one per object, for the same reason the switch
platform stopped curating binary classes: the vocabulary is BTHome's, and
picking a favourite from it would make the rest unreachable. A device with a
writable button object gets seven buttons, each named after what it does and
each usable in an automation without a template.

**Buttons do not confirm**, like text and for the same reason: the device's
resting advertisement is "none" whatever was pressed, so §6 has nothing to
compare. Unlike text there is also nothing to show — a button has no state.

`0x3B command` is **not** offered. Its vocabulary has no "none": `0x00` means
`off`. §4.3 assumes every event object has a no-op, and this one does not, so a
write touching any other object on the same device would have to send it a real
command. Written up in spec/for-gordon.md; until that is settled, offering a
control for it would be offering to surprise people.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import EVENT_NO_OP, WritableObject, describe, event_values

# A dimmer's second byte is how many steps it turned. A button press is one
# step; a device wanting more can be driven by pressing again.
DIMMER_STEPS = 1


def pressable(obj: WritableObject) -> bool:
    """Event objects that have a "none" value, and so can be left alone."""
    kind = describe(obj.object_id)
    return kind is not None and kind.kind == "event" and obj.object_id in EVENT_NO_OP


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one button per value of every writable event object."""
    coordinator = entry.runtime_data
    known: set[tuple[int, int]] = set()

    @callback
    def _sync() -> None:
        if coordinator.declaration is None:
            return
        new: list[BTHomeWritableButton] = []
        for obj in coordinator.declaration.objects:
            if not pressable(obj):
                continue
            for code, name in (event_values(obj.object_id) or {}).items():
                if (obj.position, code) in known:
                    continue
                known.add((obj.position, code))
                new.append(BTHomeWritableButton(coordinator, obj, code, name))
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class BTHomeWritableButton(BTHomeWritableEntity, ButtonEntity):
    """One value of one writable event object."""

    _confirms = False

    def __init__(
        self,
        coordinator: BTHomeWritableCoordinator,
        obj: WritableObject,
        code: int,
        name: str,
    ) -> None:
        super().__init__(coordinator, obj)
        self._code = code
        kind = describe(obj.object_id)
        self._length = kind.length if kind else 1
        self._attr_name = name.replace("_", " ").capitalize()
        # Several buttons share one position, so the position alone is not
        # unique the way it is for every other platform.
        self._attr_unique_id = f"{coordinator.address}-{obj.position}-{code:02x}"

    async def async_press(self) -> None:
        value = bytearray(self._length)
        value[0] = self._code
        if self._length > 1:
            # The dimmer's step count. Only its first byte is the direction.
            value[1] = DIMMER_STEPS
        await self.async_apply(bytes(value))

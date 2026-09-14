"""Text platform: BTHome text objects declared writable.

Home Assistant already has the entity this needs — `text`, with its
`text.set_value` service — so nothing here invents a mechanism. A writable
BTHome text object becomes a `text` entity, and setting it sends one write.

**These entities do not confirm.** A text object is write-only in practice: it
is advertised as a zero-length placeholder and never as content (PROTOCOL.md
§3), both because a screen's worth of text does not fit in an advertising packet
and because its contents are not necessarily public. So the state shown is *what
Home Assistant last sent*, not what the device is displaying — the two agree
unless a write was lost, and nothing will say if one was. §3 requires the
confirm/revert model to be skipped here rather than merely allowing it.

The state is therefore unknown until something is sent, including after a
restart. That is the honest reading: Home Assistant does not know what is on the
screen, and restoring a remembered value would assert something it cannot check.
"""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BTHomeWritableConfigEntry
from .coordinator import BTHomeWritableCoordinator
from .entity import BTHomeWritableEntity
from .protocol import WritableObject

# `bthome-ble`'s format name for a length-prefixed string, which is what BTHome
# object 0x53 decodes to. `raw` is variable-length too but carries bytes rather
# than text, and has no business in a text box.
TEXT_FORMAT = "string"

# A BTHome length byte stops at 255, and Home Assistant's own text entity caps
# there too. The real ceiling is lower and not knowable from here: it is the
# smaller of the negotiated MTU minus its framing and whatever the device set
# as its own maximum write length -- 48 characters on one board measured, 126 on
# another (decisions.md D-017, D-035). A write beyond what the link allows fails
# and is reported; it cannot be prevented here without guessing.
MAX_LENGTH = 255


def writable_text(obj: WritableObject) -> bool:
    return obj.data_format == TEXT_FORMAT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BTHomeWritableConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a text entity for every writable text object."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _sync() -> None:
        """Add entities for objects not seen before.

        Runs on every advertisement rather than once, for the same reason as the
        switch platform: the declaration is only known once a packet has been
        parsed, and a device may start advertising a longer one after a firmware
        update.
        """
        if coordinator.declaration is None:
            return
        new = [
            BTHomeWritableText(coordinator, obj)
            for obj in coordinator.declaration.objects
            if writable_text(obj) and obj.position not in known
        ]
        if not new:
            return
        known.update(entity.position for entity in new)
        async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


class BTHomeWritableText(BTHomeWritableEntity, TextEntity):
    """One writable text object."""

    _attr_native_max = MAX_LENGTH
    _attr_native_min = 0

    def __init__(
        self, coordinator: BTHomeWritableCoordinator, obj: WritableObject
    ) -> None:
        super().__init__(coordinator, obj)
        self._attr_name = "Text"

    @property
    def native_value(self) -> str | None:
        """What was last sent, or None if nothing has been.

        Read out of the base class's optimistic value rather than kept
        separately, so that a write which never reached the device takes the
        text down with it: `_revert()` clears that value, and a second copy
        would keep asserting a delivery that did not happen.

        Never what the device is showing. There is no way to ask it.
        """
        if self._optimistic is not None:
            return _decode(self._optimistic)
        if self._write_only:
            # The placeholder carries no information; "" would be a claim.
            return None
        advertised = self._advertised_value
        return None if advertised is None else _decode(advertised)

    async def async_set_value(self, value: str) -> None:
        body = value.encode("utf-8")
        if len(body) > MAX_LENGTH:
            raise ValueError(
                f"{len(body)} bytes of text; a BTHome length byte stops at {MAX_LENGTH}"
            )
        # The value of a variable-length object carries its own length byte, so
        # that compose_write can concatenate it unchanged (§4.2).
        await self.async_apply(bytes([len(body)]) + body)


def _decode(value: bytes) -> str | None:
    """Text out of a variable-length object's value: length byte, then bytes."""
    if len(value) < 1:
        return None
    return value[1:].decode("utf-8", errors="replace")

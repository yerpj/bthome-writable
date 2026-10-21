"""D-116: the read path and a cached GATT table that no longer fits the device.

Reported by @enaon on espruino#8024 and reproduced on the bench:

    CD:F5:77:3A:B2:16: entry 2: read object 0x09, expected 0x1E

Home Assistant read one characteristic and credited the value to another. An
Espruino device rebuilds its GATT table every time code is uploaded to it, so
a device can change its characteristic layout while the list of object IDs it
declares in its advertising stays the same -- and the layout change is the only
thing that used to drop the cache. Everything else about the read then works:
the handles exist, a sealed read authenticates, because a read's nonce binds
the MAC, the service, the direction and the counter, never the entry.

The object-ID check was therefore the only thing between a stale handle and a
wrong value, and all it did was drop the value. The entry stayed stale, the
table stayed wrong, and on a value nobody writes again that is for ever.

The other half is the entry that is declared and *absent* from the cached
table: skipped without a word, and counted as a successful read.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.bthome_writable.coordinator import BTHomeWritableCoordinator
from custom_components.bthome_writable.protocol import Declaration

from .conftest import UUID_TEMPLATE

ADDRESS = "A4:C1:38:8E:1F:2B"

LIGHT, COUNT = 0x1E, 0x09
"""@enaon's two: a light, and the count his dimmer rides on."""


def coordinator(hass: HomeAssistant, layout: list[int]) -> BTHomeWritableCoordinator:
    """A plain device, declaring `layout`, already known to the integration."""
    device = BTHomeWritableCoordinator(hass, ADDRESS)
    device.declaration = Declaration.restore({"layout": layout, "settings_revision": 3})
    return device


async def test_a_read_that_answers_another_entrys_object_is_read_again(
    hass: HomeAssistant, gatt
) -> None:
    """The reported fault, and the fix: drop the table, rediscover, read."""
    device = coordinator(hass, [LIGHT, COUNT])
    # The table Home Assistant holds is one upload old: entry 1's handle now
    # serves the count. The read succeeds; it is simply not the right entry.
    gatt.declare(2, readable={1: bytes.fromhex("0905"), 2: bytes.fromhex("0905")})

    async def reveal() -> None:
        """What dropping a stale table does: the next look sees the truth."""
        gatt.cache_cleared += 1
        gatt.readable[UUID_TEMPLATE.format(1)] = bytes.fromhex("1E01")

    gatt.clear_cache = reveal

    assert await device.async_read_all() is True
    assert gatt.cache_cleared == 1, "dropped once, not on every entry"
    assert gatt.connections == 2, "and the second connection is the useful one"
    assert device._values[1] == bytes.fromhex("01"), "the light is on, and known"


async def test_the_wrong_object_is_never_credited_to_the_entry(
    hass: HomeAssistant, gatt
) -> None:
    """A table that is still wrong after rediscovery: no value, and no success.

    The receiver cannot tell a stale handle from a device that moved its
    entries, so the second pass is the end of it. What must not happen either
    way is a count shown as the state of a light.
    """
    device = coordinator(hass, [LIGHT, COUNT])
    gatt.declare(2, readable={1: bytes.fromhex("0905"), 2: bytes.fromhex("0905")})

    assert await device.async_read_all() is False, (
        "an entry that could not be read means the revision is not read"
    )
    assert 1 not in device._values
    assert gatt.connections == 2, "tried again, once"
    assert gatt.cache_cleared == 2, "and dropped the table it was given both times"


async def test_a_declared_entry_absent_from_the_cached_table_is_read_again(
    hass: HomeAssistant, gatt
) -> None:
    """The other half of D-116: the entry the read path used to skip in silence.

    A device that has just *gained* an entry is a device whose table changed,
    so the copy we hold does not have it -- the same evidence the write path
    has acted on from the start (D-012, D-080).
    """
    device = coordinator(hass, [LIGHT, COUNT])
    gatt.declare(1, readable={1: bytes.fromhex("1E01")})

    async def reveal() -> None:
        gatt.cache_cleared += 1
        uuid = UUID_TEMPLATE.format(2)
        gatt.declare(2, readable={1: bytes.fromhex("1E01"), 2: bytes.fromhex("0905")})
        assert uuid in gatt.characteristics

    gatt.clear_cache = reveal

    assert await device.async_read_all() is True
    assert device._values[2] == bytes.fromhex("05")
    assert gatt.connections == 2


async def test_a_declared_entry_still_absent_is_not_a_successful_read(
    hass: HomeAssistant, gatt
) -> None:
    """This is what used to return True: the entry was skipped, the revision
    marked read, and nothing ever came back to it."""
    device = coordinator(hass, [LIGHT, COUNT])
    gatt.declare(1, readable={1: bytes.fromhex("1E01")})

    assert await device.async_read_all() is False
    assert gatt.cache_cleared == 2


async def test_a_write_only_entry_is_still_a_successful_read(
    hass: HomeAssistant, gatt
) -> None:
    """The case that must not be caught by any of this.

    A write-only entry is legal and common: @enaon's lamp takes commands and
    reports nothing, and §4.3 makes the getter optional. Its characteristic is
    present and has no `read` property, which is a device as declared, not a
    stale table. Treating it as a failure would put every such device into a
    permanent read-retry loop.
    """
    device = coordinator(hass, [LIGHT, COUNT])
    gatt.declare(2, readable={2: bytes.fromhex("0905")})

    assert await device.async_read_all() is True
    assert gatt.connections == 1, "no rediscovery, because nothing is stale"
    assert gatt.cache_cleared == 0
    assert 1 not in device._values
    assert device._values[2] == bytes.fromhex("05")

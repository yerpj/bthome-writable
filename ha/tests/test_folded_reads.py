"""D-130: the read §3.2 called for, made on the connection a command holds.

A connection is the expensive thing. On a user's bench one cost 9.5 s through
an ESPHome proxy, and the proxy stopped scanning for 7.9 s of it; on this bench
0.7 to 3.4 s at a 1000 ms advertising interval (`docs/measurements.md` §16,
§17). So when a device's settings revision has moved and a command is going out
anyway, the read rides with the command, and the read that was queued behind it
finds nothing left to do.

The scripted sequences below are the before-and-after: the same script, the
constant on and off, counting connections. Nothing here needs a radio, which is
the point -- what is being proved is an ordering, not a latency.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest

from custom_components.bthome_writable import coordinator as coordinator_module
from custom_components.bthome_writable.coordinator import BTHomeWritableCoordinator
from custom_components.bthome_writable.protocol import Declaration

from .conftest import UUID_TEMPLATE, settle

ADDRESS = "A4:C1:38:8E:1F:2B"

LIGHT, COUNT = 0x1E, 0x09
"""@enaon's pair: the lamp, and the count his dimmer rides on."""

LIT = bytes.fromhex("1E01")
DIM = bytes.fromhex("0905")
BRIGHTER = bytes.fromhex("0909")


def device(hass: HomeAssistant, *, advertised: int = 4, read: int = 3):
    """A two-entry device whose revision has moved since it was last read."""
    coordinator = BTHomeWritableCoordinator(hass, ADDRESS)
    coordinator.declaration = Declaration.restore(
        {"layout": [LIGHT, COUNT], "settings_revision": advertised}
    )
    coordinator._revision_advertised = advertised
    coordinator._revision_read = read
    return coordinator


# --- the before and after ---------------------------------------------------


@pytest.mark.parametrize(
    ("folded", "connections"),
    [(True, 1), (False, 2)],
    ids=["folded", "separate"],
)
async def test_a_command_and_a_due_read_cost_one_connection_or_two(
    hass: HomeAssistant, gatt, folded: bool, connections: int
) -> None:
    """The whole claim, in one script run twice.

    A knob moved on the device, so §3.2 owes a read. A command goes out. Then
    the read `_read_loop` would make runs. Folded, the command carried it and
    the read connects to nobody; separate, it is a second connection -- and on
    @enaon's bench a second connection is seconds, not milliseconds.
    """
    coordinator = device(hass)
    gatt.declare(2, readable={1: LIT, 2: BRIGHTER})

    with patch.object(coordinator_module, "FOLD_A_DUE_READ_INTO_A_WRITE", folded):
        await coordinator._write_now(1, b"\x01")
        # What a moved revision does on its own: `_notice_revision` asks for a
        # read, and `_read_loop` makes it -- or finds there is nothing left.
        coordinator.async_request_read()
        await settle(hass)

    assert gatt.connections == connections
    assert coordinator.value_of(2) == b"\x09", (
        "the dimmer's new value is in, either way"
    )
    assert coordinator._revision_read == 4, "and the revision is settled, either way"


async def test_a_read_whose_revision_is_already_read_connects_to_nobody(
    hass: HomeAssistant, gatt
) -> None:
    """What makes the fold bite, and worth having on its own.

    A read waits for a connection slot, and whatever held that slot may have
    been a command that carried this very read. `async_read_all` used to
    connect anyway and re-read values it had just stored.
    """
    coordinator = device(hass, advertised=4, read=4)
    gatt.declare(2, readable={1: LIT, 2: DIM})

    assert await coordinator.async_read_all() is True
    assert gatt.connections == 0


# --- what the fold must not break ------------------------------------------


async def test_the_entry_just_written_keeps_what_the_command_decided(
    hass: HomeAssistant, gatt, caplog: pytest.LogCaptureFixture
) -> None:
    """D-122, which the fold could have resurrected.

    A device that applies a write slowly answers with the value it had, because
    §4.3's getter is published rather than served on demand. The write path
    knows that and keeps what was written; a read loop does not and would adopt
    the stale answer. So the folded read leaves that entry alone.
    """
    coordinator = device(hass)
    gatt.declare(2, readable={1: LIT, 2: BRIGHTER})
    gatt.echo_writes = False  # the lamp has not republished the entry yet
    coordinator._values[1] = b"\x01"  # and it was on before the command

    await coordinator._write_now(1, b"\x00")

    assert gatt.connections == 1
    assert coordinator.value_of(1) == b"\x00", (
        "the written value stands; the folded read must not put the lamp back on"
    )
    assert coordinator.value_of(2) == b"\x09", "and the other entry was still read"
    assert coordinator._revision_read == 4


async def test_the_caller_is_released_before_the_folded_read(
    hass: HomeAssistant, gatt
) -> None:
    """The command's own clock stops at the acknowledgement (§4.2).

    Whatever the connection does afterwards is the integration's business, not
    the user's: an action that waited for our housekeeping would report a
    slower command than the device gave.
    """
    coordinator = device(hass)
    gatt.declare(2, readable={1: LIT, 2: BRIGHTER})
    started = asyncio.Event()
    release = asyncio.Event()
    served = gatt.read_gatt_char

    async def hold_the_second_entry(characteristic):
        uuid = (
            characteristic if isinstance(characteristic, str) else characteristic.uuid
        )
        if uuid == UUID_TEMPLATE.format(2):
            # Where the folded read is, rather than how long it takes: an
            # ordering is what this proves, and a clock would prove it weakly.
            started.set()
            await release.wait()
        return await served(characteristic)

    gatt.read_gatt_char = hold_the_second_entry

    command = hass.async_create_task(coordinator.async_write(1, b"\x01"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert command.done(), "the caller was released before this read began"
    finally:
        # Whatever happened above, nothing is left holding the link: a blocked
        # read would hang this test's own teardown.
        release.set()
        await settle(hass)

    assert coordinator.value_of(2) == b"\x09", "and the read then finished"
    assert gatt.connections == 1


async def test_a_folded_read_that_fails_leaves_the_revision_unread(
    hass: HomeAssistant, gatt
) -> None:
    """A read that fails must not be recorded as done (D-083), and must not
    take the command down with it: the device has acknowledged it."""
    coordinator = device(hass)
    gatt.declare(2, readable={1: LIT, 2: BRIGHTER})
    served = gatt.read_gatt_char

    async def refuse_the_second_entry(characteristic):
        uuid = (
            characteristic if isinstance(characteristic, str) else characteristic.uuid
        )
        if uuid == UUID_TEMPLATE.format(2):
            raise TimeoutError("no answer")
        return await served(characteristic)

    gatt.read_gatt_char = refuse_the_second_entry

    await coordinator._write_now(1, b"\x01")

    assert coordinator.value_of(1) == b"\x01", "the command stands"
    assert coordinator._revision_read == 3, "the revision is still owed"
    assert coordinator._read_failed_at is not None, "and the retry is on the clock"


async def test_a_read_that_holds_a_connection_is_left_alone(
    hass: HomeAssistant, gatt
) -> None:
    """One read at a time. A command cannot take over the connection another
    read is already using, so it leaves that revision to it (D-087)."""
    coordinator = device(hass)
    gatt.declare(2, readable={1: LIT, 2: BRIGHTER})
    coordinator._reading = True
    coordinator._read_connected = True

    await coordinator._write_now(1, b"\x01")

    assert gatt.connections == 1, "the command, and nothing else"
    assert coordinator.value_of(2) is None, "the read in flight owns that entry"
    assert coordinator._revision_read == 3


async def test_a_read_waiting_for_a_slot_is_carried_and_stands_down(
    hass: HomeAssistant, gatt
) -> None:
    """The sequence the fold is actually for, and the one that nearly got away.

    `_notice_revision` asks for a read the moment the revision moves, so by the
    time a command runs there is almost always a read *task*. What matters is
    whether it has a connection: while it queues for a slot, the command can do
    its work, and the read then finds the revision already read and stands down
    without connecting. Blocking the fold on the mere existence of that task --
    which is what `_reading` says -- would have left this whole change firing
    only after a failed read.
    """
    coordinator = BTHomeWritableCoordinator(hass, ADDRESS, max_connections=1)
    coordinator.declaration = Declaration.restore(
        {"layout": [LIGHT, COUNT], "settings_revision": 4}
    )
    coordinator._revision_advertised = 4
    coordinator._revision_read = 3
    gatt.declare(2, readable={1: LIT, 2: BRIGHTER})

    at_the_read_back = asyncio.Event()
    carry_on = asyncio.Event()
    served = gatt.read_gatt_char

    async def hold_the_command_in_its_connection(characteristic):
        uuid = (
            characteristic if isinstance(characteristic, str) else characteristic.uuid
        )
        if uuid == UUID_TEMPLATE.format(1) and not carry_on.is_set():
            at_the_read_back.set()
            await carry_on.wait()
        return await served(characteristic)

    gatt.read_gatt_char = hold_the_command_in_its_connection

    command = hass.async_create_task(coordinator.async_write(1, b"\x01"))
    try:
        await asyncio.wait_for(at_the_read_back.wait(), 2)
        # The revision moves while the command holds the only slot: the read
        # this asks for cannot connect until the command lets go.
        coordinator.async_request_read()
        assert coordinator._reading is True
        assert coordinator._read_connected is False
    finally:
        carry_on.set()
        await settle(hass)
        await command

    assert gatt.connections == 1, "the command carried the read; nothing else connected"
    assert coordinator.value_of(2) == b"\x09"
    assert coordinator._revision_read == 4
    assert coordinator._reading is False, "and the read loop finished"


async def test_a_read_in_its_backoff_is_carried_by_a_command(
    hass: HomeAssistant, gatt
) -> None:
    """`READ_RETRY` exists to stop us *connecting* again after a failed read.

    A command's connection is already open, so carrying the read costs nothing
    the backoff was protecting, and it ends the stale window early rather than
    waiting the ten seconds out.
    """
    coordinator = device(hass)
    gatt.declare(2, readable={1: LIT, 2: BRIGHTER})
    coordinator._read_failed_at = asyncio.get_running_loop().time()

    await coordinator._write_now(1, b"\x01")

    assert gatt.connections == 1
    assert coordinator.value_of(2) == b"\x09"
    assert coordinator._revision_read == 4
    assert coordinator._read_failed_at is None

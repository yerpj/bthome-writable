"""D-132: one cap for the host, and a form that can move it.

D-003 settled the cap and its default of two, and its own correction of
2026-09-23 recorded that nothing could ever change it: setup read
`entry.options` and no flow wrote there. Exposing it meant fixing it first.

The cap lived in a `dict[int, asyncio.Semaphore]` keyed by the limit, so two
entries asking for different numbers each got a gate of their own and the host's
real total was their sum. One entry at 2 and one at 3 meant five connections at
once on a host that was told three. Invisible while nothing could write the
option, since every entry then read the same default and the dictionary never
held a second key.
"""

from __future__ import annotations

import asyncio
import time

from bleak_retry_connector import BleakOutOfConnectionSlotsError
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.bthome_writable.const import (
    CONF_MAX_CONNECTIONS,
    DEFAULT_MAX_CONNECTIONS,
    EVENT_WRITE,
)
from custom_components.bthome_writable.coordinator import (
    BTHomeWritableCoordinator,
    WriteFailed,
)
from custom_components.bthome_writable.protocol import Declaration
from custom_components.bthome_writable.slots import (
    ConnectionSlots,
    connection_slots,
    register_request,
    withdraw_request,
)

from .conftest import settle, setup_device

ONE = "A4:C1:38:8E:1F:2B"
ANOTHER = "A4:C1:38:8E:1F:2C"


async def let_the_others_run(times: int = 5) -> None:
    """Yield until every runnable task has reached its next real wait.

    Not a sleep: a task held at the gate never reaches a timer, so sleeping for
    it would wait for ever in this harness. Yielding is also the right
    granularity here, since what is asserted is that a caller *cannot* proceed.
    """
    for _ in range(times):
        await asyncio.sleep(0)


# --- the host's one gate -----------------------------------------------------


def test_one_gate_for_the_host_whatever_each_entry_asks() -> None:
    """The bug this replaces: two limits meant two gates and no cap."""
    assert register_request(ONE, 2) is register_request(ANOTHER, 3)
    assert connection_slots().limit == 2, "the most cautious request is in force"


def test_a_device_that_is_gone_stops_holding_the_cap_down() -> None:
    register_request(ONE, 1)
    register_request(ANOTHER, 4)
    assert connection_slots().limit == 1

    withdraw_request(ONE)
    assert connection_slots().limit == 4

    withdraw_request(ANOTHER)
    assert connection_slots().limit == DEFAULT_MAX_CONNECTIONS, "back to the default"


# --- what the gate does ------------------------------------------------------


async def test_the_gate_admits_up_to_the_limit_and_queues_the_rest() -> None:
    gate = ConnectionSlots(2)
    await gate.acquire()
    await gate.acquire()

    third = asyncio.create_task(gate.acquire())
    await let_the_others_run()
    assert not third.done(), "a third connection waits"
    assert (gate.in_flight, gate.waiting) == (2, 1)

    gate.release()
    await asyncio.wait_for(third, 1)
    assert (gate.in_flight, gate.waiting) == (2, 0)


async def test_raising_the_cap_lets_a_waiter_through_without_a_reload() -> None:
    """Why this is a class of our own: `asyncio.Semaphore` cannot be resized.

    The options form takes effect on the next command, not on the next restart,
    and nobody's open connection is dropped to make that happen.
    """
    gate = ConnectionSlots(1)
    await gate.acquire()
    queued = asyncio.create_task(gate.acquire())
    await let_the_others_run()
    assert not queued.done()

    gate.resize(2)
    await asyncio.wait_for(queued, 1)
    assert gate.in_flight == 2


async def test_lowering_the_cap_drains_the_excess_instead_of_cutting_it() -> None:
    """A connection that is open already costs the adapter its slot."""
    gate = ConnectionSlots(3)
    for _ in range(3):
        await gate.acquire()

    gate.resize(1)
    assert gate.in_flight == 3, "all three stay open"

    queued = asyncio.create_task(gate.acquire())
    gate.release()
    gate.release()
    await let_the_others_run()
    assert not queued.done(), "two in flight against a cap of one is still over it"

    gate.release()
    await asyncio.wait_for(queued, 1)
    assert gate.in_flight == 1


async def test_a_cancelled_waiter_leaves_no_slot_behind() -> None:
    gate = ConnectionSlots(1)
    await gate.acquire()
    queued = asyncio.create_task(gate.acquire())
    await let_the_others_run()

    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert gate.waiting == 0

    gate.release()
    await gate.acquire()
    assert gate.in_flight == 1, "and the slot is still there to be had"


async def test_a_slot_granted_to_a_caller_that_vanishes_is_passed_on() -> None:
    """The one race worth a test: admitted, then cancelled before resuming.

    The slot is that caller's and nobody else knows it, so losing it here would
    lose it for the lifetime of the process.
    """
    gate = ConnectionSlots(1)
    await gate.acquire()
    doomed = asyncio.create_task(gate.acquire())
    next_in_line = asyncio.create_task(gate.acquire())
    await let_the_others_run()

    gate.release()  # hands the slot to `doomed`
    doomed.cancel()  # which never comes back for it
    with pytest.raises(asyncio.CancelledError):
        await doomed

    await asyncio.wait_for(next_in_line, 1)
    assert gate.in_flight == 1


# --- and the form ------------------------------------------------------------


@pytest.mark.usefixtures("custom_integration")
async def test_the_form_shows_the_cap_in_force_and_saves_a_new_one(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Zero-config stands: the form exists, and nobody has to open it."""
    entry = await setup_device(hass, radio, "single-light")
    coordinator = entry.runtime_data
    assert connection_slots().limit == DEFAULT_MAX_CONNECTIONS

    form = await hass.config_entries.options.async_init(entry.entry_id)
    assert form["type"] is FlowResultType.FORM
    assert form["description_placeholders"]["effective"] == "2"

    saved = await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={CONF_MAX_CONNECTIONS: 4}
    )
    assert saved["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    assert entry.options[CONF_MAX_CONNECTIONS] == 4
    assert connection_slots().limit == 4, "in force straight away"
    assert entry.runtime_data is coordinator, "and without reloading the entry"


@pytest.mark.usefixtures("custom_integration")
async def test_unloading_a_device_hands_its_share_of_the_cap_back(
    hass: HomeAssistant, radio, gatt
) -> None:
    entry = await setup_device(hass, radio, "single-light")
    form = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(
        form["flow_id"], user_input={CONF_MAX_CONNECTIONS: 1}
    )
    await hass.async_block_till_done()
    assert connection_slots().limit == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert connection_slots().limit == DEFAULT_MAX_CONNECTIONS


# --- and when the host has no slot left --------------------------------------
#
# D-133. `bleak_retry_connector` counts an exhausted adapter as a transient
# error, so it has already tried nine times, four seconds apart, before it
# raises. There is nothing to gain by trying a tenth; what there is to gain is
# keeping the other devices out of the same wall for a moment.


async def test_a_hold_off_makes_the_next_connection_wait() -> None:
    gate = ConnectionSlots(2)
    gate.hold_off(0.05)

    started = time.monotonic()
    await gate.acquire()

    assert time.monotonic() - started >= 0.04, "it waited"
    assert gate.in_flight == 1, "and then took its slot as usual"


def test_a_shorter_hold_off_does_not_cut_a_longer_one_short() -> None:
    gate = ConnectionSlots(2)
    gate.hold_off(30)
    gate.hold_off(0.1)
    assert gate.holding_off > 1, "the host is still out of slots"


async def test_a_command_that_finds_no_slot_says_which_it_was(
    hass: HomeAssistant, gatt
) -> None:
    """The message a user gets decides what they do next.

    "Could not be reached" sends them to look at the device, which may well be
    sitting there advertising. The host is what ran out.
    """
    coordinator = BTHomeWritableCoordinator(hass, ONE)
    coordinator.declaration = Declaration.restore({"layout": [0x1E]})
    gatt.declare(1)
    gatt.fail_on_connect = BleakOutOfConnectionSlotsError("No slot available")

    with pytest.raises(WriteFailed, match="no connection slot was free"):
        await coordinator._write_now(1, b"\x01")

    assert connection_slots().holding_off > 0, "and the host is given a moment"
    assert gatt.connections == 0


async def test_a_read_that_finds_no_slot_leaves_the_state_alone(
    hass: HomeAssistant, gatt
) -> None:
    """Nobody is waiting on a state read, so this is a deferral, not an error.

    The deferral itself is a level up and predates this: whatever reads fail
    with, the caller catches it, marks `_read_failed_at` and tries again after
    `READ_RETRY` on the next advertisement. What D-133 adds is that the rest of
    the host's devices hear about the exhaustion rather than each discovering
    it for themselves.
    """
    coordinator = BTHomeWritableCoordinator(hass, ONE)
    coordinator.declaration = Declaration.restore(
        {"layout": [0x1E], "settings_revision": 4}
    )
    coordinator._revision_advertised = 4
    coordinator._revision_read = 3
    gatt.declare(1, readable={1: bytes.fromhex("1E01")})
    gatt.fail_on_connect = BleakOutOfConnectionSlotsError("No slot available")

    with pytest.raises(BleakOutOfConnectionSlotsError):
        await coordinator.async_read_all()

    assert connection_slots().holding_off > 0, "the host is given a moment"
    assert coordinator.value_of(1) is None, "and nothing is invented for the state"


async def test_the_wait_for_a_slot_is_reported_as_queueing(
    hass: HomeAssistant, gatt
) -> None:
    """D-133: a cap doing its job must not read as a slow radio.

    `connect_started` was taken before the gate, so the wait for a host slot
    landed in `connect_ms` among the radio's own wait. On the bench a cap of
    one made one command wait nine seconds behind another device, and
    `queued_ms` reported two milliseconds.
    """
    first_device = BTHomeWritableCoordinator(hass, ONE, max_connections=1)
    second_device = BTHomeWritableCoordinator(hass, ANOTHER, max_connections=1)
    for coordinator in (first_device, second_device):
        coordinator.declaration = Declaration.restore({"layout": [0x1E]})
    gatt.declare(1)

    events: list[dict] = []
    hass.bus.async_listen(EVENT_WRITE, lambda event: events.append(event.data))

    at_the_write = asyncio.Event()
    carry_on = asyncio.Event()
    served = gatt.write_gatt_char

    async def hold_the_first_command(characteristic, payload, response=True):
        if not carry_on.is_set():
            at_the_write.set()
            await carry_on.wait()
        return await served(characteristic, payload, response)

    gatt.write_gatt_char = hold_the_first_command

    first = hass.async_create_task(first_device._write_now(1, b"\x01"))
    second = None
    try:
        await asyncio.wait_for(at_the_write.wait(), 2)
        second = hass.async_create_task(second_device._write_now(1, b"\x01"))
        # Real time, because what is being measured is real time: the second
        # command is at the gate and cannot proceed until the first lets go.
        await asyncio.sleep(0.1)
    finally:
        carry_on.set()
        await first
        if second is not None:
            await second
    await settle(hass)

    queued = {event["address"]: event["queued_ms"] for event in events}
    assert queued[ANOTHER] >= 90, f"the wait for the one slot is here: {queued}"
    assert queued[ONE] < 50, f"and the first command queued for nothing: {queued}"


# --- and who goes first ------------------------------------------------------
#
# D-134, the last of D-003's steps. Measured first: at a cap of two, with four
# writable devices configured, a command queued 2528 ms behind this
# integration's own reads (`docs/measurements.md` §20).


async def test_a_command_goes_ahead_of_queued_housekeeping() -> None:
    gate = ConnectionSlots(1)
    await gate.acquire(urgent=True)
    order: list[str] = []

    async def housekeeping() -> None:
        await gate.acquire()
        order.append("read")

    async def a_user_waiting() -> None:
        await gate.acquire(urgent=True)
        order.append("command")

    read = asyncio.create_task(housekeeping())
    await let_the_others_run()
    command = asyncio.create_task(a_user_waiting())
    await let_the_others_run()
    assert order == [], "the only slot is held, so neither has gone"

    gate.release()
    await asyncio.wait_for(command, 1)
    assert order == ["command"], "the command was taken out of turn, by design"

    gate.release()
    await asyncio.wait_for(read, 1)
    assert order == ["command", "read"], "and the read was not forgotten"


async def test_two_commands_keep_the_order_they_arrived_in() -> None:
    """Urgency is a class, not a scramble: each queue is still first in first
    out, so two commands cannot overtake each other."""
    gate = ConnectionSlots(1)
    await gate.acquire(urgent=True)
    order: list[int] = []

    async def command(number: int) -> None:
        await gate.acquire(urgent=True)
        order.append(number)

    first = asyncio.create_task(command(1))
    await let_the_others_run()
    second = asyncio.create_task(command(2))
    await let_the_others_run()

    for _ in range(2):
        gate.release()
    await asyncio.wait_for(asyncio.gather(first, second), 1)
    assert order == [1, 2]


async def test_a_command_overtakes_another_devices_queued_read(
    hass: HomeAssistant, gatt
) -> None:
    """The case §20 measured, in one test: a read of one device holding the
    host's only slot while a command for another waits behind it."""
    reader = BTHomeWritableCoordinator(hass, ONE, max_connections=1)
    reader.declaration = Declaration.restore({"layout": [0x1E], "settings_revision": 4})
    reader._revision_advertised = 4
    reader._revision_read = 3
    commanded = BTHomeWritableCoordinator(hass, ANOTHER, max_connections=1)
    commanded.declaration = Declaration.restore({"layout": [0x1E]})
    gatt.declare(1, readable={1: bytes.fromhex("1E01")})

    order: list[str] = []
    served_write, served_read = gatt.write_gatt_char, gatt.read_gatt_char

    async def note_write(characteristic, payload, response=True):
        order.append("command")
        return await served_write(characteristic, payload, response)

    async def note_read(characteristic):
        order.append("read")
        return await served_read(characteristic)

    gatt.write_gatt_char = note_write
    gatt.read_gatt_char = note_read

    gate = connection_slots()
    await gate.acquire(urgent=True)  # something else holds the one slot
    read = asyncio.create_task(reader.async_read_all())
    await let_the_others_run()
    command = asyncio.create_task(commanded._write_now(1, b"\x01"))
    await let_the_others_run()

    gate.release()
    await asyncio.wait_for(command, 2)
    assert order[0] == "command", f"the command went first: {order}"
    await asyncio.wait_for(read, 2)
    assert "read" in order, "and the read still happened"

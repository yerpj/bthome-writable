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

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.bthome_writable.const import (
    CONF_MAX_CONNECTIONS,
    DEFAULT_MAX_CONNECTIONS,
)
from custom_components.bthome_writable.slots import (
    ConnectionSlots,
    connection_slots,
    register_request,
    withdraw_request,
)

from .conftest import setup_device

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

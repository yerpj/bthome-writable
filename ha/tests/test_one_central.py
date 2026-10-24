"""D-131: an Espruino serves one central, so two of ours must take turns.

The connection cap of D-003 is per host: it protects the adapter's and the
proxies' slots, which a device knows nothing about. The constraint a *device*
has is its own -- one central at a time -- and until this was measured nothing
expressed it. With two host slots and two mechanisms that connect, a command
and the read §3.2 calls for could reach for the same device at once: one then
waited on a link the other held, retried, and arrived 13 to 34 s later or gave
up (`docs/measurements.md` §18, §19).

The fold of D-130 removes that collision for the reads a command happens to
carry. These tests are about the rest of them.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import patch

from homeassistant.core import HomeAssistant

from custom_components.bthome_writable import coordinator as coordinator_module

from .conftest import a_lamp_and_a_dimmer, hold_the_first, let_the_others_run, settle

LIT = bytes.fromhex("1E01")
DIM = bytes.fromhex("0905")


async def test_a_read_waits_for_the_command_to_let_go_of_the_device(
    hass: HomeAssistant, gatt
) -> None:
    """The collision, and the lock that ends it.

    The fold is off here on purpose: what is under test is the serialisation,
    not the case where the command carries the read. Two host slots are free,
    so nothing but the device's own turn can hold the read back.
    """
    coordinator = a_lamp_and_a_dimmer(hass, "A4:C1:38:8E:1F:2B")
    gatt.declare(2, readable={1: LIT, 2: DIM})
    at_the_read_back, carry_on = hold_the_first(gatt, read=1)

    with patch.object(coordinator_module, "FOLD_A_DUE_READ_INTO_A_WRITE", False):
        command = hass.async_create_task(coordinator.async_write(1, b"\x01"))
        read = None
        try:
            await asyncio.wait_for(at_the_read_back.wait(), 2)
            read = hass.async_create_task(coordinator.async_read_all())
            await let_the_others_run()

            assert gatt.connections == 1, (
                "the read may not connect while the command holds the device"
            )
        finally:
            carry_on.set()
            await settle(hass)
            await command
            if read is not None:
                await read

    assert gatt.connections == 2, "and it connected once the command let go"
    assert coordinator.value_of(2) == b"\x05"


async def test_two_devices_are_not_made_to_wait_for_each_other(
    hass: HomeAssistant, gatt
) -> None:
    """The lock is per device, and the point of that is that it is not per host.

    A bench of twenty lamps whose commands queued behind each other would be a
    worse fault than the one being fixed. The host cap stays the only thing that
    limits how many devices are talked to at once (D-003).
    """
    one = a_lamp_and_a_dimmer(hass, "A4:C1:38:8E:1F:2B", due=False)
    two = a_lamp_and_a_dimmer(hass, "A4:C1:38:8E:1F:2C", due=False)
    gatt.declare(2, readable={1: LIT, 2: DIM})
    at_the_read_back, carry_on = hold_the_first(gatt, read=1)

    first = hass.async_create_task(one.async_write(1, b"\x01"))
    second = None
    try:
        await asyncio.wait_for(at_the_read_back.wait(), 2)
        second = hass.async_create_task(two.async_write(2, b"\x07"))
        for _ in range(10):
            await asyncio.sleep(0)

        assert gatt.connections == 2, (
            "the second device's command connected while the first was held"
        )
    finally:
        carry_on.set()
        await settle(hass)
        await first
        if second is not None:
            await second


async def test_a_connection_that_fails_does_not_keep_the_device_to_itself(
    hass: HomeAssistant, gatt
) -> None:
    """A lock held by a failure is a device nothing can reach again."""
    coordinator = a_lamp_and_a_dimmer(hass, "A4:C1:38:8E:1F:2B", due=False)
    gatt.declare(1, readable={1: LIT})
    gatt.fail_on_write = TimeoutError("the link went away")

    with patch.object(coordinator_module, "FOLD_A_DUE_READ_INTO_A_WRITE", False):
        # The write is expected to fail; what matters is that the next one
        # is not shut out, which is the device's turn having been handed
        # back. Asserted through a second command rather than by reading
        # the lock: what the lock *is* may change (D-003's remaining step),
        # what it guarantees may not.
        with contextlib.suppress(Exception):
            await coordinator._write_now(1, b"\x01")

        gatt.fail_on_write = None
        await coordinator._write_now(1, b"\x00")

    assert coordinator.value_of(1) == b"\x00", "and the next command gets through"


async def test_a_command_waiting_for_a_device_does_not_sit_on_a_host_slot(
    hass: HomeAssistant, gatt
) -> None:
    """The order the two locks are taken in, which is the rest of D-131.

    The device's turn first, then a host slot, and never the other way round: a
    command that waited for a busy device while holding one of the host's two
    slots would make one device's queue every other device's problem.

    So: one command in flight on a device, a second queued behind it, and a
    third for a different device. The third must get through.
    """
    busy = a_lamp_and_a_dimmer(hass, "A4:C1:38:8E:1F:2B", due=False)
    elsewhere = a_lamp_and_a_dimmer(hass, "A4:C1:38:8E:1F:2C", due=False)
    gatt.declare(2, readable={1: LIT, 2: DIM})
    at_the_write, carry_on = hold_the_first(gatt, write=True)

    in_flight = hass.async_create_task(busy._write_now(1, b"\x01"))
    queued = other_device = None
    try:
        await asyncio.wait_for(at_the_write.wait(), 2)
        queued = hass.async_create_task(busy._write_now(2, b"\x05"))
        await let_the_others_run()
        other_device = hass.async_create_task(elsewhere._write_now(1, b"\x01"))
        await let_the_others_run()

        assert gatt.connections == 2, (
            "the other device connected, so the queued command is waiting for "
            "its device rather than holding one of the host's two slots"
        )
    finally:
        carry_on.set()
        await settle(hass)
        for command in (in_flight, queued, other_device):
            if command is not None:
                await command

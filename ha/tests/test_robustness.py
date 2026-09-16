"""T4.1: what happens when the connection fails, and where the user sees it.

The rest of the suite fakes `_write_now` outright, which is right for testing
what bytes get composed but means the connection path itself is never exercised.
These tests run that path for real against a fake client, because the failures
that matter in this project all live there -- a link that drops mid-write, a
device that disappears between the decision to write and the write itself -- and
because both of the incidents on 2026-09-15 were connection failures that
presented as something else entirely (D-042, D-043).
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

from bleak.exc import BleakError
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
import pytest

from custom_components.bthome_writable.entity import LOGBOOK_ENTRY

from .conftest import with_light
from .test_switch import FAST_DEBOUNCE, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

ENTITY = "switch.espruino_light_light"


class FakeClient:
    """A GATT client that can be told how to fail.

    Modelled on the real one only as far as `_write_now` touches it: the
    characteristic lookup, the write, and the disconnect that has to happen
    whatever else does.
    """

    def __init__(self, *, fail_on_write: Exception | None = None) -> None:
        self.fail_on_write = fail_on_write
        self.disconnected = False
        self.cache_cleared = False
        self.written: list[bytes] = []
        self.services = MagicMock()
        self.services.get_characteristic.return_value = MagicMock()

    async def write_gatt_char(self, _characteristic, payload, response=True):
        if self.fail_on_write is not None:
            raise self.fail_on_write
        self.written.append(bytes(payload))

    async def disconnect(self):
        self.disconnected = True

    async def clear_cache(self):
        self.cache_cleared = True


def connected(client: FakeClient):
    """Patch the transport so `_write_now` runs against `client`.

    The debounce goes with it: at its production value the write lands after
    anything the test pushes, so a confirming advertisement would arrive before
    the confirmation window had even opened.
    """
    module = "custom_components.bthome_writable.coordinator"
    return (
        patch(
            f"{module}.bluetooth.async_ble_device_from_address", return_value=object()
        ),
        patch(f"{module}.establish_connection", AsyncMock(return_value=client)),
        patch(f"{module}.BTHomeWritableCoordinator._check_mtu", AsyncMock()),
        patch(f"{module}.WRITE_DEBOUNCE", FAST_DEBOUNCE),
    )


async def toggle(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": ENTITY}, blocking=True
    )


@pytest.fixture
def logbook_entries(hass: HomeAssistant) -> list[dict]:
    """Collect the logbook entries the integration fires."""
    entries: list[dict] = []
    hass.bus.async_listen(LOGBOOK_ENTRY, lambda event: entries.append(event.data))
    return entries


async def test_a_link_that_drops_mid_write_reverts_the_entity(
    hass: HomeAssistant, radio
) -> None:
    """The fault injection T4.1 asks for: the connection succeeds, the write
    does not. The entity must not keep showing a value the device never took."""
    await setup_device(hass, radio, "espruino-single-light")
    client = FakeClient(fail_on_write=BleakError("device disconnected"))

    with contextlib.ExitStack() as stack:
        for context in connected(client):
            stack.enter_context(context)
        await toggle(hass)
        await settle(hass, 0.3)

    assert hass.states.get(ENTITY).state == STATE_ON, (
        "a write that raised must leave the entity on the device's last "
        "advertised value, not on the value that was attempted"
    )


async def test_the_connection_is_released_even_when_the_write_raises(
    hass: HomeAssistant, radio
) -> None:
    """The one thing that must survive any failure.

    A client that is never disconnected holds a slot on the adapter, and the
    device -- an Espruino accepts a single central -- stays unreachable to
    everyone until something power-cycles it. That is D-043, which cost an
    evening, so it gets a test rather than a `finally` and good intentions.
    """
    await setup_device(hass, radio, "espruino-single-light")
    client = FakeClient(fail_on_write=BleakError("device disconnected"))

    with contextlib.ExitStack() as stack:
        for context in connected(client):
            stack.enter_context(context)
        await toggle(hass)
        await settle(hass, 0.3)

    assert client.disconnected


async def test_a_failed_write_is_recorded_in_the_logbook(
    hass: HomeAssistant, radio, logbook_entries
) -> None:
    """Where a user actually looks.

    A reverted entity is indistinguishable from one that was never touched, so
    without this the failure is invisible outside the debug log.
    """
    await setup_device(hass, radio, "espruino-single-light")
    client = FakeClient(fail_on_write=BleakError("device disconnected"))

    with contextlib.ExitStack() as stack:
        for context in connected(client):
            stack.enter_context(context)
        await toggle(hass)
        await settle(hass, 0.3)

    assert logbook_entries, "a failed write must leave a logbook entry"
    entry = logbook_entries[-1]
    assert entry["entity_id"] == ENTITY
    assert "did not reach the device" in entry["message"]


async def test_an_unreachable_device_fails_before_it_connects(
    hass: HomeAssistant, radio
) -> None:
    """The device vanished between the command and the write.

    Worth separating from a failed connection: there is nothing to retry and
    nothing to disconnect, and the message has to say which of the two it was --
    D-043 was made harder by an error that conflated them.
    """
    await setup_device(hass, radio, "espruino-single-light")

    module = "custom_components.bthome_writable.coordinator"
    with patch(f"{module}.bluetooth.async_ble_device_from_address", return_value=None):
        await toggle(hass)
        await settle(hass, 0.3)

    assert hass.states.get(ENTITY).state == STATE_ON


async def test_a_successful_write_leaves_no_logbook_noise(
    hass: HomeAssistant, radio, logbook_entries
) -> None:
    """The logbook is for failures. A working control that wrote a row on every
    press would be worse than one that wrote none."""
    await setup_device(hass, radio, "espruino-single-light")
    client = FakeClient()

    with contextlib.ExitStack() as stack:
        for context in connected(client):
            stack.enter_context(context)
        await toggle(hass)
        # A bare sleep, not `settle`: `async_block_till_done` would drain the
        # confirmation task to its ceiling, and the advertisements below would
        # then arrive after the window they are supposed to close.
        await asyncio.sleep(0.05)

    # The device obeys and says so, which is the only thing that closes the
    # confirmation window (§6). Pushed after the write has landed, or the
    # window has not opened yet and the advertisement counts for nothing.
    radio.push(with_light("espruino-single-light", on=False, time=1.0))
    radio.push(with_light("espruino-single-light", on=False, time=2.0))
    await hass.async_block_till_done()

    assert client.written == [b"\x1e\x00"]
    assert logbook_entries == []


async def test_the_connection_cap_is_one_semaphore_for_the_whole_host(
    hass: HomeAssistant, radio
) -> None:
    """D-003: the cap protects the adapter's slots, which are a host resource.

    A per-device cap would let ten devices open ten connections and starve the
    adapter, which is precisely the state the host was found in on 2026-09-15.
    """
    from custom_components.bthome_writable.coordinator import connection_semaphore

    assert connection_semaphore(2) is connection_semaphore(2)
    assert connection_semaphore(2) is not connection_semaphore(3)


async def test_a_write_failure_does_not_wedge_the_queue(
    hass: HomeAssistant, radio
) -> None:
    """After a failure the next command must still be attempted.

    The flush loop scopes its redundancy suppression to one burst precisely so
    that a failed write stays repeatable (D-020); this checks the connection
    path honours that too, rather than leaving the position marked as sent.
    """
    await setup_device(hass, radio, "espruino-single-light")
    failing = FakeClient(fail_on_write=BleakError("device disconnected"))

    with contextlib.ExitStack() as stack:
        for context in connected(failing):
            stack.enter_context(context)
        await toggle(hass)
        await settle(hass, 0.3)

    working = FakeClient()
    with contextlib.ExitStack() as stack:
        for context in connected(working):
            stack.enter_context(context)
        await toggle(hass)
        await settle(hass, 0.3)

    assert working.written == [b"\x1e\x00"], (
        "the second command must reach the device; a failure that leaves the "
        "value queued as already-written makes the control permanently dead"
    )

"""T4.1: what happens when the connection fails, and where the user sees it.

Run against a fake GATT client, so the connection path itself is exercised: a
link that drops mid-write, a device that is not reachable, a command that
fails without touching the one before it. Both incidents of 2026-09-15 were
connection failures that presented as something else (D-042, D-043).
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import STATE_ON, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.bthome_writable.const import EVENT_WRITE
from custom_components.bthome_writable.coordinator import connection_semaphore
from custom_components.bthome_writable.entity import LOGBOOK_ENTRY

from .conftest import DEFAULT_ADDRESS, UUID_TEMPLATE, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

LIGHT = "switch.espruino_light_light"


@pytest.fixture
def logbook_entries(hass: HomeAssistant) -> list[dict]:
    entries: list[dict] = []
    hass.bus.async_listen(LOGBOOK_ENTRY, lambda event: entries.append(event.data))
    return entries


async def test_a_link_that_drops_mid_write_leaves_the_value_unapplied(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)
    gatt.fail_on_write = RuntimeError("device disconnected")

    with pytest.raises(HomeAssistantError, match="could not be reached"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
        )
    await settle(hass)

    assert hass.states.get(LIGHT).state == STATE_UNKNOWN


async def test_the_connection_is_released_even_when_the_write_raises(
    hass: HomeAssistant, radio, gatt
) -> None:
    """A client never disconnected holds a slot and leaves an Espruino -- one
    central at a time -- unreachable to everyone (D-043)."""
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)
    gatt.fail_on_write = RuntimeError("device disconnected")

    with pytest.raises(HomeAssistantError, match="could not be reached"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
        )
    await settle(hass)

    assert gatt.connections == gatt.disconnects == 1


async def test_a_failed_write_is_recorded_in_the_logbook(
    hass: HomeAssistant, radio, gatt, logbook_entries
) -> None:
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)
    gatt.fail_on_write = RuntimeError("device disconnected")

    with pytest.raises(HomeAssistantError, match="could not be reached"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
        )
    await settle(hass)

    assert logbook_entries
    assert logbook_entries[-1]["entity_id"] == LIGHT
    assert "did not reach the device" in logbook_entries[-1]["message"]


async def test_a_successful_write_leaves_no_logbook_noise(
    hass: HomeAssistant, radio, gatt, logbook_entries
) -> None:
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)

    assert gatt.writes
    assert logbook_entries == []


async def test_an_unreachable_device_fails_before_it_connects(
    hass: HomeAssistant, radio, gatt, logbook_entries
) -> None:
    await setup_device(hass, radio, "single-light")
    module = "custom_components.bthome_writable.coordinator"
    with (
        patch(f"{module}.bluetooth.async_ble_device_from_address", return_value=None),
        pytest.raises(HomeAssistantError, match="could not be reached"),
    ):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
        )
        await settle(hass)

    assert gatt.connections == 0
    assert "not reachable" in logbook_entries[-1]["message"]


async def test_a_command_that_fails_takes_nothing_else_with_it(
    hass: HomeAssistant, radio, gatt
) -> None:
    """One connection carries one command (D-059). Two entries queued together
    are two connections, so a link that drops on the second leaves the first
    applied -- and, unlike a batch, the second is retried by nothing and
    reported on its own."""
    await setup_device(hass, radio, "two-lights-and-display")
    gatt.declare(3)
    coordinator = hass.config_entries.async_entries("bthome_writable")[0].runtime_data

    await coordinator._write_now(1, b"\x01")
    gatt.fail_on_write = RuntimeError("device disconnected")
    with pytest.raises(RuntimeError):
        await coordinator._write_now(2, b"\x01")

    assert coordinator.value_of(1) == b"\x01"
    assert coordinator.value_of(2) is None
    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("1e01"))]
    assert gatt.connections == gatt.disconnects == 2


async def test_a_write_failure_does_not_wedge_the_queue(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)
    gatt.fail_on_write = RuntimeError("device disconnected")
    with pytest.raises(HomeAssistantError, match="could not be reached"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
        )
    await settle(hass)

    gatt.fail_on_write = None
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)

    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("1e01"))]
    assert hass.states.get(LIGHT).state == STATE_ON


def test_the_connection_cap_is_one_semaphore_for_the_whole_host() -> None:
    """D-003: the cap protects the adapter's slots, a host resource."""
    assert connection_semaphore(2) is connection_semaphore(2)
    assert connection_semaphore(2) is not connection_semaphore(3)


async def test_a_write_reports_where_its_time_went(
    hass: HomeAssistant, radio, gatt
) -> None:
    """The one boundary a receiver can measure and a user cares about: from the
    command arriving to the device acknowledging the write. Split, because the
    interesting part is `connect_ms` -- mostly the wait to catch the device
    advertising, which is what its advertising interval costs (D-050)."""
    events: list[dict] = []
    hass.bus.async_listen(EVENT_WRITE, lambda event: events.append(event.data))

    await setup_device(hass, radio, "single-light")
    gatt.declare(1)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)

    assert len(events) == 1
    timing = events[0]
    assert timing["entry"] == 1
    assert timing["address"] == DEFAULT_ADDRESS
    for phase in ("queued_ms", "connect_ms", "write_ms", "total_ms"):
        assert timing[phase] >= 0
    # The total covers the whole journey, so it cannot be shorter than its parts.
    assert timing["total_ms"] >= timing["connect_ms"] + timing["write_ms"] - 0.1


async def test_a_failed_write_reports_no_timing(
    hass: HomeAssistant, radio, gatt
) -> None:
    """A write that never landed has no delivery time to report."""
    events: list[dict] = []
    hass.bus.async_listen(EVENT_WRITE, lambda event: events.append(event.data))

    await setup_device(hass, radio, "single-light")
    gatt.declare(1)
    gatt.fail_on_write = RuntimeError("device disconnected")
    with pytest.raises(HomeAssistantError, match="could not be reached"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
        )
    await settle(hass)

    assert events == []

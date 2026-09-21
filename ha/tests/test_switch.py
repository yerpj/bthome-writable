"""The switch platform and the version 2 state model, end to end.

What bytes leave, on which characteristic, and what the entity shows before,
during and after a write -- against a fake GATT client rather than a mocked
coordinator, so the connection path is exercised too.
"""

from __future__ import annotations

import asyncio

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest

from .conftest import (
    DEFAULT_ADDRESS,
    UUID_TEMPLATE,
    service_info,
    settle,
    setup_device,
)

pytestmark = pytest.mark.usefixtures("custom_integration")

LIGHT = "switch.espruino_light_light"


async def test_one_switch_per_declared_light(hass: HomeAssistant, radio, gatt) -> None:
    await setup_device(hass, radio, "single-light")
    assert hass.states.get(LIGHT) is not None


async def test_entries_of_one_type_are_numbered_in_entry_order(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "two-lights-and-display")
    assert hass.states.get("switch.espruino_light_light_1") is not None
    assert hass.states.get("switch.espruino_light_light_2") is not None


async def test_the_state_is_unknown_until_written(
    hass: HomeAssistant, radio, gatt
) -> None:
    """§2.3: nothing is advertised, and nothing has been sent yet."""
    await setup_device(hass, radio, "single-light")
    assert hass.states.get(LIGHT).state == STATE_UNKNOWN


async def test_turning_on_writes_one_object_to_characteristic_1(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)

    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("1e01"))]
    assert hass.states.get(LIGHT).state == STATE_ON
    assert gatt.disconnects == gatt.connections


async def test_a_write_touches_only_its_own_entry(
    hass: HomeAssistant, radio, gatt
) -> None:
    """§4.2: no write-all. The first light and the display are not written."""
    await setup_device(hass, radio, "two-lights-and-display")
    gatt.declare(3)

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.espruino_light_light_2"},
        blocking=True,
    )
    await settle(hass)

    assert gatt.writes == [(UUID_TEMPLATE.format(2), bytes.fromhex("1e00"))]


async def test_an_entity_without_reported_state_is_assumed_state(
    hass: HomeAssistant, radio, gatt
) -> None:
    """§3.1: a device advertising no settings revision is shown as last set."""
    await setup_device(hass, radio, "single-light")
    assert hass.states.get(LIGHT).attributes.get("assumed_state") is True


async def test_a_failed_write_is_not_shown_as_applied(
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


async def test_a_failed_write_keeps_the_last_value_that_did_arrive(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)
    gatt.fail_on_write = RuntimeError("device disconnected")
    with pytest.raises(HomeAssistantError, match="could not be reached"):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": LIGHT}, blocking=True
        )
    await settle(hass)

    assert hass.states.get(LIGHT).state == STATE_ON


async def test_rapid_toggles_collapse_behind_the_write_in_flight(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Leading edge, then coalesced (D-020): the first command goes at once, and
    whatever piles up behind it collapses to its last value."""
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)

    for service in ("turn_on", "turn_off", "turn_on", "turn_off"):
        await hass.services.async_call("switch", service, {"entity_id": LIGHT})
    await settle(hass, 0.2)

    assert len(gatt.writes) <= 2
    assert gatt.writes[-1] == (UUID_TEMPLATE.format(1), bytes.fromhex("1e00"))
    assert hass.states.get(LIGHT).state == STATE_OFF


async def test_the_entity_goes_unavailable_when_the_device_stops_advertising(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    radio.vanish()
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT).state == STATE_UNAVAILABLE


async def test_a_sensor_only_packet_does_not_drop_the_entries(
    hass: HomeAssistant, radio, gatt
) -> None:
    """§2.2: a rotating device's other packet is not 'nothing writable'."""
    await setup_device(hass, radio, "rotation-declaration-packet")
    radio.push(service_info("rotation-sensor-packet"))
    await hass.async_block_till_done()
    gatt.declare(1)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)
    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("1e01"))]


async def test_a_changed_layout_forgets_values_and_the_cached_gatt_table(
    hass: HomeAssistant, radio, gatt
) -> None:
    """New firmware means a rebuilt GATT table, and old values mean nothing."""
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)
    assert hass.states.get(LIGHT).state == STATE_ON

    radio.push(service_info("two-lights-and-display"))
    await settle(hass)

    assert gatt.cache_cleared == 1
    assert hass.states.get(LIGHT).state == STATE_UNKNOWN


async def test_a_characteristic_missing_from_the_cache_drops_the_cache(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    # No characteristics declared: the cached table is stale.

    with pytest.raises(HomeAssistantError, match="could not be reached"):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
        )
    await settle(hass)

    assert gatt.cache_cleared == 1
    assert hass.states.get(LIGHT).state == STATE_UNKNOWN


async def test_the_device_merges_with_the_core_bthome_device_card(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Identified by its Bluetooth connection, not by identifiers of our own."""
    await setup_device(hass, radio, "single-light")
    registry = dr.async_get(hass)
    device = registry.async_get_device(
        connections={(dr.CONNECTION_BLUETOOTH, DEFAULT_ADDRESS)}
    )
    assert device is not None
    assert not device.identifiers


async def test_the_action_waits_for_the_write_rather_than_the_queue(
    hass: HomeAssistant, radio, gatt
) -> None:
    """`action-exceptions`, Silver: an action returns when the work is done.

    The write used to be queued and the call returned at once, so a command that
    never landed still reported success. Now the caller waits for its own write,
    which is what makes the failure above reportable at all (D-064).
    """
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )

    # No settle(): if the call returned before the write, this is empty.
    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("1e01"))]


async def test_a_superseded_command_is_not_an_error(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Coalescing drops a queued value when a newer one arrives for the entry.

    Nothing failed -- the user changed their mind, or dragged a slider -- so the
    dropped call must not raise. Only a command that reached the device and was
    refused, or could not be delivered at all, is an error (D-064).
    """
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)

    both = [
        hass.services.async_call("switch", service, {"entity_id": LIGHT}, blocking=True)
        for service in ("turn_on", "turn_off")
    ]
    await asyncio.gather(*both)  # neither raises
    await settle(hass)

    assert gatt.writes[-1] == (UUID_TEMPLATE.format(1), bytes.fromhex("1e00"))
    assert hass.states.get(LIGHT).state == STATE_OFF

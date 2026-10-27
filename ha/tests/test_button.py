"""The button platform: event entries, one button per vocabulary value."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
import pytest

from custom_components.bthome_writable.button import event_payload

from .conftest import UUID_TEMPLATE, service_info, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

PRESS = "button.espruino_light_press"


async def test_one_button_per_value_of_the_vocabulary(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "momentary-action")
    for name in ("press", "double_press", "long_press", "hold_press"):
        assert hass.states.get(f"button.espruino_light_{name}") is not None


async def test_pressing_writes_the_event_to_its_entry(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "momentary-action")
    gatt.declare(1)

    await hass.services.async_call(
        "button", "press", {"entity_id": PRESS}, blocking=True
    )
    await settle(hass)

    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("3a01"))]


async def test_two_presses_are_two_writes(hass: HomeAssistant, radio, gatt) -> None:
    """Events are never coalesced: a second press is not a repeat to drop."""
    await setup_device(hass, radio, "momentary-action")
    gatt.declare(1)

    await hass.services.async_call("button", "press", {"entity_id": PRESS})
    await hass.services.async_call("button", "press", {"entity_id": PRESS})
    await settle(hass, 0.2)

    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("3a01"))] * 2


async def test_a_command_entry_is_counted_and_not_offered(
    hass: HomeAssistant, radio, gatt
) -> None:
    """D-151, and it used to be the opposite test.

    0x3B was offered as five buttons from 2026-10-03, because version 2 writes
    one entry rather than all of them and that was the objection version 1 could
    not answer (D-048). §2.1 now excludes the object outright: BTHome gives it to
    a device announcing a command of its own, so a writable one would face both
    ways. The entry is still counted, which is what the light behind it proves.
    """
    await setup_device(
        hass, radio, "momentary-action", service_data=bytes.fromhex("400009ff023b1e")
    )
    gatt.declare(2)

    assert not [s for s in hass.states.async_entity_ids() if s.startswith("button.")]
    # Entry 2, because the excluded entry keeps its place in the count.
    switch = [s for s in hass.states.async_entity_ids() if s.startswith("switch.")]
    assert len(switch) == 1
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch[0]}, blocking=True
    )
    await settle(hass)
    assert gatt.writes == [(UUID_TEMPLATE.format(2), bytes.fromhex("1e01"))]


def test_event_payloads_follow_bthomes_encodings() -> None:
    assert event_payload(0x3A, 0x04) == bytes([0x04])
    assert event_payload(0x3C, 0x01) == bytes([0x01, 0x01])  # rotate left, one step


async def test_the_sensor_packet_does_not_create_buttons(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    radio.push(service_info("single-light"))
    await hass.async_block_till_done()
    assert not [s for s in hass.states.async_entity_ids() if s.startswith("button.")]

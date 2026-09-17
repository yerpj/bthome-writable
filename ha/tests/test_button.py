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


async def test_a_command_entry_is_offered_now_that_writes_are_per_entry(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Version 1 could not offer 0x3B: write-all would have sent it an `off`.
    Version 2 writes only the entry pressed (D-048)."""
    await setup_device(
        hass, radio, "momentary-action", service_data=bytes.fromhex("400009ff3b")
    )
    gatt.declare(1)
    assert hass.states.get("button.espruino_light_toggle") is not None

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.espruino_light_toggle"}, blocking=True
    )
    await settle(hass)
    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("3b0002"))]


def test_event_payloads_follow_bthomes_encodings() -> None:
    assert event_payload(0x3A, 0x04) == bytes([0x04])
    assert event_payload(0x3C, 0x01) == bytes([0x01, 0x01])  # rotate left, one step
    assert event_payload(0x3B, 0x01) == bytes([0x00, 0x01])  # on, no arguments
    assert event_payload(0x3B, 0x03) == bytes([0x01, 0x03, 0x01])  # step up, one step


async def test_the_sensor_packet_does_not_create_buttons(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "single-light")
    radio.push(service_info("single-light"))
    await hass.async_block_till_done()
    assert not [s for s in hass.states.async_entity_ids() if s.startswith("button.")]

"""The button platform: writable event objects.

One button per value of BTHome's own vocabulary, and nothing that pretends to
confirm — an event object's resting advertisement is "none" whatever was
pressed, so §6 has nothing to compare against.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest

from custom_components.bthome_writable.protocol import event_values

from .test_switch import FAST_DEBOUNCE, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

PRESS = "button.espruino_light_press"
LONG_PRESS = "button.espruino_light_long_press"


async def press(hass: HomeAssistant, entity: str) -> None:
    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "button", "press", {"entity_id": entity}, blocking=True
        )
        await settle(hass)


async def test_one_button_per_value_of_the_vocabulary(
    hass: HomeAssistant, radio
) -> None:
    """Seven values, seven buttons. Choosing a favourite would make the rest
    unreachable, which is the mistake the switch platform used to make."""
    await setup_device(hass, radio, "writable-button")

    expected = len(event_values(0x3A) or {})
    buttons = [
        state
        for state in hass.states.async_all("button")
        if state.entity_id.startswith("button.espruino_light_")
    ]
    assert len(buttons) == expected
    assert hass.states.get(PRESS) is not None
    assert hass.states.get(LONG_PRESS) is not None


async def test_pressing_writes_the_value_that_button_names(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """0x04 is long_press; the same bytes as the fixture's `long-press` write."""
    await setup_device(hass, radio, "writable-button")
    await press(hass, LONG_PRESS)

    assert mock_write == [bytes.fromhex("3a04")]


async def test_a_press_does_not_wait_for_a_confirmation_that_cannot_come(
    hass: HomeAssistant, radio, mock_write, caplog
) -> None:
    """The device keeps advertising 'none'. An entity applying §6 here would
    log a revert warning after every single press."""
    await setup_device(hass, radio, "writable-button")
    caplog.clear()
    await press(hass, PRESS)

    assert mock_write == [bytes.fromhex("3a01")]
    assert "reverting" not in caplog.text


async def test_the_command_object_is_not_offered(hass: HomeAssistant, radio) -> None:
    """0x3B's vocabulary has no 'none' -- its 0x00 is `off`. Until §4.3 says
    what to send to leave it alone, a control for it would surprise people."""
    from custom_components.bthome_writable.protocol import EVENT_NO_OP

    assert 0x3B not in EVENT_NO_OP
    assert (event_values(0x3B) or {}).get(0x00) == "off"

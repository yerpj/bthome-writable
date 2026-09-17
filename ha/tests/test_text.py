"""The text platform."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest

from .conftest import UUID_TEMPLATE, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

TEXT = "text.espruino_light_text"


async def test_a_text_entry_is_a_text_entity(hass: HomeAssistant, radio, gatt) -> None:
    await setup_device(hass, radio, "two-lights-and-display")
    assert hass.states.get(TEXT) is not None


async def test_setting_text_writes_bthomes_encoding_to_its_entry(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Length byte kept (D-048), characteristic 3, and nothing else written."""
    await setup_device(hass, radio, "two-lights-and-display")
    gatt.declare(3)

    await hass.services.async_call(
        "text", "set_value", {"entity_id": TEXT, "value": "Hello"}, blocking=True
    )
    await settle(hass)

    assert gatt.writes == [(UUID_TEMPLATE.format(3), bytes.fromhex("530548656c6c6f"))]
    assert hass.states.get(TEXT).state == "Hello"


async def test_the_text_is_unknown_until_something_is_sent(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "two-lights-and-display")
    assert hass.states.get(TEXT).state == "unknown"


async def test_text_longer_than_a_length_byte_is_refused(
    hass: HomeAssistant, radio, gatt
) -> None:
    await setup_device(hass, radio, "two-lights-and-display")
    gatt.declare(3)
    with pytest.raises((ValueError, ServiceValidationError)):
        await hass.services.async_call(
            "text", "set_value", {"entity_id": TEXT, "value": "x" * 256}, blocking=True
        )
    assert gatt.writes == []

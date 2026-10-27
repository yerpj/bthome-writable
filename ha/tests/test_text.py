"""The text platform."""

from __future__ import annotations

import logging

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


async def test_a_write_that_cannot_fit_the_link_says_so(
    hass: HomeAssistant, radio, gatt, caplog: pytest.LogCaptureFixture
) -> None:
    """D-148. The ceiling of §4.4 is `MTU - 3`, and above it nothing is tidy.

    Measured against a Jolt.js on an MTU of 131: 128 bytes acknowledged, 129
    bytes `Unreachable` and the connection gone with it. The write still goes
    out, because `bleak` reports 23 on BlueZ until it has been asked and a real
    23 cannot be told from an unread one (D-084); what this adds is a line that
    names both sizes, so the stack's error is diagnosable rather than mystifying.
    """
    await setup_device(hass, radio, "two-lights-and-display")
    gatt.declare(3)
    gatt.mtu_size = 23  # BLE's own default: 20 bytes of payload

    with caplog.at_level(logging.WARNING):
        await hass.services.async_call(
            "text", "set_value", {"entity_id": TEXT, "value": "x" * 30}, blocking=True
        )
        await settle(hass)

    assert "32 bytes and the MTU reads 23" in caplog.text
    assert "4.4" in caplog.text
    # Not refused: the warning is a diagnosis, not a policy.
    assert len(gatt.writes) == 1


async def test_a_write_that_fits_says_nothing(
    hass: HomeAssistant, radio, gatt, caplog: pytest.LogCaptureFixture
) -> None:
    await setup_device(hass, radio, "two-lights-and-display")
    gatt.declare(3)
    gatt.mtu_size = 131  # what a Jolt.js negotiated with this host

    with caplog.at_level(logging.WARNING):
        await hass.services.async_call(
            "text", "set_value", {"entity_id": TEXT, "value": "x" * 30}, blocking=True
        )
        await settle(hass)

    assert "does not fit" not in caplog.text
    assert len(gatt.writes) == 1


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

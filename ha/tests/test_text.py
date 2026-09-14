"""The text platform, and §3's rule that it must not confirm.

The switch tests cover what happens when a device answers back. These cover the
case where it never will: a write-only object has no advertised value, so the
confirm/revert model has nothing to work with and §3 forbids applying it. An
entity that reverted here would drop back to a placeholder a second after every
write, which is the failure these exist to catch.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
import pytest

from custom_components.bthome_writable.coordinator import WriteFailed

from .conftest import service_info
from .test_switch import FAST_DEBOUNCE, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

ENTITY = "text.espruino_light_text"


async def set_text(hass: HomeAssistant, value: str) -> None:
    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": ENTITY, "value": value},
            blocking=True,
        )
        await settle(hass)


async def test_a_writable_text_object_becomes_a_text_entity(
    hass: HomeAssistant, radio
) -> None:
    await setup_device(hass, radio, "write-only-display")

    state = hass.states.get(ENTITY)
    assert state is not None
    # Nothing has been sent, and the device never says what it is showing.
    assert state.state == STATE_UNKNOWN


async def test_setting_it_writes_the_bytes_the_spec_describes(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """§4.2: the object id, then the length byte, then the text."""
    await setup_device(hass, radio, "write-only-display")
    await set_text(hass, "hi")

    assert mock_write == [bytes.fromhex("53026869")]
    assert hass.states.get(ENTITY).state == "hi"


async def test_the_value_survives_advertisements_that_cannot_confirm_it(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """The heart of it. The device keeps advertising the zero-length
    placeholder, which never matches what was sent; a confirm/revert entity
    would read that as failure and revert. §3 says it must not."""
    await setup_device(hass, radio, "write-only-display")
    await set_text(hass, "hello")

    for _ in range(3):
        radio.push(service_info("write-only-display"))
        await settle(hass)

    assert hass.states.get(ENTITY).state == "hello"


async def test_a_failed_write_does_not_claim_the_text_arrived(
    hass: HomeAssistant, radio
) -> None:
    """No confirmation is not the same as no feedback: a write that never left
    the host must not leave the entity asserting that it did."""
    await setup_device(hass, radio, "write-only-display")

    async def _fails(self, changes):
        raise WriteFailed("no adapter could reach it")

    with (
        patch(
            "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE",
            FAST_DEBOUNCE,
        ),
        patch(
            "custom_components.bthome_writable.coordinator."
            "BTHomeWritableCoordinator._write_now",
            _fails,
        ),
    ):
        await hass.services.async_call(
            "text",
            "set_value",
            {"entity_id": ENTITY, "value": "lost"},
            blocking=True,
        )
        await settle(hass)

    assert hass.states.get(ENTITY).state != "lost"

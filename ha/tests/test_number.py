"""The number platform: writable numeric objects, and where their bounds come from.

The interesting part is not that a slider appears. It is that its range, step
and unit are *derived* from BTHome's own table rather than declared here, and
that the range is the encoding's rather than the device's — a distinction
spec/PLATFORMS.md spells out and this pins down.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest

from .test_switch import FAST_DEBOUNCE, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

ENTITY = "number.espruino_light_moisture"


async def set_number(hass: HomeAssistant, value: float) -> None:
    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": ENTITY, "value": value},
            blocking=True,
        )
        await settle(hass)


async def test_a_writable_numeric_object_becomes_a_number(
    hass: HomeAssistant, radio
) -> None:
    await setup_device(hass, radio, "writable-setpoint")

    state = hass.states.get(ENTITY)
    assert state is not None
    # 0x109a = 4250, and moisture's factor is 0.01.
    assert float(state.state) == 42.5


async def test_the_bounds_come_from_bthomes_table_not_from_us(
    hass: HomeAssistant, radio
) -> None:
    """Moisture is unsigned 16-bit with a factor of 0.01, so the encoding can
    carry 0 … 655.35 in hundredths. The device's real limits may be narrower and
    BTHome gives it no way to say so."""
    await setup_device(hass, radio, "writable-setpoint")

    attributes = hass.states.get(ENTITY).attributes
    assert attributes["min"] == 0
    assert attributes["max"] == pytest.approx(655.35)
    assert attributes["step"] == pytest.approx(0.01)
    assert attributes["unit_of_measurement"] == "%"


async def test_setting_it_writes_the_scaled_little_endian_value(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """The same bytes as the shared fixture's `setpoint-to-60` write."""
    await setup_device(hass, radio, "writable-setpoint")
    await set_number(hass, 60.0)

    assert mock_write == [bytes.fromhex("147017")]


async def test_it_reverts_when_the_device_never_confirms(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """Unlike text, a numeric object is advertised back, so §6 applies to it in
    full: the optimistic value must not survive a device that never agrees.

    The optimistic phase itself is not observable here -- `async_block_till_done`
    waits for the confirmation task, so by the time the service call returns the
    window has already closed. The switch tests drive that phase directly; what
    this pins down is the outcome.
    """
    await setup_device(hass, radio, "writable-setpoint")
    await set_number(hass, 60.0)

    # The device kept advertising 42.5 throughout, so 60.0 was never confirmed.
    assert float(hass.states.get(ENTITY).state) == 42.5
    assert mock_write == [bytes.fromhex("147017")]

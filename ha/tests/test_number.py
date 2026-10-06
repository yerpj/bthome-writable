"""The number platform, and reading state back (§3.2), on the thermostat of §8.2."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest

from .conftest import UUID_TEMPLATE, service_info, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

TARGET = "number.espruino_light_temperature"
POWER = "switch.espruino_light_power"


async def test_a_numeric_entry_is_a_number_with_the_encodings_bounds(
    hass: HomeAssistant, radio, gatt
) -> None:
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    state = hass.states.get(TARGET)
    assert state is not None
    # 0x57: sint8, whole degrees.
    assert state.attributes["min"] == -128
    assert state.attributes["max"] == 127
    assert state.attributes["step"] == 1


async def test_setting_the_target_writes_one_object_to_entry_2(
    hass: HomeAssistant, radio, gatt
) -> None:
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    gatt.writes.clear()

    await hass.services.async_call(
        "number", "set_value", {"entity_id": TARGET, "value": 22}, blocking=True
    )
    await settle(hass)

    assert gatt.writes == [(UUID_TEMPLATE.format(2), bytes.fromhex("5716"))]
    assert float(hass.states.get(TARGET).state) == 22


async def test_a_device_with_a_settings_revision_is_read_on_first_sight(
    hass: HomeAssistant, radio, gatt
) -> None:
    """§3.2: after a restart the real state is fetched, not left unknown."""
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)

    assert float(hass.states.get(TARGET).state) == 20
    assert hass.states.get(POWER).state == "on"
    assert hass.states.get(TARGET).attributes.get("assumed_state") is not True


async def test_a_changed_settings_revision_triggers_a_re_read(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Someone turns the knob: the device bumps 0x65 and the receiver reads."""
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    reads_before = len(gatt.reads)

    gatt.readable[UUID_TEMPLATE.format(2)] = bytes.fromhex("5712")  # 18 °C
    payload = bytearray(bytes.fromhex("40000902c4096503ff021057"))
    payload[7] = 0x04  # settings revision 3 -> 4
    radio.push(service_info("thermostat", service_data=bytes(payload)))
    await settle(hass)

    assert len(gatt.reads) > reads_before
    assert float(hass.states.get(TARGET).state) == 18


async def test_a_re_read_that_fails_is_tried_again_on_a_later_advertisement(
    hass: HomeAssistant, radio, gatt
) -> None:
    """An Espruino device serves one central at a time: a read attempted while a
    phone holds the link fails, and must not count as having read the revision.
    Seen on hardware, where the state stayed stale until the next change."""
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)

    gatt.readable[UUID_TEMPLATE.format(2)] = bytes.fromhex("5712")
    payload = bytearray(bytes.fromhex("40000902c4096503ff021057"))
    payload[7] = 0x04
    gatt.fail_on_read = RuntimeError("device busy")
    radio.push(service_info("thermostat", service_data=bytes(payload)))
    await settle(hass)
    assert float(hass.states.get(TARGET).state) == 20

    # Not straight away: that would be a connection attempt per advertisement.
    gatt.fail_on_read = None
    radio.push(service_info("thermostat", service_data=bytes(payload)))
    await settle(hass)
    assert float(hass.states.get(TARGET).state) == 20

    with patch("custom_components.bthome_writable.coordinator.READ_RETRY", 0):
        radio.push(service_info("thermostat", service_data=bytes(payload)))
        await settle(hass)
    assert float(hass.states.get(TARGET).state) == 18


async def test_the_same_settings_revision_does_not_read_again(
    hass: HomeAssistant, radio, gatt
) -> None:
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    reads_before = len(gatt.reads)

    radio.push(service_info("thermostat"))
    await settle(hass)

    assert len(gatt.reads) == reads_before


async def test_advertising_during_a_read_does_not_cause_another_connection(
    hass: HomeAssistant, radio, gatt
) -> None:
    """D-087, reported by a user at their own site.

    After `changed()` the device kept advertising, as devices do, and Home
    Assistant connected two or three times for one revision -- getting the
    reading on the first attempt and connecting again anyway. The re-read loop
    continued on a flag set by *any* advertisement arriving during the read,
    rather than on the revision having moved past what was just read. A device
    advertises every second or so and a read takes a connection, so an ordinary
    read almost always had an advertisement land inside it.

    Invisible here because `test_the_same_settings_revision_does_not_read_again`
    pushes its advertisement *after* the read has settled.
    """
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)

    payload = bytearray(bytes.fromhex("40000902c4096503ff021057"))
    payload[7] = 0x04  # changed(): revision 3 -> 4
    connections_before = gatt.connections

    # The device goes on advertising while the receiver is reading it, which is
    # what a device does. Pushed from inside the read, so the timing is the
    # real one rather than one the test arranged afterwards.
    reading = gatt.read_gatt_char

    async def advertise_then_read(characteristic):
        radio.push(service_info("thermostat", service_data=bytes(payload)))
        return await reading(characteristic)

    gatt.read_gatt_char = advertise_then_read
    radio.push(service_info("thermostat", service_data=bytes(payload)))
    await settle(hass)

    assert gatt.connections - connections_before == 1, (
        "one revision, one connection -- the device serves one central at a time"
    )


async def test_a_read_of_the_wrong_type_is_not_shown_as_state(
    hass: HomeAssistant, radio, gatt
) -> None:
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("1e01")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    assert hass.states.get(TARGET).state == "unknown"

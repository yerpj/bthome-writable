"""The switch platform and the confirmation model of §6, end to end.

These are the tests that would catch a protocol regression from the Home
Assistant side: what bytes leave, and what the entity shows before, during and
after the device confirms.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bthome_writable.const import DOMAIN
from custom_components.bthome_writable.coordinator import WriteFailed

from .conftest import DEFAULT_ADDRESS, service_info, with_light

pytestmark = pytest.mark.usefixtures("custom_integration")

# Real sleeps, but short ones: the debounce and the confirmation window are
# both plain asyncio.sleep, which freezegun does not move.
FAST_DEBOUNCE = 0.01


@pytest.fixture(autouse=True)
def fast_confirmation(request):
    """Shrink the confirmation window for every test in this module.

    An entity that has written but not been confirmed keeps a task alive until
    the ceiling, and `async_block_till_done` waits for it -- so production
    values would make the suite wait a minute per write. The behaviour under
    test is the ordering and the conditions, not the durations.

    Opt out with `@pytest.mark.real_confirmation` where the durations are the
    point.
    """
    if request.node.get_closest_marker("real_confirmation"):
        yield
        return

    with (
        patch(
            "custom_components.bthome_writable.coordinator.CONFIRM_WINDOW_FLOOR", 0.05
        ),
        patch(
            "custom_components.bthome_writable.coordinator.CONFIRM_WINDOW_CEILING", 1.0
        ),
    ):
        yield


async def setup_device(
    hass: HomeAssistant, radio, fixture_name: str
) -> MockConfigEntry:
    """Bring one device up, seeded with a first advertisement."""
    radio.last = service_info(fixture_name)

    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=DEFAULT_ADDRESS, data={}, title="Espruino Light"
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def settle(hass: HomeAssistant, seconds: float = 0.05) -> None:
    await asyncio.sleep(seconds)
    await hass.async_block_till_done()


async def test_one_switch_per_writable_boolean(hass: HomeAssistant, radio) -> None:
    await setup_device(hass, radio, "espruino-single-light")

    state = hass.states.get("switch.espruino_light_light")
    assert state is not None
    assert state.state == STATE_ON


async def test_multi_instance_switches_are_numbered_like_the_sensors(
    hass: HomeAssistant, radio
) -> None:
    """`bthome-ble` names duplicate sensors light_1, light_2, ... -- the
    switches must use the same numbering or a three-light device is unusable."""
    await setup_device(hass, radio, "espruino-multi-instance")

    assert hass.states.get("switch.espruino_light_light_1").state == STATE_ON
    assert hass.states.get("switch.espruino_light_light_2").state == STATE_OFF
    assert hass.states.get("switch.espruino_light_light_3").state == STATE_ON


async def test_turning_off_writes_the_payload_the_spec_describes(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """§4.2, and the same bytes as the shared fixture's `light-off` write."""
    await setup_device(hass, radio, "espruino-single-light")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        await settle(hass)

    assert [payload.hex() for payload in mock_write] == ["1e00"]


async def test_a_write_carries_every_writable_object_not_just_the_changed_one(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """Write-all is the whole protocol: the untouched lights are resent at
    their advertised values, not omitted."""
    await setup_device(hass, radio, "espruino-multi-instance")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light_3"},
            blocking=True,
        )
        await settle(hass)

    assert [payload.hex() for payload in mock_write] == ["1e011e001e00"]


async def test_the_entity_shows_the_new_value_before_the_device_confirms(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """§6.4: optimistic, so the UI does not look broken for an interval.

    Asserted immediately after the call and before yielding to the loop: the
    Home Assistant test harness collapses `asyncio.sleep`, so anything that
    lets the loop run also expires the confirmation window.
    """
    await setup_device(hass, radio, "espruino-single-light")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )

    # No confirming advertisement has arrived, yet the entity already reads off.
    assert hass.states.get("switch.espruino_light_light").state == STATE_OFF


async def test_the_advertisement_confirms_the_write(
    hass: HomeAssistant, radio, mock_write
) -> None:
    await setup_device(hass, radio, "espruino-single-light")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        await settle(hass)

    radio.push(with_light("espruino-single-light", on=False, time=1.0))
    await hass.async_block_till_done()

    assert hass.states.get("switch.espruino_light_light").state == STATE_OFF


async def test_an_unconfirmed_write_reverts(
    hass: HomeAssistant, radio, mock_write, caplog
) -> None:
    """§6.4: advertising is the source of truth, so an entity that was never
    confirmed must go back to what the device actually says."""
    await setup_device(hass, radio, "espruino-single-light")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        assert hass.states.get("switch.espruino_light_light").state == STATE_OFF

        # The device keeps advertising, but never the value that was written:
        # it was heard from, and it did not obey.
        for index in range(4):
            await asyncio.sleep(0.1)
            radio.push(service_info("espruino-single-light", time=float(index + 1)))
        await settle(hass, 1.2)

    assert hass.states.get("switch.espruino_light_light").state == STATE_ON
    assert "did not advertise the written value" in caplog.text


async def test_rapid_toggles_coalesce_into_one_write(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """A spammed toggle -- or a dragged slider, later -- must not turn into a
    burst of connections."""
    await setup_device(hass, radio, "espruino-single-light")

    with patch("custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", 0.1):
        for service in ("turn_off", "turn_on", "turn_off"):
            await hass.services.async_call(
                "switch",
                service,
                {"entity_id": "switch.espruino_light_light"},
                blocking=True,
            )
        await settle(hass, 0.3)

    assert [payload.hex() for payload in mock_write] == ["1e00"]


async def test_the_write_is_composed_from_the_latest_advertisement(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """Risk #8: a device reflashed with a different layout must not receive a
    write built from the layout Home Assistant saw at setup."""
    await setup_device(hass, radio, "espruino-single-light")

    # The device is reflashed: now three lights (the first one off).
    radio.push(with_light("espruino-multi-instance", on=False, time=1.0))
    await hass.async_block_till_done()

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        # The entity keeps the id it was registered under; Home Assistant entity
        # ids are stable by design, so a device that grows extra instances does
        # not get its existing ones renamed.
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        await settle(hass)

    # Three objects, not one: composed from what the device advertises now,
    # with the two untouched instances resent at their current values.
    assert [payload.hex() for payload in mock_write] == ["1e011e001e01"]


async def test_a_write_only_object_gets_no_switch(hass: HomeAssistant, radio) -> None:
    """§3: a display is not a switch, and must not be offered as one."""
    await setup_device(hass, radio, "write-only-display")

    assert not [
        state
        for state in hass.states.async_all("switch")
        if state.entity_id.startswith("switch.espruino")
    ]


async def test_the_entity_goes_unavailable_when_the_device_stops_advertising(
    hass: HomeAssistant, radio
) -> None:
    await setup_device(hass, radio, "espruino-single-light")
    assert hass.states.get("switch.espruino_light_light").state == STATE_ON

    radio.vanish()
    await hass.async_block_till_done()

    assert hass.states.get("switch.espruino_light_light").state == STATE_UNAVAILABLE


async def test_the_device_merges_with_the_core_bthome_device_card(
    hass: HomeAssistant, radio
) -> None:
    """One card in the UI, mixing core BTHome's sensors with our switches.

    The merge is by Bluetooth connection identity, which is why the entity's
    DeviceInfo carries `connections` and no identifiers of its own.
    """
    entry = await setup_device(hass, radio, "espruino-single-light")

    registry = dr.async_get(hass)
    device = registry.async_get_device(
        connections={(dr.CONNECTION_BLUETOOTH, DEFAULT_ADDRESS)}
    )
    assert device is not None
    assert entry.entry_id in device.config_entries


@pytest.mark.real_confirmation
async def test_the_confirmation_window_follows_the_advertising_interval(
    hass: HomeAssistant, radio
) -> None:
    """D-007: a device advertising every 20 s must not be reverted after 5."""
    entry = await setup_device(hass, radio, "espruino-single-light")
    coordinator = entry.runtime_data

    assert coordinator.confirm_window == 5.0  # the floor, nothing observed yet

    for index in range(1, 12):
        radio.push(service_info("espruino-single-light", time=index * 20.0))
    await hass.async_block_till_done()

    assert coordinator.confirm_window == pytest.approx(40.0, abs=2.0)


async def test_a_write_that_never_reaches_the_device_reverts_at_once(
    hass: HomeAssistant, radio, caplog
) -> None:
    """No point waiting out the confirmation window for a write that failed.

    The window measures how long the device takes to refresh its advertising;
    if the write never arrived there is nothing to wait for, and leaving the
    entity showing a value that was never sent is the worst of both.
    """
    await setup_device(hass, radio, "espruino-single-light")

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
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        await settle(hass)

    assert hass.states.get("switch.espruino_light_light").state == STATE_ON
    assert "did not reach the device" in caplog.text


async def test_the_confirmation_window_opens_when_the_write_lands(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """The window must start when the device has been told, not when queued.

    Measured on hardware: with the window opened at queue time, the debounce,
    the connection setup and the disconnect were all inside it. On a host with
    one Bluetooth adapter -- which cannot scan while connected -- they ate most
    of a five-second window before the device could possibly be confirmed, and
    the entity visibly bounced: on, off, then on again.
    """
    entry = await setup_device(hass, radio, "espruino-single-light")
    coordinator = entry.runtime_data

    events: list[str] = []
    coordinator.async_add_write_listener(
        lambda positions, error: events.append(f"delivered:{sorted(positions)}")
    )

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        # The service call has returned and the entity already shows the new
        # value -- but the write is still only queued, so nothing was delivered.
        assert events == []
        assert hass.states.get("switch.espruino_light_light").state == STATE_OFF

        await settle(hass)

    assert events == ["delivered:[2]"]
    assert [payload.hex() for payload in mock_write] == ["1e00"]


async def test_a_deaf_host_waits_out_the_ceiling_instead_of_the_window(
    hass: HomeAssistant, radio, mock_write, caplog
) -> None:
    """D-011: reverting takes evidence, not just elapsed time.

    A host with one Bluetooth adapter cannot scan while it is connected and
    takes seconds to resume, so the window can expire without a single
    advertisement having arrived — a verdict on no evidence, and the device
    may well have obeyed. So an unheard device holds its optimistic value all
    the way to the ceiling rather than being written off after the window.

    The log line carries both numbers, which is what makes the two cases
    distinguishable here: the harness collapses `asyncio.sleep`, so wall-clock
    timing tells us nothing.
    """
    await setup_device(hass, radio, "espruino-single-light")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        # The radio stays silent throughout.
        await settle(hass, 0.3)

    assert hass.states.get("switch.espruino_light_light").state == STATE_ON
    assert "0 advertisement(s) heard since the write" in caplog.text
    assert "within 1.0 s" in caplog.text, "should have waited out the ceiling"


async def test_a_heard_device_is_written_off_after_the_window_not_the_ceiling(
    hass: HomeAssistant, radio, mock_write, caplog
) -> None:
    """The other half of D-011: once the device has been heard from and still
    has not obeyed, there is nothing left to wait for."""
    await setup_device(hass, radio, "espruino-single-light")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        for index in range(4):
            await asyncio.sleep(0.05)
            radio.push(service_info("espruino-single-light", time=float(index + 1)))
        await settle(hass, 0.3)

    assert hass.states.get("switch.espruino_light_light").state == STATE_ON
    assert "0 advertisement(s)" not in caplog.text
    assert "within 1.0 s" not in caplog.text, "should not have needed the ceiling"


async def test_a_single_click_is_not_delayed_by_the_debounce(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """Leading edge, not trailing (D-015).

    Deliberately does not shrink WRITE_DEBOUNCE: with a trailing debounce the
    write would still be waiting here, which is exactly the quarter second
    every single click used to pay to save a connection in the rare case of a
    burst.
    """
    await setup_device(hass, radio, "espruino-single-light")

    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": "switch.espruino_light_light"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert [payload.hex() for payload in mock_write] == ["1e00"]


async def test_re_asserting_the_advertised_state_writes_nothing(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """The device already says it is on; telling it so costs a connection.

    An automation re-asserting state on a schedule is a normal thing to write,
    and on this transport each one is several seconds of radio.
    """
    await setup_device(hass, radio, "espruino-single-light")
    assert hass.states.get("switch.espruino_light_light").state == STATE_ON

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        await settle(hass)

    assert mock_write == []


async def test_a_write_only_object_is_never_suppressed(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """A trigger has no advertised value, and firing it twice is the point."""
    await setup_device(hass, radio, "multi-instance-and-display")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        for _ in range(2):
            await hass.services.async_call(
                "switch",
                "turn_on",
                {"entity_id": "switch.espruino_light_light_1"},
                blocking=True,
            )
            await settle(hass)

    # Both went out, even though neither changed anything the device advertises.
    assert len(mock_write) == 2


async def test_a_changed_layout_drops_the_cached_gatt_table(
    hass: HomeAssistant, radio
) -> None:
    """Reflashing a device rebuilds its GATT table (D-012, D-018).

    The host's cached copy is then wrong in the silent way: the next write
    reports success and does nothing. Noticing it from the advertising costs
    nothing and saves the user their first command after an update.
    """
    entry = await setup_device(hass, radio, "espruino-single-light")
    coordinator = entry.runtime_data

    cleared: list[str] = []

    async def _clear(self):
        cleared.append(self.address)

    with patch(
        "custom_components.bthome_writable.coordinator."
        "BTHomeWritableCoordinator.async_clear_service_cache",
        _clear,
    ):
        # Same device, same layout: nothing to do.
        radio.push(service_info("espruino-single-light", time=1.0))
        await hass.async_block_till_done()
        assert cleared == []

        # Reflashed: a different set of objects, so a different GATT table.
        radio.push(service_info("espruino-multi-instance", time=2.0))
        await hass.async_block_till_done()

    assert cleared == [coordinator.address]


async def test_an_unconfirmed_write_can_be_sent_again(
    hass: HomeAssistant, radio, mock_write
) -> None:
    """A write that was not confirmed must remain repeatable.

    Suppressing a repeat of the last payload is right *within* a burst, and
    wrong across one: it says what was sent, not what the device did, and a
    write can be delivered and do nothing (D-012). Remembering it turned a
    transient failure into a permanent one — the receiver kept refusing to
    resend the value the device had never taken.
    """
    await setup_device(hass, radio, "espruino-single-light")

    with patch(
        "custom_components.bthome_writable.coordinator.WRITE_DEBOUNCE", FAST_DEBOUNCE
    ):
        # Ask for off; the device never confirms it, so it stays advertising on.
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        await settle(hass, 0.3)
        assert [p.hex() for p in mock_write] == ["1e00"]

        # Asking again must send it again, not decide it was already done.
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.espruino_light_light"},
            blocking=True,
        )
        await settle(hass, 0.3)

    assert [p.hex() for p in mock_write] == ["1e00", "1e00"]

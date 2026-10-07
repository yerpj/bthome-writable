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


async def test_the_controls_exist_before_the_device_is_heard_from(
    hass: HomeAssistant, radio, gatt
) -> None:
    """A restart while the device is asleep used to leave it with no entities at
    all, because they were built only once an advertisement had been parsed. An
    automation naming one then breaks; an unavailable one merely waits.

    The declaration is a cache, never authority — the first advertisement
    replaces it — so this only has to be right about existence.
    """
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bthome_writable.const import CONF_DECLARATION, DOMAIN

    radio.last = None  # nothing on the air, as after a restart at night
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEFAULT_ADDRESS,
        data={CONF_DECLARATION: {"layout": [0x1E], "settings_revision": None}},
        title="Espruino Light",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(LIGHT)
    assert state is not None, "the control must exist even before an advertisement"
    assert state.state == STATE_UNAVAILABLE


async def test_what_the_device_declares_is_written_down(
    hass: HomeAssistant, radio, gatt
) -> None:
    """So the next startup has it. Stored when it changes, not on every packet."""
    from custom_components.bthome_writable.const import CONF_DECLARATION

    entry = await setup_device(hass, radio, "single-light")
    await settle(hass)

    stored = entry.data.get(CONF_DECLARATION)
    assert stored is not None
    assert stored["layout"] == [0x1E]


async def test_an_entry_that_changes_type_does_not_collide(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Entry 1 as a light and entry 1 as something else are different controls.

    The unique id used to be the address and the entry number alone, so new
    firmware that changed an entry's object ID built a second entity claiming
    the first one's identity — "Platform does not generate unique IDs", and
    neither control works (found in review).
    """
    from custom_components.bthome_writable.entity import BTHomeWritableEntity
    from custom_components.bthome_writable.protocol import WritableEntry

    coordinator = (await setup_device(hass, radio, "single-light")).runtime_data
    light = BTHomeWritableEntity(coordinator, WritableEntry(entry=1, object_id=0x1E))
    other = BTHomeWritableEntity(coordinator, WritableEntry(entry=1, object_id=0x10))

    assert light.unique_id != other.unique_id


async def test_the_device_name_is_not_fought_over(
    hass: HomeAssistant, radio, gatt
) -> None:
    """D-089, reported by Gordon: the card's title flickered.

    Both integrations contribute to the same device, so asserting a name means
    whichever writes last wins -- core BTHome calls it "Puck.js c1c3 C1C3" and
    this called it "Puck.js c1c3". `default_name` applies only when the device
    has no name yet, so core BTHome's survives and ours still covers a device
    that declares writable entries and advertises no sensors at all.
    """
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)
    entry = await setup_device(hass, radio, "single-light")

    device = registry.async_get_device(
        connections={(dr.CONNECTION_BLUETOOTH, DEFAULT_ADDRESS)}
    )
    assert device is not None
    assert device.name == "Espruino Light", "named when nothing else named it"

    # Now something else does name it, as core BTHome would.
    registry.async_update_device(device.id, name="Espruino Light 1F2B")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert (
        registry.async_get_device(
            connections={(dr.CONNECTION_BLUETOOTH, DEFAULT_ADDRESS)}
        ).name
        == "Espruino Light 1F2B"
    ), "and does not take it back"


async def test_a_control_whose_entry_changed_type_refuses_to_write(
    hass: HomeAssistant, radio, gatt
) -> None:
    """D-083. New firmware can turn entry 1 from a light into a text. Nothing
    removes the entities built for the old layout, so the stale switch stayed
    *operable*: it handed its value to the new entry's encoder and produced
    `53 01` -- a text object claiming one character and carrying none -- which
    §4.2 acknowledged before the device refused it, so Home Assistant reported
    success and showed the switch as on.

    The existing layout-change test only ever changed the *number* of entries,
    which is why this went unseen.
    """
    from homeassistant.exceptions import HomeAssistantError

    await setup_device(hass, radio, "single-light")
    assert hass.states.get(LIGHT) is not None

    # Same entry number, different object: a light becomes a display.
    radio.push(service_info("single-light", service_data=bytes.fromhex("400009ff0153")))
    await hass.async_block_till_done()

    state = hass.states.get(LIGHT)
    assert state is not None and state.state == "unavailable", (
        "a control for a layout the device has replaced must not look operable"
    )

    # Home Assistant drops a service call aimed at an unavailable entity, so
    # being unavailable already stops the ordinary path.
    before = list(gatt.writes)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    assert gatt.writes == before, "nothing reached the wire"

    # And the write path refuses on its own, for any caller that does not go
    # through entity extraction. Belt and braces, because the failure this
    # guards against is silent: the device acknowledges before validating.
    from custom_components.bthome_writable.switch import BTHomeWritableSwitch

    stale = next(
        entity
        for entity in hass.data["entity_components"]["switch"].entities
        if isinstance(entity, BTHomeWritableSwitch)
    )
    with pytest.raises(HomeAssistantError, match="no longer declares entry"):
        await stale.async_apply(b"")
    assert gatt.writes == before


async def test_an_entity_registered_before_the_object_id_joined_the_id_is_carried_over(
    hass: HomeAssistant, radio, gatt
) -> None:
    """D-078. The object ID joined the unique id so an entry that changes type
    cannot collide with what it used to be. Without a migration that orphans
    every entity already registered — the old row is never claimed again, and
    the live one takes a new entity_id with a `_2` on the end, which breaks
    every automation naming it. Found on the bench; a fresh test registry has
    nothing to orphan, so it needs saying here deliberately.
    """
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bthome_writable.const import CONF_DECLARATION, DOMAIN

    registry = er.async_get(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEFAULT_ADDRESS,
        data={CONF_DECLARATION: {"layout": [0x1E], "settings_revision": None}},
        title="Espruino Light",
    )
    entry.add_to_hass(hass)
    old = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{DEFAULT_ADDRESS}-1",  # the pre-D-069 identity
        config_entry=entry,
        suggested_object_id="espruino_light_light",
    )

    radio.last = service_info("single-light")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    carried = registry.async_get(old.entity_id)
    assert carried is not None, "the entity keeps its id rather than being orphaned"
    assert carried.unique_id == f"{DEFAULT_ADDRESS}-e1-1e"
    assert hass.states.get(LIGHT) is not None
    assert hass.states.get(f"{LIGHT}_2") is None, "and no duplicate appears beside it"


async def test_an_entry_that_never_stored_a_declaration_still_migrates(
    hass: HomeAssistant, radio, gatt
) -> None:
    """The nice!nano half of D-078. An entry created before D-069 has no stored
    declaration, so a migration that reads only the stored copy returns early
    and orphans the entity anyway -- which is what the bench showed, with the
    live row at `_2` and the original unavailable for ever. The layout is known
    one line earlier than it looks: the last advertisement the stack already
    holds is absorbed during setup, so the migration runs off that instead.
    """
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bthome_writable.const import DOMAIN

    registry = er.async_get(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEFAULT_ADDRESS,
        data={},  # nothing stored: this entry predates D-069
        title="Espruino Light",
    )
    entry.add_to_hass(hass)
    old = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{DEFAULT_ADDRESS}-1",
        config_entry=entry,
        suggested_object_id="espruino_light_light",
    )

    radio.last = service_info("single-light")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(old.entity_id).unique_id == f"{DEFAULT_ADDRESS}-e1-1e"
    assert hass.states.get(f"{LIGHT}_2") is None, "no duplicate beside it"


async def test_a_leftover_row_does_not_collide_its_way_into_a_failed_setup(
    hass: HomeAssistant, radio, gatt
) -> None:
    """A registry that has seen several firmware layouts holds rows for all of
    them. Migrating one onto an identity something else already answers to
    fails the whole config entry — which is what happened on the bench, and the
    device lost every control rather than one stale row (D-078)."""
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.bthome_writable.const import CONF_DECLARATION, DOMAIN

    registry = er.async_get(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DEFAULT_ADDRESS,
        data={CONF_DECLARATION: {"layout": [0x1E], "settings_revision": None}},
        title="Espruino Light",
    )
    entry.add_to_hass(hass)
    # The live identity, and a leftover that would migrate onto it.
    registry.async_get_or_create(
        "switch", DOMAIN, f"{DEFAULT_ADDRESS}-e1-1e", config_entry=entry
    )
    stale = registry.async_get_or_create(
        "switch", DOMAIN, f"{DEFAULT_ADDRESS}-1", config_entry=entry
    )

    radio.last = service_info("single-light")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id).unique_id == f"{DEFAULT_ADDRESS}-1"

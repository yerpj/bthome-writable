"""Config flow: discovery, confirmation, and the aborts that matter.

The `not_supported` abort is the load-bearing one. This integration matches the
same service UUID as core BTHome, so it sees every BTHome device on the air;
aborting on the ones without a declaration is what keeps a user's plain BTHome
sensors from being offered a second time.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.config_entries import (
    SOURCE_BLUETOOTH,
    SOURCE_RECONFIGURE,
    SOURCE_USER,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.bthome_writable.const import CONF_BINDKEY, DOMAIN

from .conftest import DEFAULT_ADDRESS, service_info

pytestmark = pytest.mark.usefixtures("custom_integration")


async def start_discovery(hass: HomeAssistant, fixture_name: str, **kwargs):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=service_info(fixture_name, **kwargs),
    )


async def test_a_writable_device_is_offered(hass: HomeAssistant) -> None:
    result = await start_discovery(hass, "single-light")

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["count"] == "1"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "A4:C1:38:8E:1F:2B"


async def test_a_plain_bthome_device_is_not_offered(hass: HomeAssistant) -> None:
    """The whole point of the shared-UUID abort."""
    result = await start_discovery(hass, "plain-bthome-no-declaration")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_a_rotating_devices_sensor_packet_is_not_offered(
    hass: HomeAssistant,
) -> None:
    """§2.2: a packet without the declaration says nothing about writability.

    Seeing one must not make the integration conclude the device is ordinary,
    nor that it is writable — it simply aborts, and the declaration packet on
    the next rotation slot starts the flow properly.
    """
    result = await start_discovery(hass, "rotation-sensor-packet")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_a_declaration_listing_nothing_is_not_offered(
    hass: HomeAssistant,
) -> None:
    result = await start_discovery(hass, "empty-declaration")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_writable"


async def test_a_declaration_of_types_this_receiver_cannot_offer_is_not_offered(
    hass: HomeAssistant,
) -> None:
    """§2.1: unknown and forbidden entries are counted but never offered, so a
    device declaring only those has nothing for the user."""
    result = await start_discovery(
        hass, "single-light", service_data=bytes.fromhex("400001ff029900")
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_writable"


async def test_unknown_entries_are_not_counted_as_offered(hass: HomeAssistant) -> None:
    result = await start_discovery(hass, "unknown-entry-type")

    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["count"] == "2"


async def test_a_multi_instance_device_reports_every_writable_object(
    hass: HomeAssistant,
) -> None:
    result = await start_discovery(hass, "two-lights-and-display")

    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["count"] == "3"


async def test_the_same_device_is_not_offered_twice(hass: HomeAssistant) -> None:
    result = await start_discovery(hass, "single-light")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await start_discovery(hass, "single-light")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_the_user_step_offers_nothing_when_nothing_is_on_the_air(
    hass: HomeAssistant,
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_the_user_step_lists_writable_devices_only(hass: HomeAssistant) -> None:
    """The escape hatch for a dismissed discovery card.

    It lists what the Bluetooth stack has already heard rather than asking for
    a MAC, so it stays zero-config (rule 4) -- and it must filter out plain
    BTHome devices exactly as the discovery path does.
    """
    writable = service_info("single-light")
    plain = service_info(
        "plain-bthome-no-declaration", address="AA:BB:CC:DD:EE:FF", name="Plain BTHome"
    )

    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=[writable, plain],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        choices = result["data_schema"].schema[CONF_ADDRESS].container
        assert set(choices) == {writable.address}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ADDRESS: writable.address}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == writable.address


async def test_the_user_step_hides_devices_already_configured(
    hass: HomeAssistant,
) -> None:
    result = await start_discovery(hass, "single-light")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=[service_info("single-light")],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


# A sealed advertisement of the same device, taken from the shared vectors
# rather than copied: battery and a declaration listing one light, under the
# published bindkey. Copying it was wrong within the hour -- the declaration
# gained its length byte and the ciphertext moved with it (rule 7).
_VECTOR = next(
    v
    for v in json.loads(
        (
            Path(__file__).resolve().parents[2] / "test-vectors" / "test-vectors.json"
        ).read_text(encoding="utf-8")
    )["vectors"]
    if v["name"] == "adv-single-light"
)
SEALED = _VECTOR["payload"]
BINDKEY = _VECTOR["bindkey"]


def sealed_info():
    return service_info("single-light", service_data=bytes.fromhex(SEALED))


async def configured_without_a_key(hass: HomeAssistant):
    """An entry created while the device was advertising in clear.

    Not contrived: a latency campaign deploys an unencrypted build, and the
    entry made afterwards holds no key (D-079).
    """
    result = await start_discovery(hass, "single-light")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert CONF_BINDKEY not in entry.data
    return entry


async def reconfigure(hass: HomeAssistant, entry, discovered):
    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=discovered,
    ):
        return await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        )


async def test_a_device_that_gained_a_key_can_be_told_without_being_removed(
    hass: HomeAssistant,
) -> None:
    """D-079. Before this step the only way to give a configured device a key
    was to delete it and add it again, which discards every entity id and so
    every automation naming one. The symptom it fixes is silent: a receiver
    with no key writes in clear, the device discards the payload, and §4.2
    has already acknowledged the write.
    """
    entry = await configured_without_a_key(hass)

    result = await reconfigure(hass, entry, [sealed_info()])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    assert result["description_placeholders"]["state"] == "encrypted"

    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=[sealed_info()],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BINDKEY: BINDKEY}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_BINDKEY] == BINDKEY
    assert entry.unique_id == DEFAULT_ADDRESS, "the device is the same device"


async def test_the_key_is_proved_against_the_air_before_it_is_accepted(
    hass: HomeAssistant,
) -> None:
    """The same promise the initial flow makes: a typo is caught here rather
    than becoming a device that configures and then never works."""
    entry = await configured_without_a_key(hass)
    result = await reconfigure(hass, entry, [sealed_info()])

    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=[sealed_info()],
    ):
        wrong = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BINDKEY: "00" * 16}
        )
        assert wrong["errors"] == {"base": "wrong_bindkey"}

        short = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BINDKEY: "abcd"}
        )
        assert short["errors"] == {"base": "invalid_bindkey"}

    assert CONF_BINDKEY not in entry.data


async def test_a_device_that_stopped_encrypting_can_have_its_key_cleared(
    hass: HomeAssistant,
) -> None:
    """The inverse of the same accident, and the one D-042 could only answer by
    telling the user to delete the device: an empty field removes the key."""
    result = await start_discovery(hass, "single-light")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    entry = result["result"]
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_BINDKEY: BINDKEY}
    )

    result = await reconfigure(hass, entry, [service_info("single-light")])
    assert result["description_placeholders"]["state"] == "unencrypted"

    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=[service_info("single-light")],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BINDKEY: ""}
        )

    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_BINDKEY] is None


async def test_an_encrypted_device_cannot_have_its_key_cleared(
    hass: HomeAssistant,
) -> None:
    """Clearing it would send writes in clear to a device that discards them."""
    entry = await configured_without_a_key(hass)
    result = await reconfigure(hass, entry, [sealed_info()])

    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=[sealed_info()],
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_BINDKEY: ""}
        )

    assert result["errors"] == {"base": "bindkey_required"}


async def test_a_key_is_not_accepted_for_a_device_that_is_not_on_the_air(
    hass: HomeAssistant,
) -> None:
    """Nothing to check it against, and a key accepted unproved is the failure
    this step exists to prevent."""
    entry = await configured_without_a_key(hass)
    result = await reconfigure(hass, entry, [])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_on_the_air"

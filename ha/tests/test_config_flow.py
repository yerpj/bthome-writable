"""Config flow: discovery, confirmation, and the aborts that matter.

The `not_supported` abort is the load-bearing one. This integration matches the
same service UUID as core BTHome, so it sees every BTHome device on the air;
aborting on the ones without a declaration is what keeps a user's plain BTHome
sensors from being offered a second time.
"""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_BLUETOOTH, SOURCE_USER
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.bthome_writable.const import DOMAIN

from .conftest import service_info

pytestmark = pytest.mark.usefixtures("custom_integration")


async def start_discovery(hass: HomeAssistant, fixture_name: str, **kwargs):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_BLUETOOTH},
        data=service_info(fixture_name, **kwargs),
    )


async def test_a_writable_device_is_offered(hass: HomeAssistant) -> None:
    result = await start_discovery(hass, "espruino-single-light")

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
    """§2.1: a packet without the declaration says nothing about writability.

    Seeing one must not make the integration conclude the device is ordinary,
    nor that it is writable — it simply aborts, and the declaration packet on
    the next rotation slot starts the flow properly.
    """
    result = await start_discovery(hass, "rotation-sensor-packet")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_a_declaration_marking_nothing_is_not_offered(
    hass: HomeAssistant,
) -> None:
    result = await start_discovery(hass, "empty-bitmask")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "nothing_writable"


async def test_a_malformed_declaration_is_not_offered(hass: HomeAssistant) -> None:
    """declaration-not-last violates a MUST, so the device is not usable."""
    result = await start_discovery(hass, "declaration-not-last")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_a_multi_instance_device_reports_every_writable_object(
    hass: HomeAssistant,
) -> None:
    result = await start_discovery(hass, "espruino-multi-instance")

    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["count"] == "3"


async def test_the_same_device_is_not_offered_twice(hass: HomeAssistant) -> None:
    result = await start_discovery(hass, "espruino-single-light")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    result = await start_discovery(hass, "espruino-single-light")
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
    writable = service_info("espruino-single-light")
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
    result = await start_discovery(hass, "espruino-single-light")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    with patch(
        "custom_components.bthome_writable.config_flow.async_discovered_service_info",
        return_value=[service_info("espruino-single-light")],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"

"""Config flow for BTHome Writable.

Zero configuration by design (CLAUDE.md rule 4): the device describes itself in
its advertising, so the flow has nothing to ask beyond confirmation — and, from
Phase 3, a bindkey for encrypted devices.
"""

from __future__ import annotations

import logging
from typing import Any

from habluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
import voluptuous as vol

from .const import BTHOME_SERVICE_UUID, DOMAIN
from .protocol import Declaration, ProtocolError, parse_declaration

_LOGGER = logging.getLogger(__name__)


def declaration_from(service_info: BluetoothServiceInfoBleak) -> Declaration | None:
    """The device's declaration, or None if it is a plain BTHome device."""
    payload = service_info.service_data.get(BTHOME_SERVICE_UUID)
    if not payload or len(payload) < 2:
        return None
    try:
        # Skip the device-information byte; the rest is the object stream.
        return parse_declaration(payload[1:])
    except ProtocolError as error:
        _LOGGER.debug(
            "%s: advertising carries a malformed declaration: %s",
            service_info.address,
            error,
        )
        return None


class BTHomeWritableConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discover and confirm a writable BTHome device."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._declaration: Declaration | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device seen on the BTHome service UUID.

        We match the same UUID as the core `bthome` integration, so this fires
        for every BTHome device on the air. Aborting with `not_supported` on the
        ones without a declaration is what keeps plain BTHome devices out of the
        user's discovery list — the standard mechanism for a shared UUID.
        """
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        declaration = declaration_from(discovery_info)
        if declaration is None:
            return self.async_abort(reason="not_supported")

        if not declaration.objects:
            # A declaration whose bitmask marks nothing, or marks only objects
            # that are not in the packet. Nothing to expose.
            return self.async_abort(reason="nothing_writable")

        self._discovery = discovery_info
        self._declaration = declaration
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm, showing what the device declared."""
        assert self._discovery is not None
        assert self._declaration is not None

        if user_input is not None:
            return self.async_create_entry(title=self._discovery.name, data={})

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": self._discovery.name,
                "address": self._discovery.address,
                "count": str(len(self._declaration.objects)),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup is not offered: devices announce themselves.

        A user with a writable device that HA has not discovered has a
        Bluetooth reachability problem, which a form cannot fix. Asking them to
        type a MAC would be the first step towards the manual-configuration
        trap that sank the Generic Bluetooth Integration.
        """
        return self.async_abort(reason="no_devices_found")

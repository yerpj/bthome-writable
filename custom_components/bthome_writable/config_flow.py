"""Config flow for BTHome Writable.

Zero configuration by design (CLAUDE.md rule 4): the device describes itself in
its advertising, so the flow has nothing to ask beyond confirmation — and, from
Phase 3, a bindkey for encrypted devices.
"""

from __future__ import annotations

import logging
from typing import Any

from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
import voluptuous as vol

from .const import BTHOME_SERVICE_UUID, CONF_BINDKEY, DOMAIN
from .protocol import (
    Declaration,
    ProtocolError,
    decrypt_advertising,
    is_encrypted,
    objects_at,
    parse_declaration,
)

_LOGGER = logging.getLogger(__name__)

BINDKEY_LENGTH = 32
"""A BTHome bindkey as the user meets it: 32 hex characters, 16 bytes."""


def service_data(service_info: BluetoothServiceInfoBleak) -> bytes | None:
    payload = service_info.service_data.get(BTHOME_SERVICE_UUID)
    return payload if payload and len(payload) >= 2 else None


def needs_bindkey(service_info: BluetoothServiceInfoBleak) -> bool:
    """Whether this device's advertising is sealed (§5).

    The device-information byte is the only thing readable without the key, so
    it is also the only thing this can be decided on.
    """
    payload = service_data(service_info)
    return payload is not None and is_encrypted(payload)


def declaration_from(
    service_info: BluetoothServiceInfoBleak, bindkey: bytes | None = None
) -> Declaration | None:
    """The device's declaration, or None if there is not one to be had.

    None covers three different situations on purpose, because the flow treats
    them the same: a plain BTHome device with nothing writable, an encrypted
    device whose key is wrong or missing, and a malformed declaration. In each
    case there is nothing this integration can offer.
    """
    payload = service_data(service_info)
    if payload is None:
        return None

    if is_encrypted(payload):
        if bindkey is None:
            return None
        objects = decrypt_advertising(payload, bindkey, service_info.address)
        if objects is None:
            return None
    else:
        # Past the device-information byte, and past the MAC when the flags say
        # the device put one there (§2.1).
        objects = payload[objects_at(payload) :]

    try:
        return parse_declaration(objects)
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
        self._bindkey: bytes | None = None
        self._candidates: dict[str, BluetoothServiceInfoBleak] = {}

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

        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": discovery_info.name}

        if needs_bindkey(discovery_info):
            # Nothing else about this device is readable yet: its declaration,
            # its objects and whether it has any are all inside the ciphertext.
            # The one question rule 4 allows is exactly this one.
            return await self.async_step_bindkey()

        declaration = declaration_from(discovery_info)
        if declaration is None:
            return self.async_abort(reason="not_supported")

        if not declaration.offered:
            # A declaration with no entries, or only entries this receiver
            # cannot offer (unknown or forbidden types). Nothing to expose.
            return self.async_abort(reason="nothing_writable")

        self._declaration = declaration
        return await self.async_step_confirm()

    async def async_step_bindkey(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the device's BTHome key, and prove it before accepting it.

        The key is checked by decrypting an advertisement the device has already
        sent, so a typo is caught here rather than becoming a device that pairs
        and then never works.
        """
        assert self._discovery is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            text = user_input[CONF_BINDKEY].strip().replace("-", "").replace(":", "")
            try:
                bindkey = bytes.fromhex(text)
            except ValueError:
                bindkey = b""
            if len(bindkey) * 2 != BINDKEY_LENGTH:
                errors["base"] = "invalid_bindkey"
            else:
                declaration = declaration_from(self._discovery, bindkey)
                if declaration is None:
                    errors["base"] = "wrong_bindkey"
                elif not declaration.offered:
                    return self.async_abort(reason="nothing_writable")
                else:
                    self._bindkey = bindkey
                    self._declaration = declaration
                    return await self.async_step_confirm()

        return self.async_show_form(
            step_id="bindkey",
            data_schema=vol.Schema({vol.Required(CONF_BINDKEY): str}),
            errors=errors,
            description_placeholders={
                "name": self._discovery.name,
                "address": self._discovery.address,
            },
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm, showing what the device declared."""
        assert self._discovery is not None
        assert self._declaration is not None

        if user_input is not None:
            data: dict[str, Any] = {}
            if self._bindkey is not None:
                data[CONF_BINDKEY] = self._bindkey.hex()
            return self.async_create_entry(title=self._discovery.name, data=data)

        self._set_confirm_only()
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "name": self._discovery.name,
                "address": self._discovery.address,
                "count": str(len(self._declaration.offered)),
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick from the writable devices already on the air.

        Nothing is typed here: the list is what the Bluetooth stack has already
        heard, filtered to devices carrying a declaration. This is the standard
        Home Assistant pattern and it exists for the user who dismissed the
        discovery card — without it they would be stuck, since a device only
        announces itself once.

        Still zero-config in the sense that matters (CLAUDE.md rule 4): no MAC
        to type, no YAML, nothing to look up. A device this list cannot show is
        a device Home Assistant cannot hear, which a form could not fix anyway.
        """
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            discovery = self._candidates[address]
            self._discovery = discovery

            if needs_bindkey(discovery):
                return await self.async_step_bindkey()

            declaration = declaration_from(discovery)
            if declaration is None or not declaration.offered:
                return self.async_abort(reason="not_supported")

            self._declaration = declaration
            return await self.async_step_confirm()

        configured = self._async_current_ids()
        self._candidates = {}
        for discovery in async_discovered_service_info(self.hass, connectable=True):
            if discovery.address in configured:
                continue
            # An encrypted device cannot be filtered on its declaration --
            # that is inside the ciphertext. It is offered on the strength of
            # announcing itself encrypted, and the bindkey step then decides
            # whether it has anything writable. Excluding them here was why an
            # encrypted device could be discovered but never added by hand.
            if needs_bindkey(discovery):
                self._candidates[discovery.address] = discovery
                continue
            declaration = declaration_from(discovery)
            if declaration is not None and declaration.offered:
                self._candidates[discovery.address] = discovery

        if not self._candidates:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            address: f"{discovery.name} ({address})"
                            for address, discovery in self._candidates.items()
                        }
                    )
                }
            ),
        )

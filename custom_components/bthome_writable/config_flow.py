"""Config flow for BTHome Writable.

Zero configuration by design (CLAUDE.md rule 4): the device describes itself in
its advertising, so the flow has nothing to ask beyond confirmation — and, from
Phase 3, a bindkey for encrypted devices.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components.bluetooth import async_discovered_service_info
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_ADDRESS
import voluptuous as vol

from .const import BTHOME_SERVICE_UUID, CONF_BINDKEY, DOMAIN, REAUTH_SERVICE_INFO
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
            return await self.async_step_get_encryption_key()

        declaration = declaration_from(discovery_info)
        if declaration is None:
            return self.async_abort(reason="not_supported")

        if not declaration.offered:
            # A declaration with no entries, or only entries this receiver
            # cannot offer (unknown or forbidden types). Nothing to expose.
            return self.async_abort(reason="nothing_writable")

        self._declaration = declaration
        return await self.async_step_confirm()

    async def async_step_get_encryption_key(
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
                errors[CONF_BINDKEY] = "expected_32_characters"
            else:
                declaration = declaration_from(self._discovery, bindkey)
                if declaration is None:
                    errors[CONF_BINDKEY] = "decryption_failed"
                elif not declaration.offered:
                    return self.async_abort(reason="nothing_writable")
                else:
                    self._bindkey = bindkey
                    self._declaration = declaration
                    if self.source == SOURCE_REAUTH:
                        # The device is already configured; only its key was
                        # wrong or missing. Nothing to confirm, and nothing else
                        # about the entry changes.
                        return self.async_update_reload_and_abort(
                            self._get_reauth_entry(),
                            data_updates={CONF_BINDKEY: bindkey.hex()},
                        )
                    return await self.async_step_confirm()

        return self.async_show_form(
            step_id="get_encryption_key",
            data_schema=vol.Schema(
                {vol.Required(CONF_BINDKEY): vol.All(str, vol.Strip)}
            ),
            errors=errors,
            description_placeholders={
                "name": self._discovery.name,
                "address": self._discovery.address,
            },
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Ask for a key again, because the device's packets stopped opening.

        Core `bthome` does exactly this, and it is the piece that was missing
        here: without it a key that goes wrong -- a device reflashed with
        encryption on, a key changed, an entry created while the device happened
        to be advertising in clear -- produces an integration that shows
        nothing, logs a warning nobody reads, and waits (D-082).

        The flow needs a live advertisement to check a key against, so it is
        looked up here rather than carried in `entry_data`: ours is raised from
        a packet that has just arrived, and the Bluetooth stack still has it.
        """
        address = self._get_reauth_entry().unique_id
        assert address is not None

        self._discovery = entry_data.get(REAUTH_SERVICE_INFO) or next(
            (
                info
                for info in async_discovered_service_info(self.hass, connectable=True)
                if info.address == address
            ),
            None,
        )
        if self._discovery is None:
            return self.async_abort(reason="not_on_the_air")

        if not needs_bindkey(self._discovery):
            # It is advertising in clear, so there is no key to get right. The
            # write path refuses to send a sealed write to it and says so
            # (D-042), which is a better place to deal with this than a form.
            return self.async_abort(reason="reauth_successful")

        self.context["title_placeholders"] = {"name": self._discovery.name}
        return await self.async_step_get_encryption_key()

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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change a configured device's encryption key without removing it.

        A device can gain or lose a bindkey long after it was added -- firmware
        reflashed, encryption turned on, a measurement campaign that deploys an
        unencrypted build. Until this step existed the only way to tell Home
        Assistant was to delete the device and add it again, which throws away
        every entity id and therefore every automation naming one.

        The symptom is also the worst kind: a receiver whose key does not match
        the device seals writes the device discards, or sends them in clear to a
        device that requires sealing, and section 4.2 acknowledges the write
        before validating it. Home Assistant reports success and nothing
        happens. That is D-079, found when a latency campaign left the bench in
        exactly this state.

        An empty key means the device no longer advertises encrypted -- the
        inverse case, and the one that needs no proof.
        """
        entry = self._get_reconfigure_entry()
        address = entry.unique_id
        assert address is not None
        errors: dict[str, str] = {}

        discovery = next(
            (
                info
                for info in async_discovered_service_info(self.hass, connectable=True)
                if info.address == address
            ),
            None,
        )
        if discovery is None:
            # Without an advertisement a key cannot be proved, and accepting one
            # unproved is how a device comes to pair and then never work.
            return self.async_abort(reason="not_on_the_air")

        if user_input is not None:
            text = user_input.get(CONF_BINDKEY, "").strip()
            text = text.replace("-", "").replace(":", "")
            if not text:
                if needs_bindkey(discovery):
                    errors[CONF_BINDKEY] = "bindkey_required"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_BINDKEY: None}
                    )
            else:
                try:
                    bindkey = bytes.fromhex(text)
                except ValueError:
                    bindkey = b""
                if len(bindkey) * 2 != BINDKEY_LENGTH:
                    errors[CONF_BINDKEY] = "expected_32_characters"
                elif declaration_from(discovery, bindkey) is None:
                    errors[CONF_BINDKEY] = "decryption_failed"
                else:
                    return self.async_update_reload_and_abort(
                        entry, data_updates={CONF_BINDKEY: bindkey.hex()}
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Optional(CONF_BINDKEY, default=""): vol.All(str, vol.Strip)}
            ),
            errors=errors,
            description_placeholders={
                "name": entry.title,
                "address": address,
                "state": ("encrypted" if needs_bindkey(discovery) else "unencrypted"),
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
                return await self.async_step_get_encryption_key()

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

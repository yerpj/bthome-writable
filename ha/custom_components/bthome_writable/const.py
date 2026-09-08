"""Constants for the BTHome Writable integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bthome_writable"

# BTHome service data UUID, shared with the core `bthome` integration.
BTHOME_SERVICE_UUID: Final = "0000fcd2-0000-1000-8000-00805f9b34fb"

# --- Protocol constants (see spec/PROTOCOL.md) -------------------------------
# Object ID carrying the writability declaration inside the BTHome service data.
DECLARATION_OBJECT_ID: Final = 0xFF

# BTHome device-information byte used in the AES-CCM nonce.
# 0x41 is BTHome v2's advertising value; writes use 0xFF so a captured
# advertisement can never validate as a write (and vice versa).
DEVICE_INFO_BYTE_ADVERTISING: Final = 0x41
DEVICE_INFO_BYTE_WRITE: Final = 0xFF

# --- Tunables ---------------------------------------------------------------
# [DECISION] confirmation timeout and connection cap defaults, see spec/decisions.md.
CONF_CONFIRM_TIMEOUT: Final = "confirm_timeout"
DEFAULT_CONFIRM_TIMEOUT: Final = 5.0
DEFAULT_MAX_CONNECTIONS: Final = 2
MIN_MTU: Final = 64

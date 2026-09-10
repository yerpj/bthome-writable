"""Constants for the BTHome Writable integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bthome_writable"

# BTHome service data UUID, shared with the core `bthome` integration. Matching
# on it means we see every BTHome device; the config flow aborts on the ones
# without a declaration so users never see plain BTHome devices offered twice.
BTHOME_SERVICE_UUID: Final = "0000fcd2-0000-1000-8000-00805f9b34fb"

# --- Protocol constants (see spec/PROTOCOL.md) -------------------------------
# Object ID carrying the writability declaration inside the BTHome service data.
DECLARATION_OBJECT_ID: Final = 0xFF

# GATT service and characteristic (§4.1, decisions.md D-001). Provisional until
# the first public release, frozen permanently after it.
SERVICE_UUID: Final = "2faa0001-3b0b-4b1a-9e2a-b4c2952e62f2"
WRITE_CHARACTERISTIC_UUID: Final = "2faa0002-3b0b-4b1a-9e2a-b4c2952e62f2"

# BTHome device-information byte used in the AES-CCM nonce (§5.1).
# 0x41 is the advertising value; writes use 0xFF so a captured advertisement can
# never validate as a write. Used from Phase 3 onwards.
DEVICE_INFO_BYTE_ADVERTISING: Final = 0x41
DEVICE_INFO_BYTE_WRITE: Final = 0xFF

# --- Confirmation model (§6, decisions.md D-007 and D-011) -------------------
# The window is adaptive: a floor, and two of the device's observed advertising
# intervals, so slowly advertising devices do not produce spurious reverts.
CONFIRM_WINDOW_FLOOR: Final = 5.0
CONFIRM_WINDOW_INTERVALS: Final = 2
CONFIRM_WINDOW_CEILING: Final = 60.0
"""An upper bound, so a device seen twice an hour cannot pin an entity
optimistically for half an hour."""

CONFIRM_ADVERTISEMENTS: Final = 2
"""How many advertisements must arrive after a write before an unconfirmed
value may be reverted.

Time alone is not enough. A host with a single Bluetooth adapter cannot scan
while it is connected, and takes seconds to resume afterwards, so the window
can expire without the receiver having heard the device even once — reverting
on the strength of having listened to nothing. Requiring a couple of actual
advertisements makes the rule what it was always meant to be: the device was
given two chances to say so and did not (D-011)."""

# --- Connection handling -----------------------------------------------------
CONF_MAX_CONNECTIONS: Final = "max_connections"
DEFAULT_MAX_CONNECTIONS: Final = 2
"""A typical ESPHome proxy offers three slots; two leaves room for an Espruino
UART/Web-IDE session (decisions.md D-003)."""

MIN_MTU: Final = 64
DEFAULT_MTU_PAYLOAD: Final = 20
"""What fits in a write at BLE's default 23-byte MTU. Most writes are a couple
of bytes, so the MTU is only worth asking about above this."""
WRITE_DEBOUNCE: Final = 0.25
"""Seconds to coalesce rapid changes -- a slider drag must produce one write,
not one per pixel."""

CONF_BINDKEY: Final = "bindkey"

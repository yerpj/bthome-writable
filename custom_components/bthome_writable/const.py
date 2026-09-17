"""Constants for the BTHome Writable integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "bthome_writable"

# BTHome service data UUID, shared with the core `bthome` integration. Matching
# on it means we see every BTHome device; the config flow aborts on the ones
# without a declaration so users never see plain BTHome devices offered twice.
BTHOME_SERVICE_UUID: Final = "0000fcd2-0000-1000-8000-00805f9b34fb"

# --- Protocol constants (see spec/PROTOCOL.md, version 2) --------------------
DECLARATION_OBJECT_ID: Final = 0xFF
"""The declaration: 0xFF followed by the writable entries' object IDs (§2.1)."""

PACKET_ID_OBJECT_ID: Final = 0x00

SETTINGS_REVISION_OBJECT_ID: Final = 0x65
"""BTHome's settings revision. A device advertising it has writable values that
can change by themselves, and readable characteristics to fetch them (§3.2)."""

# GATT (§4.1, decisions.md D-001, D-048). One base; the second group is 0000 for
# the service and the entry number, in hexadecimal, for each entry. Provisional
# until the first public release, frozen permanently after it.
UUID_TEMPLATE: Final = "2faa{:04x}-3b0b-4b1a-9e2a-b4c2952e62f2"
SERVICE_UUID: Final = UUID_TEMPLATE.format(0)

# The direction, carried in the AES-CCM nonce's device-information byte (§5.1).
DEVICE_INFO_BYTE_ADVERTISING: Final = 0x41
DEVICE_INFO_BYTE_WRITE: Final = 0xFF
DEVICE_INFO_BYTE_READ: Final = 0xFE

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
"""Seconds to let rapid changes pile up behind a write in flight -- a slider drag
must produce one follow-up write, not one per pixel."""

CONF_BINDKEY: Final = "bindkey"
CONF_WRITE_COUNTER: Final = "write_counter"

COUNTER_STRIDE: Final = 64
"""How far ahead of the write counter the persisted mark sits (§5.3).

Saving on every write would mean a config-entry update per command. Saving a
mark ahead of it and resuming *from the mark* gives up the values in between
rather than reusing them, which is the requirement: never send a counter the
device may already have accepted."""

RESYNC_JUMP: Final = 100_000
"""How far a resynchronisation moves the counter.

Far enough to clear any plausible drift in one step, and nothing compared with a
32-bit counter: at one write a second it would take a century to exhaust even
with a jump on every restart."""

ALLOW_PLAINTEXT_DOWNGRADE: Final = False
"""Whether a keyed device that advertises in clear may be written unsealed.

False refuses the write and says why. The alternative -- sending plaintext
because that is evidently what the device now speaks -- would make a stale
bindkey self-healing, at the cost of handing unsealed writes to anyone who can
make a keyed device look unencrypted. [DECISION] The owner may overturn this;
it is a receiver policy, not part of section 5.

The case is not hypothetical: it is how a Puck.js reflashed from the encrypted
example to the plain one stopped responding to Home Assistant entirely, with
nothing in the log (D-042)."""

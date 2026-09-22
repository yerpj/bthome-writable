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

# BTHome's device-information byte is a bitfield, not a value (§2.1). Reading
# it as a value is how this integration came to work with exactly one firmware:
# a sleepy encrypted device transmits 0x45 rather than 0x41, and comparing for
# equality called it unencrypted.
DEVICE_INFO_ENCRYPTED: Final = 1 << 0
DEVICE_INFO_MAC_INCLUDED: Final = 1 << 1
"""When set, the six bytes after the device-information byte are the device's
MAC, and the objects start seven bytes in rather than one. The MAC in the packet
is also the one the nonce uses, which matters for a device advertising under a
random address."""

DEVICE_INFO_BYTE_ADVERTISING: Final = 0x41
"""What the reference firmware transmits: BTHome v2, encrypted, nothing else.

Kept because the shared test vectors are written against it, and because §5.1
reserves the write and read values relative to it. Nothing in the receiver may
compare a real advertisement against it -- the byte that goes into the nonce is
the one the device transmitted, whatever flags it carries."""

# The direction, carried in the AES-CCM nonce's device-information byte (§5.1).
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

READ_RETRY: Final = 10.0
"""Seconds before a failed state read is tried again. An Espruino device serves
one central at a time, so a read can fail simply because a phone or the Web IDE
holds the link; the next advertisement after this retries it."""

EVENT_WRITE: Final = "bthome_writable_write"
"""Fired after each acknowledged write, with where its time went: `queued_ms`,
`connect_ms`, `write_ms`, `total_ms`. `connect_ms` is mostly the wait to catch
the device advertising, which is what its advertising interval buys or costs."""

CONF_BINDKEY: Final = "bindkey"
CONF_WRITE_COUNTER: Final = "write_counter"

COUNTER_STRIDE: Final = 64
"""How far ahead of the write counter the persisted mark sits (§5.3).

Saving on every write would mean a config-entry update per command. Saving a
mark ahead of it and resuming *from the mark* gives up the values in between
rather than reusing them, which is the requirement: never send a counter the
device may already have accepted."""

COUNTER_EPOCH_SEED: Final = True
"""Whether a write counter starts from the wall clock rather than from zero.

A device remembers the highest write counter it has accepted, in flash, and
refuses anything below it -- correctly, that is replay protection. A receiver
that starts again from zero therefore has every write refused, silently, because
§3 acknowledges a write before validating it. That happens whenever the config
entry is re-created: deleting and re-adding the device, restoring a backup older
than the counter, moving the device to another Home Assistant (D-063, found on
hardware with the device's mark at 100135 and the new entry at 0).

Seeding from the clock removes the whole class: wall time only moves forward, so
a counter seeded from it is above every counter any earlier receiver can have
sent, without having to ask the device anything. It is a forward jump, which
§5.3 requires a device to accept. The cost is counter space, and there is none
to speak of -- seconds since 1970 leave about 2.5 billion values inside 32
bits."""

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

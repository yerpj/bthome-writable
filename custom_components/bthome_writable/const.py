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

CONTROL_UUID_BASE: Final = 0x1000
"""Where the protocol's own characteristics start (§4.1).

`0001` to `0FFF` are entries, `1000` and above are the protocol's. A declaration
carries at most 255 entries, so the entry range has sixteen times the room it
can ever need, and a later control characteristic has somewhere obvious to go."""

COUNTER_UUID: Final = UUID_TEMPLATE.format(CONTROL_UUID_BASE)
"""Where a device reports the write counter it is at (D-075), if it offers it.

Write 8 random bytes, read back `seal(challenge || counter)` — the shape Zigbee
R23 §4.6.3.8 and Matter's MCSP both use, where freshness comes from the challenge
rather than from the counter being asked about."""

CHALLENGE_LENGTH: Final = 8

ALLOW_COUNTER_SYNC: Final = True
"""Whether to ask a device for its write counter before writing to it.

On by the owner's ruling of 2026-10-01 (D-080), because the case it answers
turned out not to be the unusual one. §5.3 has a device resume strictly above
anything it accepted, so ours stores `counter + 64` and resumes from the mark:
**every reboot puts it up to 64 ahead of the receiver, and nothing tells the
receiver.** Every write is then refused until the receiver catches up, and
refused in silence, because §4.2 acknowledges a write before validating it. It
was reproduced from nothing more than a reflash (D-078 fault 1, again in D-079).

The alternative remedies are both worse: a button the user has to find after a
failure they cannot see, or one flash write per command on a coin cell.

A device that does not offer the characteristic is unaffected — the read finds
nothing, the clock seed of D-064 stands, and the cost is one short connection per
configured device per restart. Plain devices are never asked at all."""

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

DEVICE_INFO_TRIGGER_BASED: Final = 1 << 2
"""Set when the device advertises only on an event rather than on a timer.

`bthome-ble` calls such a device *sleepy* and core `bthome` keeps its entities
available between packets, because a device that speaks once an hour is not an
absent device. We follow that, under their name and their rule."""

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

CONF_SLEEPY_DEVICE: Final = "sleepy_device"
"""Core `bthome`'s own key, deliberately the same string.

It persists what the trigger-based flag last said, so an entity is available
immediately after a restart rather than after the device's next event -- which,
for a trigger-based device, may be hours. Sharing the literal means a device
configured in both integrations reads the same in both config entries."""

CONF_DECLARATION: Final = "declaration"
"""The last declaration heard, kept so the controls exist before the device is.

Without it an entity is built only once an advertisement has been parsed, so a
restart while the device is asleep or out of range leaves the device with no
entities at all -- and an automation that names one breaks, where an unavailable
entity would merely wait. It is a cache, never authority: the first
advertisement replaces it."""

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

REAUTH_SERVICE_INFO: Final = "last_service_info"
"""What a reauthentication flow carries: the advertisement that would not open.

Core `bthome` passes its whole `DeviceData` and reads `device.last_service_info`
off it; we pass the service info directly, which is the part that matters. The
point is the same -- the user may answer the notification hours later, when the
device has gone quiet, and a key has to be checkable against something."""

AUTHENTICATION_FAILURES_BEFORE_REAUTH: Final = 2
"""How many advertisements must fail to authenticate before asking for the key.

Two, which is core `bthome`'s own number: *"we only ask for reautentification
after the decryption has failed twice."* One failure is a stray packet -- a
neighbour on the same address, a corrupted frame -- and raising a reauthentication
flow for it would train the user to dismiss them."""

COUNTER_RESTART_CEILING: Final = 100
"""Below this, a non-increasing advertising counter is a restart, not a replay.

`bthome-ble`'s rule, with its reasoning: a counter that has wrapped or a device
whose battery was changed resumes from zero, and refusing those would make a
device unreadable until it caught up. Above it, a counter that does not increase
is treated as a replay and the advertisement is skipped. We apply the same
thresholds so that a packet this integration accepts is one core `bthome` accepts
(`bthome_ble.parser._check_encryption_counter`)."""

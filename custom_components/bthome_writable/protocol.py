"""Wire-format handling for the BTHome Writable protocol, version 2.

Everything that reads or writes protocol bytes lives here, and nothing here
touches Home Assistant. Two reasons: the logic is meant to be proposed upstream
into the core `bthome` integration eventually, and §2.5 of the specification
asks for declaration parsing to sit behind a single function so the container
can change at the cost of that one function.

Parsing of the BTHome objects themselves is deliberately *not* reimplemented —
`bthome-ble` owns that. This module only reads what `bthome-ble` does not know
about: the declaration, the settings revision's role, and the one-object writes
and reads of §4. See spec/PROTOCOL.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .const import (
    DECLARATION_OBJECT_ID,
    DEVICE_INFO_BYTE_ADVERTISING,
    DEVICE_INFO_BYTE_READ,
    DEVICE_INFO_BYTE_WRITE,
    PACKET_ID_OBJECT_ID,
    SETTINGS_REVISION_OBJECT_ID,
    UUID_TEMPLATE,
)

# `bthome-ble` format names of objects whose width is not fixed by their ID.
LENGTH_PREFIXED_FORMATS: Final = frozenset({"raw", "string"})
COMMAND_FORMAT: Final = "command"  # <arg length, low 5 bits> <opcode> <args>

#: Entries a declaration may not list (§2.1): BTHome's packet id, the
#: declaration itself, and device information. A receiver counts them, so the
#: entries after keep their characteristic numbers, but never offers them.
FORBIDDEN_ENTRIES: Final = frozenset(
    {PACKET_ID_OBJECT_ID, DECLARATION_OBJECT_ID, 0xF0, 0xF1, 0xF2}
)


class ProtocolError(Exception):
    """The payload does not follow spec/PROTOCOL.md."""


def characteristic_uuid(entry: int) -> str:
    """Entry k, counted from 1, lives at 2FAAkkkk, k in hexadecimal (§4.1)."""
    return UUID_TEMPLATE.format(entry)


def _object_table() -> dict[int, tuple[str, int]]:
    """`bthome-ble`'s object table, as {object_id: (data_format, length)}.

    Imported lazily and adapted rather than copied: the table is upstream's to
    maintain, and a local copy would drift the first time BTHome assigns a new
    object ID.
    """
    from bthome_ble.const import MEAS_TYPES

    return {
        object_id: (meas.data_format, meas.data_length)
        for object_id, meas in MEAS_TYPES.items()
    }


@dataclass(frozen=True)
class ObjectKind:
    """What a BTHome object is, as far as choosing a control goes.

    Everything here is read from `bthome-ble` rather than declared: object ids,
    widths, factors and units are BTHome's to define, and a copy would drift the
    first time it assigns a new one. See spec/PLATFORMS.md.
    """

    kind: str
    """binary | numeric | string | event | raw | meta"""

    length: int
    signed: bool
    factor: float
    unit: str | None
    device_class: str | None
    data_format: str = ""

    @property
    def step(self) -> float:
        return self.factor

    @property
    def minimum(self) -> float:
        """The smallest value the encoding can carry, not what a device accepts.

        BTHome gives a device no way to narrow its own range, so a dimmer that
        stops at 100 still declares an object that can hold 655.35. A receiver
        cannot know better; the device is entitled to reject the write (§4.2).
        """
        if not self.signed:
            return 0.0
        return -(2 ** (8 * self.length - 1)) * self.factor

    @property
    def maximum(self) -> float:
        bits = 8 * self.length - (1 if self.signed else 0)
        return (2**bits - 1) * self.factor

    @property
    def variable(self) -> bool:
        return self.data_format in LENGTH_PREFIXED_FORMATS or (
            self.data_format == COMMAND_FORMAT
        )


def describe(object_id: int) -> ObjectKind | None:
    """Classify one object id, or None if `bthome-ble` does not know it."""
    from bthome_ble.const import MEAS_TYPES

    meas = MEAS_TYPES.get(object_id)
    if meas is None:
        return None

    shape = getattr(meas, "meas_format", None)
    name = type(shape).__name__
    # The width tests come first. `bthome-ble` gives text and raw an ordinary
    # sensor description, so classifying by description type alone calls them
    # numeric -- and a text box would then be offered as a slider.
    if meas.data_format in LENGTH_PREFIXED_FORMATS:
        kind = "raw" if meas.data_format == "raw" else "string"
    elif name == "BaseBinarySensorDescription":
        kind = "binary"
    elif name == "EventDeviceKeys":
        kind = "event"
    elif name == "BaseSensorDescription":
        kind = "numeric"
    else:
        # Device type and firmware version: readable facts about the device,
        # never something to offer a user as a control.
        kind = "meta"

    unit = getattr(shape, "native_unit_of_measurement", None)
    device_class = getattr(shape, "device_class", None)
    return ObjectKind(
        kind=kind,
        length=meas.data_length,
        signed=meas.data_format == "signed_integer",
        factor=getattr(meas, "factor", 1) or 1,
        unit=getattr(unit, "value", unit),
        device_class=getattr(device_class, "value", device_class),
        data_format=meas.data_format,
    )


def event_values(object_id: int) -> dict[int, str] | None:
    """The event vocabulary for an object id, from `bthome-ble`'s own table."""
    from bthome_ble.event import BUTTON_EVENTS, COMMAND_EVENTS, DIMMER_EVENTS

    table = {0x3A: BUTTON_EVENTS, 0x3B: COMMAND_EVENTS, 0x3C: DIMMER_EVENTS}.get(
        object_id
    )
    if table is None:
        return None
    return {code: name for code, name in table.items() if name is not None}


def encode_scaled(value: float, kind: ObjectKind) -> bytes:
    """A number as BTHome carries it: value / factor, little-endian."""
    raw = round(value / kind.factor)
    return raw.to_bytes(kind.length, "little", signed=kind.signed)


def decode_scaled(value: bytes, kind: ObjectKind) -> float:
    return int.from_bytes(value, "little", signed=kind.signed) * kind.factor


@dataclass(frozen=True)
class WritableEntry:
    """One entry of a declaration: an object type written on its own
    characteristic."""

    entry: int
    """Counted from 1, in declaration order. Also the characteristic number."""

    object_id: int

    @property
    def uuid(self) -> str:
        return characteristic_uuid(self.entry)

    @property
    def kind(self) -> ObjectKind | None:
        return describe(self.object_id)

    @property
    def offered(self) -> bool:
        """Whether a receiver may build an entity for this entry (§2.1).

        False for forbidden IDs, for IDs `bthome-ble` does not know, and for
        device-information objects. Such entries are still counted.
        """
        if self.object_id in FORBIDDEN_ENTRIES:
            return False
        kind = self.kind
        return kind is not None and kind.kind != "meta"


@dataclass(frozen=True)
class Declaration:
    """A parsed declaration, and the settings revision beside it."""

    entries: tuple[WritableEntry, ...]
    settings_revision: int | None
    """The advertised `0x65`, or None if the device does not advertise one --
    which means its writable values change only when written (§3.1)."""

    @property
    def offered(self) -> tuple[WritableEntry, ...]:
        return tuple(entry for entry in self.entries if entry.offered)

    @property
    def layout(self) -> tuple[int, ...]:
        """The entry object IDs, which is what identifies a firmware's layout."""
        return tuple(entry.object_id for entry in self.entries)


def _value_length(payload: bytes, offset: int, data_format: str, fixed: int) -> int:
    """How many value bytes follow the object ID at `offset`."""
    if data_format in LENGTH_PREFIXED_FORMATS:
        if offset + 1 >= len(payload):
            raise ProtocolError(f"no length byte for object 0x{payload[offset]:02X}")
        return 1 + payload[offset + 1]
    if data_format == COMMAND_FORMAT:
        if offset + 1 >= len(payload):
            raise ProtocolError("no argument length for a command object")
        return 2 + (payload[offset + 1] & 0x1F)
    return fixed


def split_objects(payload: bytes) -> tuple[list[tuple[int, bytes]], int | None]:
    """Walk BTHome service data: ([(object_id, value)], declaration offset).

    `payload` is the service data *without* the device-information byte, and
    decrypted if the device is encrypted — exactly what `bthome-ble` feeds its
    own object loop. The walk stops at the declaration, or at the first ID
    `bthome-ble` does not know, as upstream does: anything after an unknown ID is
    unreachable for every BTHome receiver.
    """
    table = _object_table()
    objects: list[tuple[int, bytes]] = []
    offset = 0
    while offset < len(payload):
        object_id = payload[offset]
        if object_id == DECLARATION_OBJECT_ID:
            return objects, offset
        if object_id not in table:
            return objects, None
        data_format, fixed = table[object_id]
        length = _value_length(payload, offset, data_format, fixed)
        end = offset + 1 + length
        if end > len(payload):
            raise ProtocolError(
                f"truncated payload: object 0x{object_id:02X} needs {length} bytes"
            )
        objects.append((object_id, payload[offset + 1 : end]))
        offset = end
    return objects, None


def parse_declaration(payload: bytes) -> Declaration | None:
    """Read the declaration out of BTHome service data (§2).

    This is the single function §2.5 asks for. `payload` is the service data
    without the device-information byte. Returns None for an ordinary BTHome
    device — which is what the config flow's `not_supported` abort keys on.

    A naive search for 0xFF would match a value byte — a battery at 255, say —
    which is why the payload is walked rather than scanned.
    """
    if not payload:
        return None
    objects, offset = split_objects(payload)
    if offset is None:
        return None

    entries = tuple(
        WritableEntry(entry=k, object_id=object_id)
        for k, object_id in enumerate(payload[offset + 1 :], start=1)
    )
    revision = next(
        (
            value[0]
            for object_id, value in objects
            if object_id == SETTINGS_REVISION_OBJECT_ID
        ),
        None,
    )
    return Declaration(entries=entries, settings_revision=revision)


def encode_object(entry: WritableEntry, value: bytes) -> bytes:
    """A write's plaintext: one BTHome object, ID then value (§4.2).

    `value` is in BTHome's own encoding, including the length byte of a
    variable-length object.
    """
    return bytes([entry.object_id]) + value


def decode_object(entry: WritableEntry, payload: bytes) -> bytes:
    """The value out of a read (§4.3), checked the way a device checks a write.

    Raises ProtocolError for a wrong object ID, a wrong length, or trailing
    bytes: a read from a characteristic that no longer means what the receiver
    thinks must not be shown as state.
    """
    if not payload:
        raise ProtocolError("empty read")
    if payload[0] != entry.object_id:
        raise ProtocolError(
            f"entry {entry.entry}: read object 0x{payload[0]:02X}, "
            f"expected 0x{entry.object_id:02X}"
        )
    table = _object_table()
    if entry.object_id not in table:
        raise ProtocolError(
            f"entry {entry.entry}: unknown object 0x{entry.object_id:02X}"
        )
    data_format, fixed = table[entry.object_id]
    length = _value_length(payload, 0, data_format, fixed)
    if len(payload) != 1 + length:
        raise ProtocolError(
            f"entry {entry.entry}: read is {len(payload) - 1} value bytes, "
            f"expected {length}"
        )
    return payload[1:]


# --- Encryption (§5) ---------------------------------------------------------
#
# BTHome v2's AES-CCM, unchanged, with one delta: the device-information byte of
# the nonce carries the direction -- 0x41 advertising, 0xFF write, 0xFE read. A
# captured advertisement, write or read cannot verify as either of the others,
# with nothing extra on the wire (§5.1).

MIC_LENGTH: Final = 4
COUNTER_LENGTH: Final = 4
SEAL_OVERHEAD: Final = COUNTER_LENGTH + MIC_LENGTH


def mac_bytes(address: str) -> bytes:
    """The six address bytes in the order BTHome puts them in the nonce.

    Natural order, as written. Verified against `bthome-ble`, which is the
    library that has to agree for an encrypted device to be readable at all.
    """
    return bytes.fromhex(address.replace(":", "").replace("-", ""))


def nonce(address: str, device_info: int, counter: int) -> bytes:
    """mac || 0xD2 0xFC || device-info || counter u32 LE (§5.1)."""
    return (
        mac_bytes(address)
        + bytes([0xD2, 0xFC, device_info])
        + counter.to_bytes(COUNTER_LENGTH, "little")
    )


def is_encrypted(payload: bytes) -> bool:
    """Whether BTHome service data announces itself as encrypted."""
    return bool(payload) and payload[0] == DEVICE_INFO_BYTE_ADVERTISING


def split_sealed(payload: bytes) -> tuple[bytes, int, bytes]:
    """(ciphertext, counter, mic) out of `ciphertext || counter || mic` (§5.2).

    Every direction shares this framing; advertising merely carries a leading
    device-information byte, which the caller strips.
    """
    if len(payload) <= SEAL_OVERHEAD:
        raise ProtocolError(
            f"{len(payload)} bytes is shorter than the framing it must contain"
        )
    body = payload[:-SEAL_OVERHEAD]
    counter = int.from_bytes(payload[-SEAL_OVERHEAD:-MIC_LENGTH], "little")
    return body, counter, payload[-MIC_LENGTH:]


def _open(
    payload: bytes, bindkey: bytes, address: str, device_info: int
) -> bytes | None:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM

    ciphertext, counter, mic = split_sealed(payload)
    try:
        return AESCCM(bindkey, tag_length=MIC_LENGTH).decrypt(
            nonce(address, device_info, counter), ciphertext + mic, None
        )
    except InvalidTag:
        return None


def decrypt_advertising(payload: bytes, bindkey: bytes, address: str) -> bytes | None:
    """The object stream inside encrypted service data, or None if it will not
    authenticate.

    None rather than an exception: a wrong key is an expected condition — the
    user mistyped it, or the device is not the one we think — not a programming
    error.
    """
    if not is_encrypted(payload):
        raise ProtocolError("this payload does not announce itself as encrypted")
    return _open(payload[1:], bindkey, address, DEVICE_INFO_BYTE_ADVERTISING)


def seal(
    plaintext: bytes, bindkey: bytes, address: str, device_info: int, counter: int
) -> bytes:
    """`plaintext` sealed as §5.2 frames it, under direction `device_info`."""
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM

    sealed = AESCCM(bindkey, tag_length=MIC_LENGTH).encrypt(
        nonce(address, device_info, counter), plaintext, None
    )
    body, mic = sealed[:-MIC_LENGTH], sealed[-MIC_LENGTH:]
    return body + counter.to_bytes(COUNTER_LENGTH, "little") + mic


def seal_write(plaintext: bytes, bindkey: bytes, address: str, counter: int) -> bytes:
    """A write sealed under the write direction (§5.1)."""
    return seal(plaintext, bindkey, address, DEVICE_INFO_BYTE_WRITE, counter)


def open_read(payload: bytes, bindkey: bytes, address: str) -> bytes | None:
    """A sealed read's plaintext object, or None if it will not authenticate."""
    return _open(payload, bindkey, address, DEVICE_INFO_BYTE_READ)

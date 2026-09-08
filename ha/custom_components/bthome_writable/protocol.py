"""Wire-format handling for the BTHome Writable protocol.

Everything that reads or writes protocol bytes lives here, and nothing here
touches Home Assistant. Two reasons: the logic is meant to be proposed upstream
into the core `bthome` integration eventually, and §2.5 of the specification
asks for declaration parsing to sit behind a single function so the container
can change at the cost of that one function.

Parsing of the BTHome objects themselves is deliberately *not* reimplemented —
`bthome-ble` owns that. This module only reads the parts of the payload that
`bthome-ble` does not know about: the declaration, and the positions it refers
to. See spec/PROTOCOL.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .const import DECLARATION_OBJECT_ID

# Objects whose value is preceded by a length byte. Every other object has a
# width fixed by its ID, which `bthome-ble`'s table knows and we look up rather
# than duplicate.
VARIABLE_LENGTH_FORMATS: Final = frozenset({"raw", "string"})


@dataclass(frozen=True)
class WritableObject:
    """One object a device has declared writable."""

    position: int
    object_id: int
    value: bytes
    """The last advertised value, used to compose no-change writes (§4.3).

    For a variable-length object this includes the leading length byte, so it
    can be concatenated into a write unchanged.
    """

    data_format: str
    """`bthome-ble`'s format name for this object ID."""

    @property
    def is_variable_length(self) -> bool:
        return self.data_format in VARIABLE_LENGTH_FORMATS

    @property
    def write_only(self) -> bool:
        """Whether this is the write-only placeholder of §3.

        Only detectable for variable-length objects, where a length of 0 is
        unambiguous. A fixed-length object advertising zero is indistinguishable
        from one whose value legitimately is zero — a light that is off
        advertises `1E 00` — so the pattern does not apply to them. This is
        narrower than §3's "empty or zero value" wording; see decisions.md D-009.
        """
        return self.is_variable_length and self.value == b"\x00"


@dataclass(frozen=True)
class Declaration:
    """A parsed writability declaration and the objects it points at."""

    bitmask: int
    objects: tuple[WritableObject, ...]

    @property
    def positions(self) -> tuple[int, ...]:
        return tuple(obj.position for obj in self.objects)


class ProtocolError(Exception):
    """The payload does not follow spec/PROTOCOL.md."""


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


def split_objects(payload: bytes) -> list[tuple[int, int, bytes, str]]:
    """Split BTHome service data into (position, object_id, value, format) tuples.

    `payload` is the service data *without* the device-information byte, and
    decrypted if the device is encrypted — i.e. exactly what `bthome-ble` feeds
    its own object loop.

    Stops at the declaration, which is by definition the last element (§2.2).
    Raises ProtocolError on a payload that cannot be walked, which for a write
    composition means "do not write" rather than "write something plausible".
    """
    table = _object_table()
    objects: list[tuple[int, int, bytes, str]] = []
    offset = 0
    position = 0

    while offset < len(payload):
        object_id = payload[offset]

        if object_id == DECLARATION_OBJECT_ID:
            break

        if object_id not in table:
            # Same rule as upstream: an unknown ID ends the walk. Anything
            # after it is unreachable for every BTHome receiver, so there is
            # nothing sensible to recover.
            break

        data_format, fixed_length = table[object_id]
        if data_format in VARIABLE_LENGTH_FORMATS:
            if offset + 1 >= len(payload):
                raise ProtocolError(
                    f"truncated payload: no length byte for object "
                    f"0x{object_id:02X} at position {position}"
                )
            length = payload[offset + 1]
            start = offset + 1  # the length byte belongs to the value
            end = offset + 2 + length
        else:
            length = fixed_length
            start = offset + 1
            end = offset + 1 + length

        if end > len(payload):
            raise ProtocolError(
                f"truncated payload: object 0x{object_id:02X} at position "
                f"{position} needs {length} value bytes"
            )

        objects.append((position, object_id, payload[start:end], data_format))
        offset = end
        position += 1

    return objects


def parse_declaration(payload: bytes) -> Declaration | None:
    """Read the writability declaration out of BTHome service data.

    This is the single function §2.5 asks for: if the declaration ever moves to
    a manufacturer-data container, only this changes.

    `payload` is the service data without the device-information byte. Returns
    None for an ordinary BTHome device — which is what the config flow's
    `not_supported` abort keys on, so that plain BTHome devices are never
    offered to the user.
    """
    if not payload:
        return None

    declaration_offset = _find_declaration(payload)
    if declaration_offset is None:
        return None

    if declaration_offset + 1 >= len(payload):
        raise ProtocolError("declaration object carries no bitmask byte")

    bitmask = payload[declaration_offset + 1]
    if declaration_offset + 2 != len(payload):
        raise ProtocolError(
            "declaration is not the last element: "
            f"{len(payload) - declaration_offset - 2} trailing bytes"
        )

    by_position = {
        position: (object_id, value, data_format)
        for position, object_id, value, data_format in split_objects(payload)
    }

    objects: list[WritableObject] = []
    for bit in range(8):
        if not bitmask & (1 << bit):
            continue
        if bit not in by_position:
            # §2.2: a bit addressing no object is malformed. Ignore it rather
            # than invent an entity the device cannot accept a write for.
            continue
        object_id, value, data_format = by_position[bit]
        objects.append(
            WritableObject(
                position=bit,
                object_id=object_id,
                value=value,
                data_format=data_format,
            )
        )

    return Declaration(bitmask=bitmask, objects=tuple(objects))


def _find_declaration(payload: bytes) -> int | None:
    """Offset of the declaration object, walking objects rather than scanning.

    A naive `payload.index(0xFF)` would match a value byte — a battery at 255,
    say — so the payload has to be walked properly even though the declaration
    is known to be last.
    """
    table = _object_table()
    offset = 0

    while offset < len(payload):
        object_id = payload[offset]
        if object_id == DECLARATION_OBJECT_ID:
            return offset
        if object_id not in table:
            return None

        data_format, fixed_length = table[object_id]
        if data_format in VARIABLE_LENGTH_FORMATS:
            if offset + 1 >= len(payload):
                return None
            offset += 2 + payload[offset + 1]
        else:
            offset += 1 + fixed_length

    return None


def compose_write(
    declaration: Declaration, changes: dict[int, bytes] | None = None
) -> bytes:
    """Build a write payload: every writable object, in packet order (§4.2).

    `changes` maps a position to its new *value* bytes. Positions not mentioned
    are resent at their last advertised value; write-only objects not mentioned
    get the no-op of §4.3.
    """
    changes = changes or {}
    payload = bytearray()

    for obj in declaration.objects:
        payload.append(obj.object_id)
        if obj.position in changes:
            payload += changes[obj.position]
        elif obj.write_only:
            payload += no_op_value(obj)
        else:
            payload += obj.value

    return bytes(payload)


def no_op_value(obj: WritableObject) -> bytes:
    """The "do not modify" encoding for an object (§4.3).

    Variable-length objects use a length of 0. Event-class objects use BTHome's
    own "none" event value, which is also 0x00 but for an unrelated reason; they
    arrive with T2.1.

    A fixed-length, non-event object has no no-op: the way to leave it alone is
    to resend its last advertised value, which `compose_write` does. Reaching
    here with one is a bug, not a payload to guess at.
    """
    if obj.is_variable_length:
        return b"\x00"
    raise ProtocolError(
        f"object 0x{obj.object_id:02X} ({obj.data_format}) has no no-op value; "
        "resend its last advertised value instead"
    )

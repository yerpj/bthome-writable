"""Why `manifest.json` cannot ask for an older `bthome-ble`.

The floor is load-bearing and the reason is two steps removed from it, so it
reads like caution and invites someone to lower it. It is not caution.

`split_objects` walks the advertising the way `bthome-ble` does and stops at the
first object ID the library does not know (D-005, and the behaviour the whole
declaration placement rests on). BTHome's settings revision `0x65` appears
*before* the declaration in a device that reports its own state, so a library
that does not know `0x65` stops there and the declaration behind it disappears
-- the device is discovered and offers nothing.

This test fails if the installed library has lost that object, which is the only
circumstance in which the floor would need to move.
"""

from __future__ import annotations

from bthome_ble.const import MEAS_TYPES
import pytest

SETTINGS_REVISION = 0x65


def test_the_library_knows_the_settings_revision() -> None:
    assert SETTINGS_REVISION in MEAS_TYPES, (
        "bthome-ble does not know 0x65; the object walk would stop there and "
        "every declaration behind it would be invisible"
    )


@pytest.mark.parametrize("object_id", [0x00, 0x53, 0x3A, 0x3B, 0x3C, 0x54])
def test_the_library_knows_every_object_this_protocol_names(object_id: int) -> None:
    """Each of these is named in PROTOCOL.md and reached through the library's
    table: the packet id, text, the three event objects, raw."""
    assert object_id in MEAS_TYPES, f"0x{object_id:02X} missing from bthome-ble"

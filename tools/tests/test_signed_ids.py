"""The Espruino module's signed-object table against the library's.

`BTHomeWritable.js` cannot import `bthome-ble`, so it carries a copy of which
BTHome objects are signed. A copy of someone else's table drifts, and this one
did: `0x59`, `0x5A` and `0x5B` were signed upstream and unsigned here, which
decodes every negative value of those types as a large positive one. Nothing
caught it, because the upstream Espruino `BTHome` module has no type name
reaching those ids -- only a device declaring them by raw id with `signed:true`
would have noticed, and none does.

This reads the table out of the JavaScript and compares it with the library, so
the next object BTHome marks signed fails here instead.
"""

from __future__ import annotations

from pathlib import Path
import re

from bthome_ble.const import MEAS_TYPES

MODULE = Path(__file__).resolve().parents[2] / "espruino" / "BTHomeWritable.js"
SIGNED_FORMAT = "signed_integer"


def declared_in_javascript() -> set[int]:
    """The ids `SIGNED_IDS` lists, read out of the module's source."""
    line = next(
        line
        for line in MODULE.read_text(encoding="utf-8").splitlines()
        if line.startswith("const SIGNED_IDS")
    )
    return {int(match, 16) for match in re.findall(r"0x([0-9A-Fa-f]{2}):true", line)}


def signed_in_library() -> set[int]:
    return {
        object_id
        for object_id, meas in MEAS_TYPES.items()
        if meas.data_format == SIGNED_FORMAT
    }


def test_the_module_lists_every_signed_object_the_library_knows() -> None:
    missing = signed_in_library() - declared_in_javascript()

    assert not missing, (
        "BTHomeWritable.js SIGNED_IDS is missing "
        + ", ".join(f"0x{object_id:02X}" for object_id in sorted(missing))
        + ": a device declaring one by raw id would decode its negative values "
        "as large positive ones"
    )


def test_the_module_lists_nothing_the_library_calls_unsigned() -> None:
    """The other direction matters too: an id wrongly listed here turns the top
    half of an unsigned range into negatives."""
    extra = declared_in_javascript() - signed_in_library()

    assert not extra, (
        "BTHomeWritable.js SIGNED_IDS lists "
        + ", ".join(f"0x{object_id:02X}" for object_id in sorted(extra))
        + ", which bthome-ble does not call signed"
    )

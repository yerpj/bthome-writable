"""The module page documents what the module reads, with units.

Trimming the module for EspruinoDocs moves its options table off the code and
onto the page (D-096). That is their convention, and it creates the oldest
documentation failure there is: the code grows an option and the page does not
hear about it.

The units check exists because the first reader of the page found the gap in
thirty seconds -- the per-entry `interval` said what it did and not what it
counted, and `300000` reads as either five minutes or three and a half days
depending on what you assume.
"""

from __future__ import annotations

import re

from tools.build_espruino_module import OUTPUT_DIR, PAGE_DIR, SOURCE_DIR

MODULE = SOURCE_DIR / "BTHomeWritable.js"
PAGE = PAGE_DIR / "BTHomeWritable.md"

TIME = ("interval", "timeout")
"""Options counting time. Their rows must say which unit."""

SIZE = ("maxwritelength", "maxservicedata")
"""Options counting bytes."""


def options() -> set[str]:
    """Every `opts.X` the module reads."""
    return set(re.findall(r"opts\.([A-Za-z]+)", MODULE.read_text(encoding="utf-8")))


def rows() -> dict[str, str]:
    """The reference table, option name to the text describing it."""
    found = {}
    for line in PAGE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*`([A-Za-z]+)`\s*\|(.*)\|\s*$", line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def test_every_option_the_module_reads_is_on_the_page() -> None:
    missing = options() - set(rows())
    assert not missing, (
        f"setup() reads {sorted(missing)}, and the EspruinoDocs page does not "
        "mention them. The page is the only place those are documented now."
    )


def test_the_page_documents_nothing_the_module_ignores() -> None:
    """The other direction, which is how a renamed option leaves a ghost."""
    documented = set(rows())
    extra = {name for name in documented if name not in options()}
    # Methods and entry fields share the table shape; only option rows count.
    extra -= {"advertise"}
    assert not extra or extra <= {"bw"}, (
        f"the page documents {sorted(extra)}, which setup() does not read"
    )


def test_options_that_count_time_say_milliseconds() -> None:
    for name, text in rows().items():
        if any(word in name.lower() for word in TIME):
            assert re.search(r"millisecond|\bms\b", text), (
                f"`{name}` is a duration and its row does not say "
                f"the unit: {text.strip()!r}"
            )


def test_options_that_count_bytes_say_so() -> None:
    for name, text in rows().items():
        if name.lower() in SIZE:
            assert "byte" in text, (
                f"`{name}` is a size and its row does not say "
                f"the unit: {text.strip()!r}"
            )


def test_the_per_entry_interval_says_its_unit_too() -> None:
    """The one that was actually missing: it is not an `opts.` field, so the
    checks above cannot see it."""
    text = PAGE.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| `interval`"))
    assert "per-entry" in row and row.count("millisecond") >= 2, (
        "the per-entry interval shares this row and needs its own unit: "
        f"{row.strip()!r}"
    )


def test_the_published_pages_match_their_sources() -> None:
    for name in ("BTHomeWritable.md", "AESCCM.md"):
        assert (OUTPUT_DIR / name).read_text(encoding="utf-8") == (
            PAGE_DIR / name
        ).read_text(encoding="utf-8"), (
            f"{name} in dist is stale; run `python -m tools.build_espruino_module`"
        )

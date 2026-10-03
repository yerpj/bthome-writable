"""Every `[DECISION]` marker outside the archive must say what became of it.

A marker is a promise that someone still has to choose. Three of them outlived
their rulings by over a week: D-070's own heading kept `[DECISION, owner for
section 4.4]` ten days after section 4.4 was settled, `PLATFORMS.md` still
headed a ruled question `Open:`, and the working document carried five markers
for mechanisms version 2 had deleted. None of it was wrong when written, and all
of it told a reader -- or the next agent -- that work was pending which was not
(D-081).

So: outside `spec/decisions.md`, which is an archive and whose headings are
labels rather than open questions, a `[DECISION` marker has to carry a
disposition word, or be named below as genuinely still open. Adding one is then
a deliberate act with a line of justification, which is all this guard asks.
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]

SEARCHED = (
    "SPEC-WORKING-DOCUMENT.md",
    "spec/PROTOCOL.md",
    "spec/PLATFORMS.md",
    "spec/bthome-dossier.md",
    "custom_components/bthome_writable/*.py",
    "espruino/*.js",
)

DISPOSITIONS = ("ruled", "settled", "moot", "out of scope", "done")
"""Words that turn a marker from a question into a record of its answer."""

STILL_OPEN = {
    # The one in shipping code, and legitimately standing: a receiver policy the
    # owner may reverse at any time without the protocol changing.
    "custom_components/bthome_writable/const.py": 1,
    # The markers' own definition, and the task line that explains them.
    "SPEC-WORKING-DOCUMENT.md": 2,
}
"""How many bare markers each file may still carry, and why, above."""

MARKER = re.compile(r"\[DECISION")


def bare_markers(path: Path) -> list[tuple[int, str]]:
    """Markers on lines that do not say what was decided."""
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not MARKER.search(line):
            continue
        if any(word in line.lower() for word in DISPOSITIONS):
            continue
        found.append((number, line.strip()[:120]))
    return found


def test_no_marker_outside_the_archive_is_left_hanging() -> None:
    offenders: dict[str, list[tuple[int, str]]] = {}
    for pattern in SEARCHED:
        for path in sorted(ROOT.glob(pattern)):
            relative = path.relative_to(ROOT).as_posix()
            bare = bare_markers(path)
            allowed = STILL_OPEN.get(relative, 0)
            if len(bare) > allowed:
                offenders[relative] = bare

    assert not offenders, (
        "a [DECISION] marker must say what became of it "
        f"({', '.join(DISPOSITIONS)}), or be allowed in STILL_OPEN with a "
        "reason:\n"
        + "\n".join(
            f"  {where}:{number}  {text}"
            for where, items in offenders.items()
            for number, text in items
        )
    )


def test_the_working_document_warns_that_its_protocol_is_abandoned() -> None:
    """It is still named as the source of truth by CLAUDE.md while sections 3
    and 7 describe version 1. Until it is rewritten, the warning is what stops
    the next reader implementing the wrong protocol."""
    text = (ROOT / "SPEC-WORKING-DOCUMENT.md").read_text(encoding="utf-8")

    assert "describe protocol version 1, which is abandoned" in text
    assert "spec/PROTOCOL.md" in text

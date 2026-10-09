"""A bundle a document tells someone to paste must fit in a Puck.js.

T4.2 found the documented path broken on this project's own reference board
(D-093). `docs/espruino-quickstart.md` said to paste
`single-light-standalone.js`, 40 161 bytes:

* **to flash** the Web IDE wrote 41 848 bytes into 40 960 of Storage --
  ``Compacting...`` then ``Uncaught Error: Unable to find or create file``;
* **to RAM**, which is what the document actually intends, ``OUT OF MEMORY at
  getAdvertisement`` and then ``New interpreter error: LOW_MEMORY,MEMORY``,
  leaving `setup()` half-built.

Both measured on a Puck.js v2 running 2v27. The minified bundles, 18-19 kB,
work either way. Nobody had hit it in a year of hardware work because the bench
sends `.min.js` or goes through `espruino_deploy`, which puts the modules in
Storage and uploads a small application -- so every path this project exercises
avoids the one it documents.

This test reads the documents rather than the shelf: it finds every bundle a
reader is told to paste, and fails if one of them is too big. A new example, or
a document that grows a sentence naming the readable bundle, is caught here.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "espruino" / "dist"

PASTE_LIMIT = 32_768
"""Between the two measurements, and nearer the failure than the success.

A Puck.js v2 has 40 960 bytes of Storage and rather less usable variable
memory; 40 161 bytes failed in both, 18 193 worked in both. The limit is not a
specification -- it is a line drawn between a measured failure and a measured
success, and a bundle approaching it should be minified rather than argued
about.
"""

DOCUMENTS = ("docs", "README.md")

PASTE = re.compile(
    # Across line breaks and markdown links: the quickstart's instruction is
    # "paste the whole of\n[`espruino/dist/single-light-standalone.js`](...)",
    # and a pattern that stopped at the newline read straight past it.
    r"(?:paste|coller|send)\b[\s\S]{0,200}?([\w-]+-standalone(?:\.min)?\.js)",
    re.IGNORECASE,
)


def documents() -> list[Path]:
    files = [ROOT / "README.md"]
    files += sorted((ROOT / "docs").glob("*.md"))
    # The walkthrough records what went wrong, including the bundle that broke,
    # so reading it as an instruction would fail on its own findings.
    return [f for f in files if f.name != "walkthrough.md"]


def pasteable() -> list[tuple[Path, str]]:
    found = []
    for doc in documents():
        text = doc.read_text(encoding="utf-8")
        for match in PASTE.finditer(text):
            found.append((doc, match.group(1)))
    return found


def test_the_documents_tell_someone_to_paste_something() -> None:
    """Guard the guard: a regex that matches nothing passes silently."""
    assert pasteable(), (
        "no document names a bundle to paste any more -- either the "
        "instructions changed shape, or this test stopped reading them"
    )


@pytest.mark.parametrize("doc,name", pasteable(), ids=lambda v: getattr(v, "name", v))
def test_a_bundle_a_reader_is_told_to_paste_fits_a_puck(doc: Path, name: str) -> None:
    path = DIST / name
    assert path.exists(), f"{doc.name} names {name}, which is not in espruino/dist"
    size = path.stat().st_size
    assert size <= PASTE_LIMIT, (
        f"{doc.relative_to(ROOT)} tells a reader to paste {name}, which is "
        f"{size} bytes. A Puck.js refuses it in flash (40 960 of Storage) and "
        f"runs out of memory in RAM -- measured, D-093. Name the .min.js."
    )

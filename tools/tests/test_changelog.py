"""A version that moves without a changelog entry, and the four files that lie.

Two failures this repository has already had, both found late and both silent at
the time:

* `gen_test_vectors.py` wrote `spec_version: 2.0-draft.6` into the shared
  contract while emitting a declaration without the length byte §2.1 had gained
  two commits earlier. Every test that opened the file passed, because they all
  read the same wrong bytes (D-079).
* Two normative edits, §4.1's per-device numbering and §2.1's entry count, were
  made on 2026-10-15 without bumping the draft number at all, so the document
  that reached a reader claimed to be the one before it (D-103, D-105).

So the version string is checked in every place that states it, and the current
one has to be written down in the changelog that explains it. The owner's rule
of 2026-10-22: minor changes to the specification are allowed at this stage, and
a changelog is what keeps them from being invisible.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]

DRAFT = re.compile(r"2\.0-draft\.(\d+)")

STATES_THE_SPEC_VERSION = (
    "spec/PROTOCOL.md",
    "README.md",
    "tools/gen_test_vectors.py",
    "tools/gen_advertising_fixtures.py",
    "test-vectors/test-vectors.json",
    "spec/advertising-fixtures.json",
)
"""Every file carrying the protocol's version number.

The two JSON files are generated, so they are the ones that drift: a generator
whose constant was not updated writes a stale version into the contract both
test suites read."""


def spec_version() -> str:
    """The version `PROTOCOL.md` claims in its own header."""
    header = (ROOT / "spec/PROTOCOL.md").read_text(encoding="utf-8")[:400]
    found = DRAFT.search(header)
    assert found, "PROTOCOL.md has no 2.0-draft.N in its header"
    return found.group(0)


def test_every_file_that_states_the_spec_version_states_the_same_one() -> None:
    wanted = spec_version()
    disagree = {}
    for name in STATES_THE_SPEC_VERSION:
        text = (ROOT / name).read_text(encoding="utf-8")
        said = sorted(set(DRAFT.findall(text)))
        if said != [wanted.rsplit(".", 1)[1]]:
            disagree[name] = said
    assert not disagree, (
        f"{wanted} is what PROTOCOL.md says; these disagree: {disagree}. "
        "Regenerate the fixtures and the vectors after bumping a generator."
    )


def test_the_current_spec_version_has_a_changelog_entry() -> None:
    wanted = spec_version()
    log = (ROOT / "spec/CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {wanted} -" in log, (
        f"spec/CHANGELOG.md has no entry for {wanted}. A specification that "
        "changes without saying so is the failure this guard exists for."
    )


def test_no_draft_number_is_skipped() -> None:
    """Every draft from 1 to the current one is accounted for."""
    current = int(spec_version().rsplit(".", 1)[1])
    log = (ROOT / "spec/CHANGELOG.md").read_text(encoding="utf-8")
    missing = [n for n in range(1, current + 1) if f"## 2.0-draft.{n} -" not in log]
    assert not missing, f"spec/CHANGELOG.md skips draft {missing}"


def test_the_shipped_version_has_a_changelog_entry() -> None:
    """The integration's own version, which is what HACS installs."""
    manifest = json.loads(
        (ROOT / "custom_components/bthome_writable/manifest.json").read_text(
            encoding="utf-8"
        )
    )
    version = manifest["version"]
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{version}]" in log, f"CHANGELOG.md has no entry for {version}"
    assert "## [Unreleased]" in log, (
        "CHANGELOG.md has no Unreleased section, so work since the last tag has "
        "nowhere to be written down as it lands"
    )

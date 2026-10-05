"""The worked examples of PROTOCOL.md §8, against the generated fixtures.

§8 is the part of the specification a reader learns the format from, and it is
hand-written prose beside a file that is generated from the implementations. So
it drifts in the one direction nobody notices: all four examples omitted the
declaration's count byte for the twelve days after §2.1 gained it (D-073,
D-083), while the fixtures carried it the whole time. Every test in three suites
passed, because no test read the specification.

Each fixture below names the §8 example it illustrates. The test is simply that
the bytes in the document are the bytes in the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = ROOT / "spec" / "PROTOCOL.md"
FIXTURES = ROOT / "spec" / "advertising-fixtures.json"

#: fixture name -> the §8 section that shows it
ILLUSTRATED = {
    "single-light": "8.1",
    "thermostat": "8.2",
    "two-lights-and-display": "8.3",
    "momentary-action": "8.4",
}


def fixture_payloads() -> dict[str, str]:
    document = json.loads(FIXTURES.read_text(encoding="utf-8"))
    return {entry["name"]: entry["service_data"] for entry in document["fixtures"]}


def spaced(service_data: str) -> str:
    """The hex as §8 writes it: upper case, a space between bytes."""
    pairs = [service_data[i : i + 2] for i in range(0, len(service_data), 2)]
    return " ".join(pair.upper() for pair in pairs)


@pytest.mark.parametrize(("name", "section"), sorted(ILLUSTRATED.items()))
def test_the_worked_example_is_the_fixture_it_illustrates(
    name: str, section: str
) -> None:
    payload = fixture_payloads()[name]
    document = PROTOCOL.read_text(encoding="utf-8")

    assert spaced(payload) in document, (
        f"§{section} does not show {name} as "
        f"`{spaced(payload)}`; the example and the fixture have drifted"
    )


def declarations_with_wrong_count(document: str) -> list[str]:
    """Lines where a declaration's count does not match the object IDs after it.

    A declaration is `FF <n> <n object IDs>`, so the byte after `FF` is a small
    number and never an object ID a device would declare. `FF 1E` -- what every
    worked example used to say -- reads as thirty entries carrying none.

    Taken out of the test so the checker itself can be exercised against the
    strings the document used to contain: a guard that does not catch the bug it
    was written for is worse than none, and the first draft of this one missed
    `... FF 1E` at the end of a line.
    """
    offenders: list[str] = []
    for line in document.splitlines():
        # Backticks and punctuation cling to a token in prose, and a prose
        # declaration is the kind most likely to drift: `FF 1E 1E` in
        # section 2.2 was wrong for twelve days.
        tokens = [token.strip("`,.;:()") for token in line.replace("`", " ").split()]
        for index, token in enumerate(tokens):
            if token != "FF" or index + 1 >= len(tokens):
                continue
            count = tokens[index + 1]
            if len(count) != 2:
                continue
            try:
                claimed = int(count, 16)
            except ValueError:
                continue
            following = 0
            for candidate in tokens[index + 2 :]:
                if len(candidate) != 2:
                    break
                try:
                    int(candidate, 16)
                except ValueError:
                    break
                following += 1
            if claimed != following:
                offenders.append(line.strip())
    return offenders


def test_no_declaration_in_the_document_is_missing_its_count() -> None:
    offenders = declarations_with_wrong_count(PROTOCOL.read_text(encoding="utf-8"))

    assert not offenders, (
        "a declaration whose count does not match the object IDs after it:"
        + "".join(chr(10) + "  " + line for line in offenders)
    )


@pytest.mark.parametrize(
    "line",
    [
        "40 00 09 01 61 FF 1E",
        "40 00 09 FF 3A",
        "40 00 09 FF 1E 1E 53",
        "40 00 09 02 C4 09 65 03 FF 10 57",
        "- The same object ID MAY appear several times: `FF 1E 1E` is a device",
    ],
)
def test_the_checker_catches_what_the_document_used_to_say(line: str) -> None:
    """Every one of these was in `PROTOCOL.md` until 2026-10-05."""
    assert declarations_with_wrong_count(line) == [line.strip()]


@pytest.mark.parametrize(
    "line",
    [
        "40 00 09 01 61 FF 01 1E",
        "40 00 09 FF 01 3A",
        "40 00 09 FF 03 1E 1E 53",
        "40 00 09 02 C4 09 65 03 FF 02 10 57",
        "a sentence about FF with no bytes after it",
    ],
)
def test_the_checker_accepts_what_it_says_now(line: str) -> None:
    assert declarations_with_wrong_count(line) == []

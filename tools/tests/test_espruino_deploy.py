"""The parts of the flash deployer that can be wrong without hardware saying so.

Everything here is about what gets *written*, not about BLE. A bad chunk offset
or a missed dependency produces a device that boots into nothing (decisions.md
D-022), which is the failure this file exists to catch earlier than that.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from tools.espruino_deploy import (
    CHUNK,
    prepare,
    required_modules,
    write_statements,
)

ROOT = Path(__file__).resolve().parent.parent.parent


def test_requires_are_found_by_bare_name() -> None:
    source = 'var a = require("BTHome");\nvar b = require( \'Storage\' );\n'
    assert required_modules(source) == ["BTHome", "Storage"]


def test_a_require_inside_a_comment_is_not_a_dependency() -> None:
    """The module's own usage example contains one, and it names a file that
    does not exist on espruino.com. Scanning the raw source would chase it."""
    source = '// var bw = require("bthome-writable");\nvar x = require("BTHome");\n'
    assert required_modules(prepare(source)) == ["BTHome"]


def test_prepare_refuses_non_ascii_outside_a_comment() -> None:
    with pytest.raises(SystemExit, match="non-ASCII"):
        prepare('var s = "café";\n')


def test_prepare_allows_non_ascii_inside_a_comment() -> None:
    assert prepare("// an em dash — here\nvar x = 1;\n").isascii()


def _replay(statements: list[str]) -> str:
    """Reassemble what the device would hold after running these statements.

    A deliberately literal model of Espruino's Storage: erase, then an
    allocating first write, then writes at byte offsets.
    """
    call = re.compile(r'require\("Storage"\)\.(erase|write)\((.*)\);$')
    content = bytearray()
    declared: int | None = None
    for statement in statements:
        match = call.match(statement)
        assert match, statement
        kind, raw = match.groups()
        if kind == "erase":
            content, declared = bytearray(), None
            continue
        # The argument list is JSON-compatible by construction.
        args = json.loads("[" + raw + "]")
        name, piece, offset = args[0], args[1], args[2]
        assert isinstance(name, str)
        if len(args) == 4:
            declared = args[3]
            content = bytearray(declared)
        assert declared is not None, "a write must follow an allocating write"
        encoded = piece.encode("utf-8")
        content[offset : offset + len(encoded)] = encoded
    assert declared == len(content)
    return content.decode("utf-8")


@pytest.mark.parametrize(
    "content",
    [
        "var x = 1;\n",
        "a" * (CHUNK - 1),
        "a" * CHUNK,
        "a" * (CHUNK + 1),
        "".join(f"var v{i} = {i};\n" for i in range(400)),
    ],
)
def test_written_chunks_reassemble_into_the_original(content: str) -> None:
    assert _replay(write_statements("X", content)) == content


def test_the_first_write_allocates_and_the_rest_do_not() -> None:
    statements = write_statements("X", "a" * (CHUNK * 3))
    assert statements[0].startswith('require("Storage").erase(')
    assert statements[1].endswith(f',0,{CHUNK * 3});')
    for statement in statements[2:]:
        assert not statement.endswith(f",{CHUNK * 3});")


def test_statements_stay_well_under_the_console_statement_limit() -> None:
    """Espruino's console truncates a single statement well before 2 kB, and the
    resulting syntax error points nowhere near the cause."""
    source = prepare((ROOT / "espruino" / "BTHomeWritable.js").read_text("utf-8"))
    longest = max(len(s) for s in write_statements("BTHomeWritable", source))
    assert longest < 1024


def test_the_real_module_and_example_survive_preparation() -> None:
    module = prepare((ROOT / "espruino" / "BTHomeWritable.js").read_text("utf-8"))
    example = prepare(
        (ROOT / "espruino" / "examples" / "light-loop.js").read_text("utf-8")
    )
    # The dependency chain the deployer has to discover, and the export style
    # a Storage module must use for require() to return anything.
    assert required_modules(example) == ["BTHomeWritable"]
    assert required_modules(module) == ["BTHome"]
    assert "exports.setup" in module
    assert _replay(write_statements("BTHomeWritable", module)) == module

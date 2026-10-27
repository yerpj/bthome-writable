"""The pure parts of the radio loader: what goes out, and what comes back.

The input and output of a BLE console cannot be unit-tested, but the two
decisions that made the difference between a load that arrives and one that
does not are plain functions: where a block is cut, and what counts as the
board having finished a line.
"""

from __future__ import annotations

import pytest

from tools.espruino_ble import answers, blocks, chunks, complaints, prompts


def test_a_block_never_ends_inside_a_line() -> None:
    source = "a" * 100 + "\n" + "b" * 200 + "\n" + "c" * 10 + "\n"
    parts = blocks(source, 256)
    assert "".join(parts) == source
    assert all(part.endswith("\n") for part in parts)
    assert [len(part) for part in parts] == [101, 212]


def test_a_line_longer_than_a_block_goes_out_whole() -> None:
    """Cutting it would leave the interpreter holding an unfinished statement
    while the sender waits for a prompt that cannot come."""
    parts = blocks("x" * 400 + "\n", 256)
    assert parts == ["x" * 400 + "\n"]


def test_the_prompt_counts_executions_not_echoes() -> None:
    assert prompts(b">a\r\n=1\r\n>b\r\n=2\r\n>") == 2
    # An arrow function and a comparison are echoed back, and neither is a
    # prompt: minified code never begins a line with one.
    assert prompts(b"var f=(a)=>a>1;\r\n=undefined\r\n>") == 1


def test_an_answer_is_the_line_the_interpreter_prefixes() -> None:
    console = (
        '>process.env.VERSION\r\n="2v27"\r\n>sweep: ready\r\n>SWEEP_MS\r\n=120000\r\n>'
    )
    assert answers(console) == ['"2v27"', "120000"]


def test_the_complaints_are_what_a_half_arrived_load_says() -> None:
    assert complaints("New interpreter error: FIFO_FULL,LOW_MEMORY,MEMORY") == [
        "New interpreter error: FIFO_FULL,LOW_MEMORY,MEMORY"
    ]
    assert complaints("Uncaught SyntaxError: Got UNFINISHED STRING expected EOF")
    assert complaints(">SWEEP_MS\r\n=120000\r\n>") == []


def test_a_chunk_is_at_least_one_byte() -> None:
    assert chunks(b"abcde", 2) == [b"ab", b"cd", b"e"]
    with pytest.raises(ValueError, match="at least one byte"):
        chunks(b"abc", 0)

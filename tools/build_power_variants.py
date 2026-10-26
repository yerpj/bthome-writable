"""The Storage images of §23: one file a recording, ready to boot from flash.

`power-arms.js` selects its arm with the constants at the top, which is right
when a human edits it and wrong when the board is under a meter: every edit is
a chance to measure the wrong thing, and an arm that was re-typed is an arm
nobody can reproduce. So each recording of §23 gets its own built image here,
named after the recording, with the constants it needs and nothing else
changed.

    python -m tools.build_power_variants

**They are made for Storage, not for the console.** A sketch in `.bootcde`
starts when the board powers up, which means the recording can be started
*before* the board is, and the trace then begins at a boot rather than at a
disconnection: no console, no link, no 30 s fast window left over from the Web
IDE letting go. That is the cleanest version of every arm in §23, and it is
also the only one a 23 kB bundle survives on a Puck.js, because each image
sets `pretokenise` on its own first line before anything else in it is parsed.

Writing application code to a bench board's flash is what `docs/shared-bench.md`
forbids, and this is the exception the owner asked for on 2026-10-26: a board
whose storage had to be erased and reflashed anyway, for a measurement that is
worth one power cycle. Erase it when the campaign ends.
"""

from __future__ import annotations

import re
import sys

from tools.build_espruino_bundle import (
    BENCH,
    OUTPUT_DIR,
    ROOT,
    bundle,
    repl_unsafe_lines,
    strip_comments,
)

SOURCE = BENCH / "power-arms.js"
FLAGS = "E.setFlags({pretokenise: 1});"
"""The first statement of every image. Espruino keeps a function's source in
RAM unless it is tokenised, and the bundle does not fit in a Puck.js otherwise:
it leaves 274 JsVars free with the flag and runs out without it. The Web IDE
can tokenise at upload time instead, and setting it here costs nothing and
survives an upload that forgot to."""

SWEEP = "[100, 200, 500, 1000, 2000, 3200, 5000, 10000]"

VARIANTS: dict[str, dict[str, str]] = {
    "power-sweep": {
        "ADV_INTERVAL": "2000",
        "CONNECTION_INTERVAL": "null",
        "MARK": "null",
        "SWEEP": SWEEP,
        "SWEEP_MS": "120000",
        "SWEEP_START_MS": "60000",
    },
    "power-commands": {
        "ADV_INTERVAL": "2000",
        "CONNECTION_INTERVAL": "null",
        "MARK": "null",
        "SWEEP": "null",
    },
    "power-commands-pinned": {
        "ADV_INTERVAL": "2000",
        "CONNECTION_INTERVAL": "7.5",
        "MARK": "null",
        "SWEEP": "null",
    },
}
"""What each recording of §23 is, as constants.

`MARK` is null throughout: the marker channel is not available on this bench
(2026-10-26), and the sweep's steps are read out of the advertising rate in the
current itself instead, which `power_charge --segment` does. The commands are
found the same way, by the shape of a connection.

`SWEEP_START_MS` is 60 s rather than 120 because nothing has to be disconnected
first: it is one clean minute at the idle interval before the sweep starts, and
a data point of its own.
"""


def rewrite(source: str, constants: dict[str, str]) -> str:
    """The same sketch with one arm's constants in it."""
    for name, value in constants.items():
        pattern = re.compile(r"^var " + name + r" = .*?;$", re.MULTILINE)
        source, hits = pattern.subn(f"var {name} = {value};", source)
        if hits != 1:
            raise SystemExit(
                f"{name}: matched {hits} declarations in {SOURCE.name},"
                " expected exactly one"
            )
    return source


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    original = SOURCE.read_text(encoding="utf-8")
    staging = OUTPUT_DIR / ".staging"
    staging.mkdir(exist_ok=True)
    for name, constants in VARIANTS.items():
        variant = staging / f"{name}.js"
        variant.write_text(rewrite(original, constants), encoding="utf-8")
        compact = FLAGS + "\n" + strip_comments(bundle(variant))
        offenders = repl_unsafe_lines(compact)
        if offenders:
            for lineno, line in offenders:
                print(f"  line {lineno}: {line}")
            raise SystemExit(f"{name}: a top-level statement spans lines")
        target = OUTPUT_DIR / f"{name}-storage.min.js"
        with target.open("w", encoding="utf-8", newline="") as handle:
            handle.write(compact)
        print(f"wrote {target.relative_to(ROOT)} ({len(compact)} bytes)")
        print("  " + ", ".join(f"{k}={v}" for k, v in sorted(constants.items())))
        variant.unlink()
    staging.rmdir()
    return 0


if __name__ == "__main__":
    sys.exit(main())

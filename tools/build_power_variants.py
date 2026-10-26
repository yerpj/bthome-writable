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

from pathlib import Path
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

INLINE: tuple[tuple[str, Path, str, bool], ...] = (
    ("BTHome", ROOT / "espruino" / "vendor" / "BTHome.min.js", "BTHomeUpstream", False),
    ("AESCCM", ROOT / "espruino" / "AESCCM.js", "AESCCMInlined", True),
)
"""Every module the image requires that the firmware does not provide, with the
name it is bound to and whether its comments may be stripped.

A sketch booting from `.bootcde` has no Web IDE to resolve a `require()` and no
network to fetch one, so the image carries all of them. Both were found the
hard way, one at a time, on a Puck whose storage had just been erased: BTHome
had been sitting in that storage unrecorded since some earlier session, and
AESCCM behind it. Hence `leftover_requires`, which is the part that stops this
being discovered a third time.

BTHome is upstream and is inlined byte for byte (`espruino/vendor/README.md`).
AESCCM is this project's own and is comment-heavy on purpose, so it goes in
stripped: 7.8 kB of it is mostly the explanation of CCM."""
BUILTINS = frozenset({"Storage", "crypto", "Flash", "heatshrink", "neopixel"})
"""Modules the firmware itself answers for, which is `process.env.MODULES` on
the Puck under test, 2v27: anything else has to be in the image."""
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


def leftover_requires(source: str) -> list[str]:
    """Modules the image still asks for and the firmware will not answer.

    This is the check that was missing. The first build inlined BTHome and
    shipped, the board booted and died on AESCCM, and the only reason it was
    one module rather than three is that there were only two. A boot failure
    reports the symptom it reached, not the module it lacked, so the build is
    the place to notice.
    """
    wanted = set(re.findall(r'require\("([^"]+)"\)', source))
    return sorted(wanted - BUILTINS)


def preamble() -> str:
    """Every inlined module, bound, before anything that uses one.

    The bundler's own flat pattern, and flat on purpose: a closure around a
    whole module is one enormous top-level statement, which the Espruino
    console truncates silently.
    """
    # No section comments: a comment is a top-level line that does not end in
    # a semicolon, which is exactly what repl_unsafe_lines refuses, and it is
    # right to. The order here is the file's structure.
    parts = [FLAGS]
    for _name, path, bound, strip in INLINE:
        source = path.read_text(encoding="utf-8")
        parts.append("var exports = {};")
        parts.append((strip_comments(source) if strip else source).strip())
        parts.append(f"var {bound} = exports;")
    return "\n".join(parts) + "\n"


def resolve(name: str, body: str) -> str:
    """Point every `require()` of an inlined module at its binding."""
    for module, _path, bound, _strip in INLINE:
        call = f'require("{module}")'
        hits = body.count(call)
        if hits == 0:
            raise SystemExit(
                f"{name}: nothing requires {module}, so inlining it is dead"
                " weight in an image that has 274 JsVars to spare"
            )
        body = body.replace(call, bound)
    missing = leftover_requires(body)
    if missing:
        raise SystemExit(
            f"{name}: still requires {', '.join(missing)}, which a board"
            " booting from .bootcde cannot resolve: inline them in INLINE or"
            " name them in BUILTINS"
        )
    return body


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    original = SOURCE.read_text(encoding="utf-8")
    staging = OUTPUT_DIR / ".staging"
    staging.mkdir(exist_ok=True)
    for name, constants in VARIANTS.items():
        variant = staging / f"{name}.js"
        variant.write_text(rewrite(original, constants), encoding="utf-8")
        compact = preamble() + resolve(name, strip_comments(bundle(variant)))
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

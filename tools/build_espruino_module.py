"""Make the EspruinoDocs copies of the modules, from the sources here.

EspruinoDocs is a different house with different habits. Its largest module is
19 kB and its median is 2.5 kB; `espruino/BTHomeWritable.js` is 38 kB, twice
their largest, because this repository comments its reasoning where it happens
and keeps the decision log reachable from the code. That is right here and
wrong there: in their tree, the *why* lives on the module's `.md` page, and a
reviewer meeting a 38 kB file in a 2.5 kB-median directory is being asked to
read the wrong thing.

Hand-copying the module there would be worse than either. A table copied into
three places drifts three times, and this project has already paid for that
lesson (`.module-cache`, D-084). So the published copy is **generated**, and
the generator is this file.

**What it does.** Keeps the first sentence of every block comment and drops the
rest; keeps `//` comments that sit at the end of a line of code, since those
are the short ones; drops standalone `//` comment lines, which in this codebase
are continuations. Nothing is renamed and nothing is reformatted: the result
still reads like the original, which is the point.

**What it does not do.** Minify. EspruinoDocs runs closure-compiler over every
module at build time (`buildmodules.sh`), so `.min.js` is theirs to produce and
not ours to commit.

**Why a generated copy is safe.** `tools/tests/test_espruinodocs_module.py`
strips the comments from both and asserts the remaining bytes are identical,
so the published module is the tested module rather than something that
resembles it. `espruino/test/espruinodocs.test.js` then loads the generated
files and builds the fixtures with them, because the byte comparison cannot
notice a file that no longer parses.

    python -m tools.build_espruino_module
"""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "espruino"
PAGE_DIR = ROOT / "espruino" / "espruinodocs"
OUTPUT_DIR = ROOT / "espruino" / "dist" / "espruinodocs"

MODULES = ("BTHomeWritable.js", "AESCCM.js")

PAGES = ("BTHomeWritable.md", "AESCCM.md")
"""The module pages, written by hand and copied rather than generated.

They carry what the published module no longer does -- the options, the
packet budget, what a rejected write looks like -- because that is where
EspruinoDocs keeps it. Copying them here means the output directory is the
whole pull request, with nothing to remember.
"""

BUDGET = 22_000
"""Within sight of the largest module EspruinoDocs ships, `QOA.js` at 19 027.

Not a technical limit -- a social one, and the one that matters at review time.
Their median module is 2 477 bytes, so arriving with 38 kB asks a reviewer to
read the wrong thing; arriving at 22 kB makes this the largest in the directory
by about 15 %, which is a gap the `.md` page can account for.

The floor is 17 599 bytes, the code with every comment removed. There is no fat
to find: `setup()` is 2 kB, the packet planner 1.5 kB, the write codec 1 kB,
and the rest is spread evenly across a protocol with a declaration, a GATT
profile, encryption in both directions and a counter. Getting under 19 kB would
mean removing capability or diagnostics, and neither is worth being
second-largest rather than largest.
"""

HEADER = """\
/* Copyright (c) 2026 Jean-Philippe Rey. See the file LICENSE for copying permission. */
/* {title}

   Generated from {origin} in github.com/yerpj/bthome-writable, which carries
   the reasoning behind every line. Edit it there. The object ID used to
   declare writable entries is not yet assigned by BTHome: see this module's
   page. */
"""

TITLES = {
    "BTHomeWritable.js": (
        "BTHome downlink: declare writable entries, serve them over GATT."
    ),
    "AESCCM.js": "AES-CCM, from the firmware's own where there is one.",
}


def first_sentence(body: str) -> str:
    """The opening sentence of a block comment, with its layout flattened.

    These comments are written summary-first -- "Both counters, kept coarsely
    in flash." and then four paragraphs of why -- so the first sentence is
    exactly the line a reader of the published module wants.
    """
    text = " ".join(line.strip().lstrip("*").strip() for line in body.splitlines())
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    # A sentence ends at ". " -- but not inside `S5.3`, `0x1E.`, or an ellipsis.
    match = re.search(r"(?<![A-Z0-9])\.(?:\s|$)", text)
    if match:
        text = text[: match.start() + 1]
    return text.strip()


def shrink(source: str) -> str:
    """Comments down to their first sentence; code untouched."""
    out: list[str] = []
    i, n = 0, len(source)
    while i < n:
        char = source[i]
        if char in "\"'`":
            quote = char
            out.append(char)
            i += 1
            while i < n:
                if source[i] == "\\":
                    out.append(source[i : i + 2])
                    i += 2
                    continue
                out.append(source[i])
                if source[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end == -1 else end
            line_start = "".join(out).rsplit("\n", 1)[-1]
            if line_start.strip():
                out.append(source[i:end])  # trailing: short, and about this line
            i = end
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i)
            if end == -1:
                i = n
                continue
            sentence = first_sentence(source[i + 2 : end])
            if sentence:
                indent = "".join(out).rsplit("\n", 1)[-1]
                pad = indent if not indent.strip() else ""
                out.append("/* " + sentence + " */")
                if pad:
                    pass  # the indent is already in `out`
            i = end + 2
            continue
        out.append(char)
        i += 1

    text = "".join(out)
    # Collapse the blank runs the removed paragraphs leave behind.
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failed = False
    for name in MODULES:
        source = (SOURCE_DIR / name).read_text(encoding="utf-8")
        body = shrink(source)
        header = HEADER.format(title=TITLES[name], origin="espruino/" + name)
        text = header + "\n" + body
        (OUTPUT_DIR / name).write_text(text, encoding="utf-8", newline="\n")
        over = " OVER BUDGET" if len(text) > BUDGET else ""
        print(
            f"{name:20} {len(source):6} -> {len(text):6} bytes "
            f"({100 * len(text) / len(source):.0f} %){over}"
        )
        failed = failed or bool(over)

    for page in PAGES:
        text = (PAGE_DIR / page).read_text(encoding="utf-8")
        (OUTPUT_DIR / page).write_text(text, encoding="utf-8", newline="\n")
        print(f"{page:20} {len(text):6} bytes (copied)")

    print(f"\nthe pull request is the contents of {OUTPUT_DIR.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

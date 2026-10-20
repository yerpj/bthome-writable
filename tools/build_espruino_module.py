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

They carry what the published module no longer does -- the options, the packet
budget, what a rejected write looks like -- because that is where EspruinoDocs
keeps it.
"""

TUTORIALS: dict[str, str] = {}
# Empty while "BTHome Light Switch.md" is set aside (D-113). The page and its
# test stay in espruino/espruinodocs/tutorials/, out of the pull request, until
# its content has been clarified.
"""Tutorial pages, which go to `tutorials/` upstream rather than `modules/`.

EspruinoDocs keeps the two apart: `modules/X.md` is a module's reference,
`tutorials/*.md` is somebody being walked through building one thing. The two
BTHome tutorials already there -- "BTHome Setup" and "BTHome Door Sensor" --
are the family this joins, and they set its length and its tone.

They are copied into a `tutorials/` subdirectory of the pull request's folder
while the module files stay at its root, so the folder says where each file
goes without a README to say it. A tutorial brings its images in a folder named
exactly as the page, which is what every illustrated page upstream does.
"""

PULL_REQUESTS = {
    "aesccm": ("AESCCM.js", "AESCCM.md"),
    "bthome-writable": ("BTHomeWritable.js", "BTHomeWritable.md"),
}
"""One directory per pull request, because these are two offers, not one.

`AESCCM` is AES-CCM -- Bluetooth's, Zigbee's -- and is worth having whether or
not BTHome ever assigns an object ID; it also rescues anyone on a Bangle.js 2,
whose firmware builds no generic `AES` at all. `BTHomeWritable` carries a
provisional object ID and needs a Home Assistant integration that lives
elsewhere. Bundled, the second would hold the first hostage.

They go in that order: the writable module's page links to `/AESCCM`.
"""


def directory(name: str) -> Path:
    """Which pull request a file belongs to."""
    for pr, members in PULL_REQUESTS.items():
        if name in members:
            return OUTPUT_DIR / pr
    raise KeyError(name)


BUDGET = 24_000
"""Not a technical limit -- a social one, and the one that matters at review time.

EspruinoDocs serves module JavaScript from two directories, both published at
`/modules/`. `modules/`, where this one goes, holds 101 files: median 2 490
bytes, largest `QOA.js` at 19 027. `devices/` holds 172: median 2 776, largest
`wiolte.js` at 40 601, then `UG96.js` 35 755, `MPU6050_DMP.js` 34 121,
`CCS811_FW.js` 21 688, `VL53L1X.js` 20 918. So five files Espruino already
ships as modules are bigger than this budget, and what a reviewer cannot be
asked to swallow is not a large module but a conspicuously unprecedented one
(sizes measured 2026-10-20).

What reaches a chip is smaller again: the site publishes a minified twin of
every one of those 285 files -- `QOA.min.js` is 15 200 bytes -- and a third of
this file is comments, so stripping those alone takes 21 917 to 18 364.

Raised from 22 000 in D-108, where it had left 83 bytes of headroom and two
accepted proposals to fit into them. The alternative was a fourth round of
comment cutting, and the comments are what defend a provisional object ID to a
maintainer who has not agreed to it yet. On the device they weigh nothing.

The floor is 18 364 bytes, the code with every comment removed. There is no fat
to find: `setup()` is 2 kB, the packet planner 1.5 kB, the write codec 1 kB,
and the rest is spread evenly across a protocol with a declaration, a GATT
profile, encryption in both directions and a counter.
"""

HEADER = """\
/* Copyright (c) 2026 Jean-Philippe Rey. See the file LICENSE for copying permission. */
/* {title}

   Generated from {origin} in github.com/yerpj/bthome-writable, which carries
   the reasoning behind every line. Edit it there.{caveat} */
"""

CAVEATS = {
    "BTHomeWritable.js": (
        "\n\n   BTHome has not assigned the object ID\n"
        "   this uses to declare writable entries: see this module's page."
    ),
    "AESCCM.js": "",
}
"""Only one of these modules is waiting on anybody.

They ship as separate pull requests, and AES-CCM stands on its own: putting a
BTHome caveat at the top of a general-purpose cipher would be telling a reader
to worry about something that cannot affect them.
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
    text = re.sub(r"\n(?:[ \t]*\n){2,}", "\n\n", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    for pr in PULL_REQUESTS:
        (OUTPUT_DIR / pr).mkdir(parents=True, exist_ok=True)
    failed = False
    for name in MODULES:
        source = (SOURCE_DIR / name).read_text(encoding="utf-8")
        body = shrink(source)
        header = HEADER.format(
            title=TITLES[name],
            origin="espruino/" + name,
            caveat=CAVEATS[name],
        )
        text = header + "\n" + body
        (directory(name) / name).write_text(text, encoding="utf-8", newline="\n")
        over = " OVER BUDGET" if len(text) > BUDGET else ""
        print(
            f"{name:20} {len(source):6} -> {len(text):6} bytes "
            f"({100 * len(text) / len(source):.0f} %){over}"
        )
        failed = failed or bool(over)

    for page in PAGES:
        text = (PAGE_DIR / page).read_text(encoding="utf-8")
        (directory(page) / page).write_text(text, encoding="utf-8", newline="\n")
        print(f"{page:20} {len(text):6} bytes (copied)")

    for page, pr in TUTORIALS.items():
        source = PAGE_DIR / "tutorials" / page
        target = OUTPUT_DIR / pr / "tutorials"
        target.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        (target / page).write_text(text, encoding="utf-8", newline="\n")
        images, count = source.with_suffix(""), 0
        if images.is_dir():
            into = target / images.name
            into.mkdir(exist_ok=True)
            for image in sorted(images.iterdir()):
                if image.is_file():
                    (into / image.name).write_bytes(image.read_bytes())
                    count += 1
        extra = f", {count} image(s)" if count else ""
        print(f"{page:20} {len(text):6} bytes (copied{extra})")

    print()
    for pr in PULL_REQUESTS:
        print(f"pull request: the contents of {(OUTPUT_DIR / pr).relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

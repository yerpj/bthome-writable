"""Render a Markdown document to PDF, via a headless browser.

    python -m tools.md_to_pdf docs/first-use-case.md

Keeps the PDF reproducible: it is a build output of a file in the repository,
not a binary someone once exported and cannot regenerate.

The stylesheet is tuned for the kind of document this repository produces —
byte-level protocol tables, box-drawing diagrams, measurement tables — which
mostly means giving monospaced blocks room to breathe and never letting one
wrap, since a wrapped hex dump or diagram is worse than no diagram.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BROWSERS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
)

STYLE = """
@page { size: A4; margin: 18mm 16mm; }

html { font-size: 10.5pt; }
body {
  font-family: "Charter", "Georgia", "Times New Roman", serif;
  line-height: 1.5;
  color: #17181c;
  max-width: none;
  margin: 0;
}

h1 { font-size: 1.9rem; line-height: 1.2; margin: 0 0 0.2rem; letter-spacing: -0.01em; }
h2 {
  font-size: 1.25rem;
  margin: 2.2rem 0 0.6rem;
  padding-bottom: 0.25rem;
  border-bottom: 1px solid #d8dae0;
  page-break-after: avoid;
}
h3 { font-size: 1.02rem; margin: 1.4rem 0 0.4rem; page-break-after: avoid; }
h1 + p { color: #5b6070; margin-top: 0.3rem; }

p, li { orphans: 3; widows: 3; }
ul, ol { padding-left: 1.3rem; }
li { margin: 0.2rem 0; }

code {
  font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace;
  font-size: 0.86em;
  background: #f2f3f6;
  padding: 0.08em 0.3em;
  border-radius: 3px;
}

pre {
  background: #f7f8fa;
  border: 1px solid #e2e4ea;
  border-left: 3px solid #9aa1b1;
  border-radius: 4px;
  padding: 0.7rem 0.9rem;
  overflow: visible;
  page-break-inside: avoid;
}
pre code {
  background: none;
  padding: 0;
  font-size: 8.1pt;
  line-height: 1.35;
  white-space: pre;
}

table {
  border-collapse: collapse;
  width: 100%;
  margin: 0.9rem 0;
  font-size: 0.9rem;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid #dcdee4;
  padding: 0.32rem 0.55rem;
  text-align: left;
  vertical-align: top;
}
th { background: #f2f3f6; font-weight: 600; }
td code, th code { font-size: 0.88em; }

blockquote {
  margin: 1rem 0;
  padding: 0.5rem 0.9rem;
  border-left: 3px solid #c3c7d1;
  background: #fafbfc;
  color: #3d414d;
}
blockquote p { margin: 0.35rem 0; }

hr { border: none; border-top: 1px solid #dcdee4; margin: 1.8rem 0; }

/* Keep a heading with the paragraph that follows it. */
h2, h3 { break-after: avoid-page; }
"""

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>{style}</style></head><body>
{body}
</body></html>
"""


def find_browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).exists():
            return candidate
    for name in ("chrome", "chromium", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit(
        "no Chrome, Chromium or Edge found — needed to render the PDF. "
        "Install one, or convert the Markdown some other way."
    )


def render(source: Path, output: Path) -> None:
    import markdown

    text = source.read_text(encoding="utf-8")
    title = next(
        (
            line.lstrip("# ").strip()
            for line in text.splitlines()
            if line.startswith("# ")
        ),
        source.stem,
    )
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )
    html = TEMPLATE.format(title=title, style=STYLE, body=body)

    with tempfile.TemporaryDirectory() as workdir:
        page = Path(workdir) / "page.html"
        page.write_text(html, encoding="utf-8")

        browser = find_browser()
        print(f"rendering with {Path(browser).name}")
        result = subprocess.run(
            [
                browser,
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                "--run-all-compositor-stages-before-draw",
                "--virtual-time-budget=4000",
                f"--print-to-pdf={output.resolve()}",
                page.resolve().as_uri(),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if not output.exists():
            sys.stderr.write(result.stderr[-2000:] + "\n")
            raise SystemExit(f"the browser produced no {output}")

    size = output.stat().st_size
    print(f"wrote {output} ({size / 1024:.0f} kB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="the Markdown file to render")
    parser.add_argument(
        "--output", type=Path, help="target PDF (default: alongside the source)"
    )
    args = parser.parse_args()

    output = args.output or args.source.with_suffix(".pdf")
    render(args.source, output)
    return 0


if __name__ == "__main__":
    sys.exit(main())

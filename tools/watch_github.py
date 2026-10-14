"""What this project has out in other people's repositories, and what moved.

Five things now live outside this repository, across three projects, and they
are the only places the proposal can succeed or fail. Asking after them by hand
means asking after the ones you remember.

    python -m tools.watch_github            # the table, and what changed
    python -m tools.watch_github --save     # ... and record this as the baseline

State lives in `docs/data/github-watch.json` and is **committed on purpose**:
`git log -p docs/data/github-watch.json` is then the history of how the
submission was received, which is worth more than the file.

Authentication reuses the git credential helper, so there is nothing to set up
and no token in the environment. Read-only: this never writes to GitHub.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs" / "data" / "github-watch.json"

WATCHLIST: tuple[tuple[str, str, int, str], ...] = (
    # repository, kind, number, why it matters
    ("home-assistant/bthome.io", "pulls", 82, "the object id (D-098)"),
    ("Bluetooth-Devices/bthome-ble", "pulls", 424, "the parser (D-098)"),
    ("Bluetooth-Devices/bthome-ble", "issues", 146, "the thread that asked for this"),
    ("Bluetooth-Devices/bthome-ble", "issues", 257, "a capability declaration, uplink"),
    ("Bluetooth-Devices/bthome-ble", "issues", 287, "Shelly BLU range and interval"),
    ("espruino/EspruinoDocs", "pulls", 761, "AESCCM (merged)"),
    ("espruino/EspruinoDocs", "pulls", 762, "BTHomeWritable (merged)"),
    ("espruino/EspruinoDocs", "pulls", 763, "the page corrections (merged)"),
    ("yerpj/bthome-writable", "issues", 1, "@enaon, AES-CCM on a board without AES"),
    ("yerpj/bthome-writable", "issues", 2, "@enaon, ON-OFF-ON"),
)

OURS = "yerpj/bthome-writable"


def token() -> str:
    out = subprocess.run(
        ["git", "credential-manager", "get"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line[len("password=") :]
    raise SystemExit("no GitHub credential; log in with git once")


def api(path: str) -> dict | list:
    request = urllib.request.Request("https://api.github.com" + path)
    request.add_header("Authorization", "Bearer " + token())
    request.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode()[:200]
        raise SystemExit(f"{error.code} on {path}: {detail}") from error


def look() -> dict[str, dict]:
    """Everything the watchlist covers, in one shape."""
    found: dict[str, dict] = {}
    for repo, kind, number, why in WATCHLIST:
        item = api(f"/repos/{repo}/{kind}/{number}")
        assert isinstance(item, dict)
        state = item["state"]
        if item.get("merged"):
            state = "merged"
        found[f"{repo}#{number}"] = {
            "why": why,
            "state": state,
            "comments": item["comments"],
            "updated": item["updated_at"],
            "title": item["title"],
            "url": item["html_url"],
        }

    runs = api(f"/repos/{OURS}/actions/runs?per_page=1")
    assert isinstance(runs, dict)
    run = runs["workflow_runs"][0]
    found["ci"] = {
        "why": "our own CI, last run",
        "state": run["conclusion"] or run["status"],
        "comments": 0,
        "updated": run["created_at"],
        "title": run["head_sha"][:7] + " " + run["head_branch"],
        "url": run["html_url"],
    }
    return found


def changes(before: dict, after: dict) -> list[str]:
    lines = []
    for key, now in after.items():
        was = before.get(key)
        if was is None:
            lines.append(f"NEW      {key}: {now['state']}")
            continue
        if was["state"] != now["state"]:
            lines.append(f"STATE    {key}: {was['state']} -> {now['state']}")
        if now["comments"] > was["comments"]:
            delta = now["comments"] - was["comments"]
            lines.append(
                f"COMMENT  {key}: {delta} new ({was['comments']} -> {now['comments']})"
            )
        elif now["comments"] < was["comments"]:
            lines.append(f"COMMENT  {key}: a comment was removed")
    for key in before:
        if key not in after:
            lines.append(f"GONE     {key}: no longer watched")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--save", action="store_true", help="record this reading as the baseline"
    )
    args = parser.parse_args()

    before = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    after = look()

    width = max(len(k) for k in after)
    for key, item in after.items():
        print(
            f"  {key:{width}}  {item['state']:9} {item['comments']:2} comment(s)  "
            f"{item['updated'][:16]}  {item['why']}"
        )

    moved = changes(before, after)
    print()
    if not before:
        print("no baseline yet; run with --save to make this one")
    elif moved:
        print("CHANGED since the last reading:")
        for line in moved:
            print("   ", line)
    else:
        print("nothing has moved since the last reading")

    if args.save:
        STATE.write_text(
            json.dumps(after, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"\nbaseline written to {STATE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

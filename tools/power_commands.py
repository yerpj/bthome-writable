"""Drive the commands of §23's recordings 2 to 4, from Home Assistant.

The sweep needs no central. The command recordings need one, and it has to be
Home Assistant rather than this host: what a command costs the device depends
on the connection interval the central negotiates and on how long it holds the
link, so a figure taken with `tools.bthome_write` from a Windows adapter is not
the figure an adopter will see. This calls the service and nothing else.

    python -m tools.power_commands --entity switch.bureau_mobilesensf7b9_light \\
        --count 10 --every 45 --out docs/data/power-puck-commands-calls.json

**45 seconds apart, not faster.** `fastTimeout` is 30 s, so a command sent
sooner is measured from inside the fast window the previous one opened rather
than from idle, and the per-command charge then depends on the spacing instead
of on the command. The checks of recording 4 are the deliberate exception: they
ask what happens at one and four commands a minute, which is the saturation
itself.

The trace is the witness, so nothing here waits for the device: the service
call returns as soon as the command is queued, about 0.3 s, long before
anything reaches the radio. What this writes down is the count and the spacing,
which is what the analysis checks itself against -- ten connections in the
trace, 45 s apart, or something happened that the current will explain.

A command is a write on a shared bench (`docs/shared-bench.md`): take the lock.
Needs `HA_URL` and `HA_TOKEN` in the environment.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_URL = "http://haosjry.local:8123"
TIMEOUT = 30
LEAD_IN_S = 5.0
"""Seconds between the start of this command and the first service call, so
that the trace holds a stretch of undisturbed idle to measure the floor
against even if the recording was started late."""


def schedule(count: int, every: float, lead_in: float = LEAD_IN_S) -> list[float]:
    """When each command goes out, in seconds from the start of the run."""
    if count < 1:
        raise ValueError("a run of no commands measures nothing")
    if every <= 0:
        raise ValueError("commands need a spacing")
    return [lead_in + index * every for index in range(count)]


def _call(url: str, token: str, path: str, payload: dict | None) -> object:
    data = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        url.rstrip("/") + path,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=TIMEOUT) as answer:
        body = answer.read()
    return json.loads(body) if body else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity", required=True, help="the entity to command")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument(
        "--every", type=float, default=45.0, help="seconds between commands"
    )
    parser.add_argument("--lead-in", type=float, default=LEAD_IN_S)
    parser.add_argument(
        "--service",
        default="toggle",
        help="the service on the entity's own domain (default toggle, which is"
        " the one that always changes the value)",
    )
    parser.add_argument("--out", type=Path, help="write the call times as JSON")
    args = parser.parse_args(argv)

    url = os.environ.get("HA_URL", DEFAULT_URL)
    token = os.environ.get("HA_TOKEN")
    if not token:
        raise SystemExit("HA_TOKEN is not set; source the bench env file")

    domain = args.entity.split(".", 1)[0]
    when = schedule(args.count, args.every, args.lead_in)

    try:
        before = _call(url, token, f"/api/states/{args.entity}", None)
    except (HTTPError, URLError) as exc:
        raise SystemExit(f"{args.entity}: {exc}") from None
    state = before.get("state") if isinstance(before, dict) else None
    print(f"{args.entity} is {state!r}")
    if state in (None, "unavailable", "unknown"):
        raise SystemExit(
            f"{args.entity} is {state!r}: Home Assistant will not command it."
            " After a storage erase the device's counter restarts and"
            " bthome-ble drops its advertisements as replays, which is what"
            " this looks like. Reload the device's config entries first."
        )

    print(
        f"{args.count} commands, {args.every:g} s apart,"
        f" first in {args.lead_in:g} s:"
        f" {when[-1] + args.lead_in:.0f} s in all"
    )
    started = time.monotonic()
    calls: list[dict] = []
    for index, due in enumerate(when, 1):
        delay = due - (time.monotonic() - started)
        if delay > 0:
            time.sleep(delay)
        at = time.monotonic() - started
        wall = time.time()
        try:
            _call(
                url,
                token,
                f"/api/services/{domain}/{args.service}",
                {"entity_id": args.entity},
            )
            failed = None
        except (HTTPError, URLError) as exc:
            failed = str(exc)
        took = time.monotonic() - started - at
        print(
            f"  {index:>3}/{args.count}  at {at:7.2f} s"
            f"  returned in {took:5.2f} s" + (f"  FAILED: {failed}" if failed else "")
        )
        calls.append(
            {
                "n": index,
                "at_s": round(at, 3),
                "wall": wall,
                "returned_in_s": round(took, 3),
                "error": failed,
            }
        )

    if args.out:
        args.out.write_text(
            json.dumps(
                {
                    "entity": args.entity,
                    "service": f"{domain}.{args.service}",
                    "count": args.count,
                    "every_s": args.every,
                    "calls": calls,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"written to {args.out}")
    return 1 if any(call["error"] for call in calls) else 0


if __name__ == "__main__":
    sys.exit(main())

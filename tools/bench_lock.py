"""One agent at a time on the bench.

The bench is Home Assistant plus the single Bluetooth adapter it owns plus the
Espruino devices in front of it. None of those can be shared, and the reason is
worth stating because it is not obvious: the failure mode is *silent*. If a
second agent redeploys `custom_components/bthome_writable` while the first one
is running a hardware test, the first one's test still passes -- against code it
did not write. That mistake has already been made twice in this project from a
single agent misreading its own results (see D-039 and D-041 in
`spec/decisions.md`); two agents make it trivially easy.

So: writes to the bench are serialised by a lock, reads are always free.

The lock is a single file on the Home Assistant configuration share, because
that share is reachable from any machine on the network and *is* the contended
resource. `O_EXCL` is honoured over SMB here (verified), so acquiring is a real
atomic test-and-set rather than a check followed by a hopeful write.

    python -m tools.bench_lock status
    python -m tools.bench_lock acquire --holder claude-a --note "T4.1 retries"
    python -m tools.bench_lock renew
    python -m tools.bench_lock release

Every lock carries an expiry. An agent that crashes mid-test must not leave the
bench unusable until a human notices, so a stale lock can be taken -- loudly,
and only once it has actually expired.

This lock is advisory. It cannot stop an agent that does not ask, and it cannot
arbitrate a power rail. It makes the common case correct and the collision
visible; that is all it is for.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from typing import Any

# On the Home Assistant configuration share: visible to every agent, and next
# to the integration it protects. Forward slashes because Python opens a UNC
# path this way without the backslash quoting getting mangled by a shell.
DEFAULT_LOCK = "//haosjry.local/config/bthome-writable.lock"

# Long enough that a hardware run does not have to renew mid-test, short enough
# that a crashed agent frees the bench before anyone is blocked for an evening.
DEFAULT_LEASE_MINUTES = 30


def lock_path() -> str:
    return os.environ.get("BENCH_LOCK", DEFAULT_LOCK)


def default_holder() -> str:
    return os.environ.get("BENCH_HOLDER") or f"{socket.gethostname()}:{os.getpid()}"


def read_lock(path: str) -> dict[str, Any] | None:
    """The current holder, or None if the bench is free.

    A lock file that cannot be parsed is treated as held by an unknown agent
    rather than as absent: a truncated write is a reason to go and look, not a
    reason to assume the bench is yours.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    except FileNotFoundError:
        # Absent means free only if the place it would be is reachable. An
        # unmounted share also raises FileNotFoundError, and reporting that as a
        # free bench is exactly the silent wrong answer this tool exists to
        # prevent.
        if not os.path.isdir(os.path.dirname(path)):
            raise OSError("the directory holding the lock is unreachable") from None
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"holder": "<unreadable lock file>", "expires": time.time() + 60}


def remaining(lock: dict[str, Any]) -> float:
    return float(lock.get("expires", 0)) - time.time()


def describe(lock: dict[str, Any]) -> str:
    left = remaining(lock)
    when = "expired " if left < 0 else ""
    note = lock.get("note")
    return (
        f"{lock.get('holder', '?')}"
        + (f" -- {note}" if note else "")
        + f" ({when}{abs(left) / 60:.0f} min"
        + ("" if left < 0 else " left")
        + ")"
    )


def write_lock(path: str, holder: str, note: str, minutes: int, *, steal: bool) -> None:
    payload = {
        "holder": holder,
        "note": note,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "acquired": time.time(),
        "acquired_readable": time.strftime("%Y-%m-%d %H:%M:%S"),
        "expires": time.time() + minutes * 60,
        "lease_minutes": minutes,
    }
    body = json.dumps(payload, indent=2) + "\n"
    if steal:
        # Taking over an expired lock: the holder is gone by definition, so
        # there is nobody to race against and a plain write is honest.
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
    else:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(body)


def cmd_status(args: argparse.Namespace) -> int:
    lock = read_lock(lock_path())
    if lock is None:
        print("bench free")
        return 0
    state = "EXPIRED" if remaining(lock) < 0 else "held"
    print(f"bench {state}: {describe(lock)}")
    return 0 if remaining(lock) < 0 else 1


def cmd_acquire(args: argparse.Namespace) -> int:
    path = lock_path()
    holder = args.holder or default_holder()
    deadline = time.time() + args.wait * 60

    while True:
        current = read_lock(path)

        if current is not None and current.get("holder") == holder:
            # Already ours. Re-acquiring is a renew, not an error; an agent
            # should not have to remember whether it took the lock earlier.
            write_lock(path, holder, args.note, args.minutes, steal=True)
            print(f"still yours, extended {args.minutes} min")
            return 0

        if current is not None and remaining(current) < 0:
            print(
                f"breaking an expired lock held by {describe(current)}",
                file=sys.stderr,
            )
            write_lock(path, holder, args.note, args.minutes, steal=True)
            print(f"acquired by {holder} for {args.minutes} min (was stale)")
            return 0

        if current is None:
            try:
                write_lock(path, holder, args.note, args.minutes, steal=False)
            except FileExistsError:
                # Someone won the race between the read and the create. Loop
                # and treat them as the holder, which they are.
                continue
            print(f"acquired by {holder} for {args.minutes} min")
            return 0

        if time.time() >= deadline:
            print(f"bench busy: {describe(current)}", file=sys.stderr)
            return 1
        time.sleep(args.poll)


def cmd_renew(args: argparse.Namespace) -> int:
    path = lock_path()
    holder = args.holder or default_holder()
    current = read_lock(path)
    if current is None:
        print("no lock to renew", file=sys.stderr)
        return 1
    if current.get("holder") != holder:
        print(f"not yours to renew: {describe(current)}", file=sys.stderr)
        return 1
    note = args.note or current.get("note", "")
    write_lock(path, holder, note, args.minutes, steal=True)
    print(f"renewed {args.minutes} min")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    path = lock_path()
    holder = args.holder or default_holder()
    current = read_lock(path)
    if current is None:
        print("bench already free")
        return 0
    if current.get("holder") != holder and not args.force:
        print(
            f"not yours to release: {describe(current)}\n"
            "pass --force only if you know that agent is gone",
            file=sys.stderr,
        )
        return 1
    os.remove(path)
    print("released")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--holder",
            default=None,
            help="who you are; defaults to $BENCH_HOLDER or host:pid",
        )

    p = sub.add_parser("status", help="who holds the bench")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("acquire", help="take the bench")
    common(p)
    p.add_argument("--note", default="", help="what you are about to do")
    p.add_argument("--minutes", type=int, default=DEFAULT_LEASE_MINUTES)
    p.add_argument(
        "--wait",
        type=float,
        default=0,
        help="minutes to wait for a busy bench (default: fail immediately)",
    )
    p.add_argument("--poll", type=float, default=10, help="seconds between retries")
    p.set_defaults(func=cmd_acquire)

    p = sub.add_parser("renew", help="extend your lease")
    common(p)
    p.add_argument("--note", default="")
    p.add_argument("--minutes", type=int, default=DEFAULT_LEASE_MINUTES)
    p.set_defaults(func=cmd_renew)

    p = sub.add_parser("release", help="give the bench back")
    common(p)
    p.add_argument("--force", action="store_true", help="release someone else's lock")
    p.set_defaults(func=cmd_release)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except OSError as error:
        # The share lives on the Home Assistant host, so it disappears when the
        # host is down, when its Samba add-on has not started, or when this
        # machine has lost the mount -- all three seen on 2026-09-17. A bare
        # traceback there reads like a bug in the lock; this says what to fix.
        print(
            f"bench lock unavailable: cannot reach {lock_path()} ({error}).\n"
            "Check that Home Assistant is up, that its Samba add-on is started, "
            "and that the share is mounted on this machine.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())

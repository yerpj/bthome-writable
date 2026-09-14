"""Cut and restore the power to the board under test.

The OOTY is a hardware debug aid sitting on the bench: among other things it
switches a 3V3 rail, and the Puck.js is on that rail. That removes a whole class
of incident from this project. Twice now a deployment has left the device
unable to advertise, and therefore unable to be connected to, and therefore
unfixable without a finger on the button (decisions.md D-029, D-031). A rail
that can be cycled from here makes those recoverable.

    python -m tools.ooty state
    python -m tools.ooty on
    python -m tools.ooty off
    python -m tools.ooty cycle --off-ms 1500

The protocol client lives in the OOTY repository rather than here, so that there
is one implementation of its framing; point `OOTY_PATH` at that checkout if it
is not in the default place. This module only adds what this project needs:
retries, because switching the rail sometimes disturbs the board's own USB and
the port has to be reopened.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

DEFAULT_OOTY = Path(os.environ.get("OOTY_PATH", r"C:/Users/JP/Documents/perso/OOTY"))
RETRIES = 5


def _client():
    """The OOTY protocol client, imported from its own repository."""
    tests = DEFAULT_OOTY / "tests"
    if not tests.is_dir():
        raise SystemExit(
            f"no OOTY checkout at {DEFAULT_OOTY} -- set OOTY_PATH to point at one"
        )
    if str(tests) not in sys.path:
        sys.path.insert(0, str(tests))
    from ootybench.protocol import Ooty, find_port

    return Ooty, find_port


def command(text: str, retries: int = RETRIES) -> str:
    """Run one command, reopening the port if the board drops off USB.

    Switching the rail occasionally takes the board's own CDC interface down
    with it; the command has usually been executed by then, but the answer is
    lost. Retrying a read-back settles what actually happened.
    """
    Ooty, find_port = _client()
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with Ooty(find_port()) as board:
                return board.command(text)
        except Exception as error:  # pyserial raises several unrelated types
            last = error
            if attempt < retries:
                time.sleep(2.0)
    raise SystemExit(f"OOTY did not answer {text!r} after {retries} tries: {last}")


def rail() -> str:
    return command("SW3V3")


def set_rail(on: bool, settle: float = 1.0) -> str:
    """Switch the rail and report what it reads back as, not what we asked.

    What comes back is the signal the board drives, not a measurement: the
    control line is open-drain and active low, so an ON rail reads ON while its
    pin sits at 0. `VM` would not help -- it watches the switched VBUS input,
    which is a different rail entirely. Whether the board under test actually
    came up is answered by the board under test.
    """
    command("SW3V3 ON" if on else "SW3V3 OFF")
    time.sleep(settle)
    return rail()


def cycle(off_ms: int = 1500) -> str:
    before = set_rail(False)
    time.sleep(off_ms / 1000.0)
    after = set_rail(True)
    return f"off: {before} -> on: {after}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["state", "on", "off", "cycle"])
    parser.add_argument(
        "--off-ms",
        type=int,
        default=1500,
        help="how long to stay off during a cycle (default 1500)",
    )
    args = parser.parse_args()

    if args.action == "state":
        print(f"3V3 rail: {rail()}")
    elif args.action == "cycle":
        print(cycle(args.off_ms))
    else:
        print(f"3V3 rail: {set_rail(args.action == 'on')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

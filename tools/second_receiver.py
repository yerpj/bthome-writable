"""The same measurement, from a second central, so the two can be compared.

Every latency figure in this project came from one receiver: Home Assistant on a
Raspberry Pi, one `bcm43438`, one BlueZ. "A first command costs two to three
advertising events" may be a property of the protocol or a property of that
stack, and nothing measured so far can tell the two apart.

This runs the regression harness's sample plan from the bench host instead --
Windows, WinRT, `bleak`, a different adapter -- and prints it beside the
baseline Home Assistant recorded. Same boundary (command issued to GATT write
acknowledged), same interval, same counts, same fast-window guarantee, so the
difference between the two columns is the receiver and nothing else.

    python -m tools.bench_lock acquire --note "second receiver"
    python -m tools.second_receiver
    python -m tools.second_receiver --device puck
    python -m tools.bench_lock release

**What this host is known to do**, measured rather than assumed: it takes about
half a second longer to establish a link than BlueZ, and it stops delivering
advertisements for several seconds after a disconnect (D-047). Both are reasons
to expect it to be *slower*, not faster; a column that comes out faster is worth
distrusting before it is worth believing.

Nothing here goes through the integration, so the receiver-side work of D-059
and D-064 is not in these numbers. What is shared is the device: the same
sketch, the same advertising interval, the same fast-advertising window.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import time

from tools.devices import DEVICES
from tools.regression import (
    BASELINE,
    FAST_TIMEOUT_MS,
    FIRST_REPS,
    GAP_S,
    IDLE_S,
    INTERVAL_MS,
    REPEAT_REPS,
    summarise,
)

OUT = Path("docs/data/second-receiver.json")


def as_sample(got: dict, phases: dict) -> dict:
    """Put a host-side measurement into the shape the summary reads.

    The host times three phases -- catching an advertisement, connecting, and
    the write -- while Home Assistant reports the wait in its queue, the time to
    open the link, and the write. Catching the advertisement *is* part of
    opening the link, so the two line up once it is folded in: `connect_ms` is
    everything before the write on both sides, and `total_ms` is the whole
    command on both sides.
    """
    if phases.get("failed"):
        return {"failed": True, **got}
    connect = phases["discover"] + phases["connect"]
    return {
        "connect_ms": connect * 1000,
        "write_ms": phases["write"] * 1000,
        "total_ms": (connect + phases["write"]) * 1000,
        "retries": phases["retries"],
        **got,
    }


async def measure(config: dict, kind_payloads: list[bytes]) -> dict:
    """First commands after a quiet period, then a burst, as the guard does."""
    from tools.latency_sweep import one_write
    from tools.latency_sweep_write import FastWindow, set_fast_timeout, set_interval

    window = FastWindow(FAST_TIMEOUT_MS)
    await set_fast_timeout(config, FAST_TIMEOUT_MS)
    window.touched()
    await set_interval(config, INTERVAL_MS)
    window.touched()

    first: list[dict] = []
    for index in range(FIRST_REPS):
        await asyncio.sleep(IDLE_S)
        idle_for = window.idle_for()
        phases = await one_write(
            config["address"], 1, kind_payloads[index % len(kind_payloads)]
        )
        got = as_sample(window.classify("first", idle_for), phases)
        window.touched()
        first.append(got)
        print(f"  first  {_line(got)}", flush=True)

    repeat: list[dict] = []
    for index in range(REPEAT_REPS):
        idle_for = window.idle_for()
        phases = await one_write(
            config["address"], 1, kind_payloads[index % len(kind_payloads)]
        )
        got = as_sample(window.classify("next", idle_for), phases)
        window.touched()
        repeat.append(got)
        print(f"  repeat {_line(got)}", flush=True)
        await asyncio.sleep(GAP_S)

    return {"first": first, "repeat": repeat}


def _line(got: dict) -> str:
    if got.get("failed"):
        return "FAILED"
    flag = (
        "" if got.get("fast_window_ok", True) else "  << wrong side of the fast window"
    )
    return f"{got['total_ms'] / 1000:5.2f} s{flag}"


ROWS = (
    ("first command, median", "first_median_s", "s"),
    ("first command, 90th percentile", "first_p90_s", "s"),
    ("repeated command, median", "repeat_median_s", "s"),
    ("repeated command, 90th percentile", "repeat_p90_s", "s"),
    ("the write itself", "write_median_ms", "ms"),
    ("delivered", "delivered_fraction", ""),
    ("connected without a retry", "direct_fraction", ""),
)


def render(device: str, ha: dict | None, host: dict) -> None:
    print(f"\n{device}")
    print(f"  {'':<34} {'Home Assistant':>15} {'bench host':>12} {'ratio':>8}")
    for label, key, unit in ROWS:
        there = ha.get(key) if ha else None
        here = host[key]
        ratio = f"{here / there:.2f}x" if there else "--"
        left = f"{there:.3f}" if there is not None else "--"
        print(f"  {label:<34} {left:>15} {here:>12.3f} {ratio:>8}  {unit}")
    stale = host["samples_on_the_wrong_side_of_the_fast_window"]
    if stale:
        print(f"  {stale} sample(s) on the wrong side of the fast window")


async def run(args) -> int:
    import aiohttp

    from tools.ha_bench import bench_prepared
    from tools.latency_sweep import payloads
    from tools.latency_sweep_write import set_fast_timeout

    baseline = (
        json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    )
    devices = [args.device] if args.device else list(DEVICES)
    results: dict[str, dict] = {}

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with (
        aiohttp.ClientSession(connector=connector) as session,
        # The proxy is Home Assistant's path and irrelevant here; the automation
        # is not -- it writes to the nice!nano every 30 s, which would hold that
        # device's fast window open under this measurement.
        bench_prepared(session) as changed,
    ):
        print("bench: " + ("; ".join(changed) or "already as wanted"), flush=True)
        for name in devices:
            config = DEVICES[name]
            print(
                f"\n=== {name} at {INTERVAL_MS} ms, from the bench host ===",
                flush=True,
            )
            try:
                run_result = await measure(config, payloads(config["kind"]))
                results[name] = summarise(run_result["first"], run_result["repeat"])
            finally:
                try:
                    await set_fast_timeout(config, 30000)
                except Exception as error:  # the bench matters more
                    print(f"  could not restore the fast window: {error}")

    for name, host in results.items():
        render(name, baseline.get("devices", {}).get(name), host)

    OUT.write_text(
        json.dumps(
            {
                "recorded": time.strftime("%Y-%m-%d"),
                "receiver": "Windows bench host, WinRT via bleak",
                "compared_with": str(BASELINE),
                "interval_ms": INTERVAL_MS,
                "first_reps": FIRST_REPS,
                "repeat_reps": REPEAT_REPS,
                "fast_timeout_ms": FAST_TIMEOUT_MS,
                "devices": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwritten to {OUT}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=tuple(DEVICES))
    args = parser.parse_args()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

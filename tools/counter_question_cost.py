"""What the counter question of §5.6 costs, carried one way or the other.

The question used to take a connection of its own: one at setup, and one before
any command whose device had moved its settings revision. It now rides the
connection the command itself makes (D-129). This measures the difference where
a user feels it, which is the first command after Home Assistant restarts or
reloads the entry -- the case @enaon reported as 5 to 10 s on his lights.

Two cases per arm, because the answer is not the same in both:

*immediate* -- the command is issued half a second after the reload, which is a
user reaching for a switch as Home Assistant comes back. Folded, the command
makes one connection and carries the question inside it. Separate, the question
connects first and the command queues behind it on the connection semaphore.

*settled* -- the command is issued 40 s after the reload, past the module's
default fast window, so the separate question has long finished and the command
is an ordinary first command. This is where the fold *costs*: the exchange is
inside the connection, and nothing was saved because nothing was waiting.

    python -m tools.counter_question_cost --arm folded   --reps 3
    python -m tools.counter_question_cost --arm separate --reps 3

The arm is a label: it says which code is deployed, and this tool does not
change it. To switch arms, set `FOLD_THE_COUNTER_QUESTION_INTO_A_WRITE` in the
deployed `const.py` and restart Home Assistant.

**What the device has to be.** The question is only asked of a device that is
sealed and offers the counter report, so the board must be running a sketch with
a `bindkey` and `counterReport: true` -- `espruino/examples/encrypted-light.js`
is one -- and the configured device in Home Assistant must hold the same
bindkey. Against a device in clear this tool measures nothing: no question is
ever owed, and every sample is an ordinary first command.

It is a bench write: it commands the device and reloads a config entry. Take the
lock (`docs/shared-bench.md`).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics as st
import time

import aiohttp

from tools.devices import DEVICES

IDLE_S = 40.0
"""Seconds to leave the device alone before a sample.

Past the module's 30 s default fast window, so every sample's connection pays
the idle advertising interval rather than the fast one (D-024, §16).
"""

SETTLED_S = 40.0
"""How long the *settled* case waits after the reload before commanding.

Long enough that a question with a connection of its own has finished, so the
two arms differ only in where the exchange happened.
"""

IMMEDIATE_S = 0.5
"""And how long the *immediate* case waits: a user reaching for a switch."""


async def entry_for(session: aiohttp.ClientSession, address: str) -> str:
    """The config entry that carries this device, by its address."""
    base = os.environ["HA_URL"].rstrip("/")
    headers = {"Authorization": "Bearer " + os.environ["HA_TOKEN"]}
    async with session.get(
        f"{base}/api/config/config_entries/entry",
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=30),
    ) as response:
        entries = await response.json()
    tail = address.replace(":", "")[-4:].lower()
    for entry in entries:
        if entry.get("domain") != "bthome_writable":
            continue
        if tail in str(entry.get("title", "")).lower():
            return entry["entry_id"]
    raise SystemExit(f"no bthome_writable config entry found for {address}")


async def reload(session: aiohttp.ClientSession, entry_id: str) -> None:
    """Re-run setup for one device, which is a restart as this code sees it."""
    base = os.environ["HA_URL"].rstrip("/")
    headers = {"Authorization": "Bearer " + os.environ["HA_TOKEN"]}
    async with session.post(
        f"{base}/api/config/config_entries/entry/{entry_id}/reload",
        headers=headers,
        json={},
        timeout=aiohttp.ClientTimeout(total=120),
    ) as response:
        if response.status != 200:
            raise SystemExit(f"reload refused: {response.status}")


async def sample(bus, config: dict, index: int, case: str) -> dict:
    """One reload and one command, with the wait the case asks for."""
    from tools.latency_sweep_write import command

    await asyncio.sleep(IDLE_S)
    reloaded = time.monotonic()
    await reload(bus.session, config["entry_id"])
    await asyncio.sleep(IMMEDIATE_S if case == "immediate" else SETTLED_S)
    issued = time.monotonic()
    got = await command(bus, config, index, timeout=90.0)
    got |= {
        "case": case,
        "since_reload_s": round(issued - reloaded, 2),
        "wall_s": round(time.monotonic() - issued, 2),
    }
    return got


def render(arm: str, samples: list[dict]) -> None:
    print(f"\n=== {arm} " + "=" * 50)
    print(f"{'case':<10} {'wall':>7} {'connect':>9} {'counter':>9} {'write':>8}")
    for got in samples:
        if got.get("failed"):
            print(f"{got['case']:<10}   FAILED")
            continue
        print(
            f"{got['case']:<10} {got['wall_s']:6.2f} s"
            f" {got['connect_ms'] / 1000:8.2f} s"
            f" {got.get('counter_ms', 0):8.0f} ms"
            f" {got['write_ms']:7.0f} ms"
        )
    for case in ("immediate", "settled"):
        totals = [s["wall_s"] for s in samples if s.get("case") == case]
        if totals:
            print(
                f"  {case}: median {st.median(totals):.2f} s"
                f" over {len(totals)} sample(s)"
            )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=sorted(DEVICES), default="puck")
    parser.add_argument(
        "--arm",
        choices=("folded", "separate"),
        required=True,
        help="which code is deployed; a label, not a switch",
    )
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--out", help="write the samples here as JSON")
    args = parser.parse_args()

    from tools.ha_bench import bench_prepared
    from tools.latency_sweep_write import Bus

    config = dict(DEVICES[args.device])
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    samples: list[dict] = []
    async with aiohttp.ClientSession(connector=connector) as session:
        config["entry_id"] = await entry_for(session, config["address"])
        print(f"{args.device}: config entry {config['entry_id']}", flush=True)
        async with bench_prepared(session) as changed:
            print("bench: " + ("; ".join(changed) or "already as wanted"), flush=True)
            bus = Bus(session)
            await bus.open()
            try:
                index = 0
                for case in ("immediate", "settled"):
                    for _ in range(args.reps):
                        index += 1
                        got = await sample(bus, config, index, case)
                        samples.append(got)
                        print(
                            f"  {case:<10} "
                            + ("FAILED" if got.get("failed") else f"{got['wall_s']} s"),
                            flush=True,
                        )
            finally:
                await bus.close()

    render(args.arm, samples)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"arm": args.arm, "samples": samples}, handle, indent=2)
        print(f"\nsamples written to {args.out}")
    return 0


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        raise SystemExit(asyncio.run(main()))

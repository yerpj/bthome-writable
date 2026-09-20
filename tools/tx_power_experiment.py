"""Does the received signal level change how long a first command takes?

A central cannot begin a connection until it catches an advertising event, and a
packet lost to noise costs a whole advertising interval — so link quality ought
to show up in exactly the number `tools/latency_sweep_write.py` measures. The two
bench devices sit 7 dB apart as the receiver hears them, which is not an
experiment: they also differ in hardware, firmware and position.

This is the experiment. One device, one position, one advertising interval, and
the only thing that changes is its transmit power:

    python -m tools.tx_power_experiment --device puck --interval 1200 \
        --powers 4 -20 --reps 10 --out docs/data/tx-power-puck.json

Espruino's `NRF.setTxPower` accepts -40, -20, -16, -12, -8, -4, 0 and 4 dBm. The
tool reports the level Home Assistant's scanner actually sees at each setting,
so the x axis is a measured RSSI rather than a requested power.

Needs `HA_URL` and `HA_TOKEN`, as the sweep does.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import statistics
import sys

from tools.latency_sweep_write import (
    DEVICES,
    Bus,
    command,
    run_on_device,
    set_fast_timeout,
    set_interval,
)


async def rssi_now(address: str, seconds: float = 20.0) -> dict | None:
    """The level this host hears from the device, measured rather than asked for.

    Home Assistant's diagnostics carry an RSSI too, but it lagged a 24 dB change
    by 21 dB when this was checked — it is whatever the last advertisement
    happened to give, and the scanner had not caught up. A short scan here is
    slower and true.
    """
    import statistics

    from bleak import BleakScanner

    seen: list[int] = []

    def heard(device, advertisement) -> None:
        if device.address.upper() == address:
            seen.append(advertisement.rssi)

    async with BleakScanner(heard):
        await asyncio.sleep(seconds)

    if not seen:
        return None
    return {
        "median": statistics.median(seen),
        "min": min(seen),
        "max": max(seen),
        "packets": len(seen),
    }


async def run(args) -> int:
    config = DEVICES[args.device]
    results = []

    import aiohttp

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        bus = Bus(session)
        await bus.open()
        index = 0
        try:
            await set_fast_timeout(config, 3000)
            await set_interval(config, args.interval)

            for power in args.powers:
                print(f"\n=== {power:+} dBm ===", flush=True)
                await run_on_device(config, f"NRF.setTxPower({power});")
                await asyncio.sleep(20)  # let the receiver hear the new level
                seen = await rssi_now(config["address"])
                if seen:
                    print(
                        f"  this host hears {seen['median']:.0f} dBm "
                        f"({seen['packets']} packets, {seen['min']} to {seen['max']})",
                        flush=True,
                    )
                else:
                    print("  this host hears nothing", flush=True)

                samples = []
                for _ in range(args.reps):
                    await asyncio.sleep(args.idle)
                    index += 1
                    got = await command(bus, config, index, args.timeout)
                    if got.get("failed"):
                        print("  FAILED", flush=True)
                    else:
                        print(
                            f"  {got['total_ms'] / 1000:5.2f} s "
                            f"(connect {got['connect_ms'] / 1000:.2f})",
                            flush=True,
                        )
                    samples.append(got)

                results.append({"tx_power": power, "rssi": seen, "samples": samples})
                if args.out:
                    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                    Path(args.out).write_text(
                        json.dumps(
                            {
                                "address": config["address"],
                                "label": config["label"],
                                "interval_ms": args.interval,
                                "measures": "command to GATT write acknowledgement, "
                                "one device, one position, transmit power varied",
                                "results": results,
                            },
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
        finally:
            await run_on_device(config, "NRF.setTxPower(4);")
            await set_fast_timeout(config, 30000)
            await bus.close()

    print()
    for row in results:
        good = [s["total_ms"] / 1000 for s in row["samples"] if not s.get("failed")]
        lost = sum(1 for s in row["samples"] if s.get("failed"))
        if good:
            level = row["rssi"]["median"] if row["rssi"] else None
            print(
                f"{row['tx_power']:+3} dBm (heard at {level} dBm): "
                f"median {statistics.median(good):5.2f} s, "
                f"mean {statistics.fmean(good):5.2f} s, lost {lost}"
            )
        else:
            print(f"{row['tx_power']:+3} dBm: every command lost")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=tuple(DEVICES), default="puck")
    parser.add_argument("--interval", type=int, default=1200)
    parser.add_argument("--powers", type=int, nargs="+", default=[4, -20])
    parser.add_argument("--reps", type=int, default=10)
    parser.add_argument("--idle", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--out")
    args = parser.parse_args()

    if not os.environ.get("HA_TOKEN"):
        raise SystemExit("HA_TOKEN is not set")
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

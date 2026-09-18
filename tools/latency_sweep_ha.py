"""The same sweep, driven by Home Assistant rather than by this host.

`tools/latency_sweep.py` measures the protocol from the bench host, which is the
only place the write itself can be timed precisely — and which adds a Windows
adapter's own delays to every sample. This one measures what a user actually
experiences: a service call in Home Assistant, over whichever adapter or proxy
Home Assistant is using, until the *device* shows it has acted.

The service call is not the answer: it returns as soon as the command is queued
(about 0.3 s), long before anything reaches the device. So each device needs a
witness that does not compete for its single BLE connection:

- **nice!nano** — its console over USB serial. `oled-text.js` prints
  `SHOWN[n]: <text>` when it draws, so the sweep writes a unique string and
  waits for that line. Nothing else touches the radio.
- **Puck.js** — its own light sensor, read back through Home Assistant.
  `light-loop.js` measures the LED it was told to switch, so the illuminance
  sensor crossing a threshold is the device saying "applied". That adds one
  advertising refresh to every sample, which the device sends immediately at its
  fast interval, so the addition is small but real.

    python -m tools.latency_sweep_ha --device nano --out docs/data/ha-nano-text.json
    python -m tools.latency_sweep_ha --device puck --out docs/data/ha-puck-switch.json

Needs `HA_URL` and `HA_TOKEN` in the environment, and for the Puck, the
`light-loop.js` sketch rather than `button-light.js`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import statistics
import sys
import time
import urllib.request

NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")

DEVICES = {
    "puck": {
        "address": "C8:80:32:AD:F7:B9",
        "label": "Puck.js switch (light), through Home Assistant",
        "entity": "switch.bureau_mobilesensf7b9_light",
        "witness": "sensor.bureau_mobilesensf7b9_illuminance",
    },
    "nano": {
        "address": "CD:F5:77:3A:B2:16",
        "label": "nice!nano text (OLED), through Home Assistant",
        "entity": "text.espruino_b216_text",
        "port": "COM15",
    },
}


def call(path: str, payload: dict | None = None):
    url = os.environ["HA_URL"].rstrip("/") + path
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        method="POST" if payload is not None else "GET",
        headers={
            "Authorization": "Bearer " + os.environ["HA_TOKEN"],
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def state_of(entity: str) -> str:
    return call(f"/api/states/{entity}")["state"]


# --- the two witnesses --------------------------------------------------------


class SerialWitness:
    """The nice!nano's console, over USB. Untouched by anything BLE does."""

    def __init__(self, port: str) -> None:
        import serial  # imported here so the Puck path needs no pyserial

        self.link = serial.Serial(port, 115200, timeout=0.05)
        self.link.write(b"\n")
        time.sleep(0.3)
        self.link.reset_input_buffer()

    def arm(self) -> None:
        self.link.reset_input_buffer()

    def send(self, line: str) -> None:
        """Run a statement on the device. The witness owns the port, so every
        console write goes through here -- opening COM15 twice is refused."""
        self.link.write(line.encode())
        time.sleep(1.0)
        self.link.reset_input_buffer()

    def wait(self, needle: str, deadline: float) -> float | None:
        """Seconds until the sketch printed `needle`, or None if it never did."""
        buffer = ""
        while time.perf_counter() < deadline:
            chunk = self.link.read(256)
            if chunk:
                buffer += NOISE.sub("", chunk.decode("utf-8", "replace"))
                if needle in buffer:
                    return time.perf_counter()
            else:
                time.sleep(0.01)
        return None

    def close(self) -> None:
        self.link.close()


class SensorWitness:
    """The Puck's light sensor, as Home Assistant reports it.

    Always waits for a *transition*, never for a state: a witness that accepts
    the value it already had would time a command at nothing whenever the lamp
    was already where it was being sent, and would drift out of step after the
    first failed write.
    """

    def __init__(self, entity: str, threshold: float = 300.0) -> None:
        self.entity = entity
        self.threshold = threshold

    def bright(self) -> bool:
        try:
            return float(state_of(self.entity)) > self.threshold
        except (ValueError, KeyError):
            return False

    def wait_for(self, want_bright: bool, deadline: float) -> float | None:
        while time.perf_counter() < deadline:
            if self.bright() == want_bright:
                return time.perf_counter()
            time.sleep(0.15)
        return None


# --- the sweep ----------------------------------------------------------------


async def set_interval(config: dict, witness, ms: int) -> None:
    """Over USB where there is a cable, over BLE otherwise.

    Not a detail: this host cannot open a GATT connection to the nice!nano at
    all any more, though Home Assistant can (see the sweep's own notes), so the
    serial route is the only one that works there.
    """
    if isinstance(witness, SerialWitness):
        witness.send(f"bw.setAdvertisingInterval({ms});\n")
        return
    from tools.set_adv_interval import run as set_run

    await set_run(config["address"], ms, False)


def one_command_nano(
    config, witness: SerialWitness, index: int, timeout: float
) -> dict:
    text = f"sweep {index:04d}"
    witness.arm()
    started = time.perf_counter()
    call(
        "/api/services/text/set_value",
        {"entity_id": config["entity"], "value": text},
    )
    landed = witness.wait(text, started + timeout)
    return sample(started, landed)


def one_command_puck(
    config, witness: SensorWitness, index: int, timeout: float
) -> dict:
    # Whatever the lamp is now, send it the other way, so that every sample is a
    # change the sensor can witness.
    on = not witness.bright()
    started = time.perf_counter()
    call(
        f"/api/services/switch/turn_{'on' if on else 'off'}",
        {"entity_id": config["entity"]},
    )
    landed = witness.wait_for(on, started + timeout)
    return sample(started, landed)


def sample(started: float, landed: float | None) -> dict:
    if landed is None:
        return {"total": 0.0, "failed": True}
    return {"total": landed - started}


async def run(args) -> int:
    config = DEVICES[args.device]
    if args.device == "nano":
        witness: object = SerialWitness(config["port"])
        one = one_command_nano
    else:
        witness = SensorWitness(config["witness"])
        one = one_command_puck

    index = 0
    results: list[dict] = []
    try:
        for interval in args.intervals:
            print(f"\n=== {interval} ms ===", flush=True)
            await set_interval(config, witness, interval)

            first: list[dict] = []
            for _ in range(args.first_reps):
                print(f"  idling {args.idle:.0f} s ...", flush=True)
                await asyncio.sleep(args.idle)
                index += 1
                got = one(config, witness, index, args.timeout)
                report("first", got)
                first.append(got)

            consecutive: list[dict] = []
            for _ in range(args.burst):
                index += 1
                got = one(config, witness, index, args.timeout)
                report("next", got)
                consecutive.append(got)
                await asyncio.sleep(args.gap)

            results.append(
                {"interval_ms": interval, "first": first, "consecutive": consecutive}
            )
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(
                    json.dumps(
                        {
                            "address": config["address"],
                            "label": config["label"],
                            "entity": config["entity"],
                            "via": "Home Assistant 2026.7.4 on a Raspberry Pi 3",
                            "witness": "USB console"
                            if args.device == "nano"
                            else "its own light sensor",
                            "idle_wait_s": args.idle,
                            "results": results,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
    finally:
        if isinstance(witness, SerialWitness):
            witness.close()

    for row in results:
        print(
            f"{row['interval_ms']:6} ms   first {mean_total(row['first']):6.2f} s"
            f"   consecutive {mean_total(row['consecutive']):5.2f} s"
        )
    return 0


def report(case: str, got: dict) -> None:
    if got.get("failed"):
        print(f"  {case:<9} FAILED (no sign of it on the device)", flush=True)
    else:
        print(f"  {case:<9} {got['total']:6.2f} s", flush=True)


def mean_total(samples: list[dict]) -> float:
    usable = [s["total"] for s in samples if not s.get("failed")]
    return statistics.fmean(usable) if usable else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=tuple(DEVICES), required=True)
    parser.add_argument(
        "--intervals",
        type=int,
        nargs="+",
        default=[100, 200, 500, 1000, 2000, 5000, 10000],
    )
    parser.add_argument("--first-reps", type=int, default=3)
    parser.add_argument("--burst", type=int, default=5)
    parser.add_argument("--idle", type=float, default=35.0)
    parser.add_argument("--gap", type=float, default=1.0)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--out")
    args = parser.parse_args()

    if not os.environ.get("HA_TOKEN"):
        raise SystemExit("HA_TOKEN is not set")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())

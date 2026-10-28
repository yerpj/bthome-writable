"""Command several devices at the same instant, and see where the wait landed.

D-133's wall and D-134's priority were both argued from tests and from reading
`bleak_retry_connector`, because three devices and one three-slot proxy cannot
fill a host (D-133, "what is still not done"). With four devices in one island
and the Pi's own adapter switched off, the island's proxy offers three slots for
four commands, so the fourth meets the host rather than the cap.

    .venv-ha/Scripts/python.exe -m tools.slot_storm --devices lamp lamp2 lamp3 jolt \\
        --cap 6 --without-pi --label "cap 6, four devices, three slots"

What it does, in order, and undoes on every way out:

* reads every `bthome_writable` entry and raises each one's `max_connections` to
  `--cap`, because **the lowest request wins** (`slots.register_request`): one
  entry left at the default of 2 caps the whole host at 2 and the proxy's three
  slots are never reached;
* disables the Raspberry Pi's own Bluetooth entry with `--without-pi`, and any
  other scanner named with `--without`, because **the pool is every scanner Home
  Assistant has**: with two proxies up, four devices on a three-slot proxy never
  meet a wall, they are routed through the other proxy instead, however badly it
  hears them. Measured here: arm A sent the fourth device through the proxy in
  the next room and paid 9.4 s of connecting for it;
* subscribes to `bthome_writable_write`, which is where `queued_ms` and
  `connect_ms` come from (D-133 moved that boundary inside the gate), and to
  `bluetooth/subscribe_connection_allocations`, which is Home Assistant's own
  view of who holds a slot;
* issues one command per device *at the same instant*, from one `gather`, and
  keeps each call's own duration and error;
* restores the switches, the Pi and every cap it changed.

Nothing is written to the devices beyond the commands themselves, and every
switch ends where it started. The bench lock is the caller's to take.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import statistics
import time
from typing import Any

import aiohttp

from tools.devices import DEVICES

PI_ENTRY_TITLE = "Raspberry Pi"
WRITE_EVENT = "bthome_writable_write"
SETTLE_S = 6.0
"""How long to keep listening after the last command, for late events."""


class Bus:
    """One WebSocket conversation, with ids that only ever go up."""

    def __init__(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        self.ws = ws
        self._id = 0
        self._results: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.allocations: list[tuple[float, Any]] = []
        self._subscriptions: dict[int, str] = {}
        self._pump: asyncio.Task | None = None

    def next_id(self) -> int:
        self._id += 1
        return self._id

    async def start(self) -> None:
        self._pump = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop reading, so closing the socket is not an unretrieved exception."""
        if self._pump is not None:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._pump
            self._pump = None

    async def _run(self) -> None:
        while True:
            msg = await self.ws.receive_json()
            kind = msg.get("type")
            if kind == "result":
                self._results[msg["id"]] = msg
            elif kind == "event":
                what = self._subscriptions.get(msg["id"])
                if what == "write":
                    self.events.append(msg["event"]["data"])
                elif what == "allocations":
                    self.allocations.append((time.monotonic(), msg["event"]))

    async def ask(
        self, payload: dict[str, Any], timeout: float = 180.0
    ) -> dict[str, Any]:
        mine = self.next_id()
        await self.ws.send_json({"id": mine, **payload})
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if mine in self._results:
                return self._results.pop(mine)
            await asyncio.sleep(0.02)
        raise TimeoutError(f"no answer to {payload.get('type')}")

    async def subscribe(self, payload: dict[str, Any], tag: str) -> None:
        mine = self.next_id()
        self._subscriptions[mine] = tag
        await self.ws.send_json({"id": mine, **payload})


async def states(bus: Bus) -> dict[str, str]:
    got = await bus.ask({"type": "get_states"})
    return {row["entity_id"]: row["state"] for row in got["result"]}


async def entries(
    session: aiohttp.ClientSession, url: str, token: str
) -> list[dict[str, Any]]:
    async with session.get(
        f"{url}/api/config/config_entries/entry",
        headers={"Authorization": f"Bearer {token}"},
    ) as r:
        return await r.json()


async def set_cap(
    session: aiohttp.ClientSession, url: str, token: str, entry_id: str, cap: int
) -> None:
    """Walk one entry's options flow, which is the only way in (D-132)."""
    head = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with session.post(
        f"{url}/api/config/config_entries/options/flow",
        headers=head,
        json={"handler": entry_id},
    ) as r:
        flow = await r.json()
    async with session.post(
        f"{url}/api/config/config_entries/options/flow/{flow['flow_id']}",
        headers=head,
        json={"max_connections": cap},
    ) as r:
        await r.json()


async def set_pi(bus: Bus, entry_id: str, enabled: bool) -> None:
    await bus.ask(
        {
            "type": "config_entries/disable",
            "entry_id": entry_id,
            "disabled_by": None if enabled else "user",
        }
    )


async def command(bus: Bus, entity: str, service: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        got = await bus.ask(
            {
                "type": "call_service",
                "domain": entity.split(".")[0],
                "service": service,
                "service_data": {"entity_id": entity},
            }
        )
    except TimeoutError as exc:
        return {"entity": entity, "ok": False, "seconds": None, "error": str(exc)}
    took = round(time.monotonic() - started, 2)
    if got.get("success"):
        return {"entity": entity, "ok": True, "seconds": took, "error": None}
    message = str((got.get("error") or {}).get("message"))
    return {"entity": entity, "ok": False, "seconds": took, "error": message}


def report(run: dict[str, Any]) -> None:
    print(f"\n=== {run['label']}")
    print(
        f"cap {run['cap']}, Pi {'off' if run['without_pi'] else 'on'}, "
        f"{len(run['commands'])} commands at once"
    )
    for row in run["commands"]:
        mark = "ok   " if row["ok"] else "FAIL "
        print(f"  {mark} {row['entity']:40} {row['seconds']} s")
        if row["error"]:
            print(f"        {row['error'][:200]}")
    if run["events"]:
        print("  where the time went, per acknowledged write:")
        for ev in run["events"]:
            print(
                f"    {ev['address']} entry {ev['entry']}: "
                f"queued {ev['queued_ms']} ms, "
                f"connect {ev['connect_ms']} ms, counter {ev['counter_ms']} ms, "
                f"write {ev['write_ms']} ms, total {ev['total_ms']} ms"
            )
        queued = [ev["queued_ms"] for ev in run["events"]]
        print(
            f"    queued_ms: min {min(queued)}, "
            f"median {statistics.median(queued)}, max {max(queued)}"
        )
    else:
        print("  no write event: nothing was acknowledged")
    busiest = max(
        (len(a["allocated"]) for _, rows in run["allocations"] for a in rows), default=0
    )
    print(f"  most slots held at once, as Home Assistant saw them: {busiest}")


async def run_storm(args: argparse.Namespace) -> dict[str, Any]:
    url = os.environ.get("HA_URL", "http://haosjry.local:8123")
    token = os.environ["HA_TOKEN"]
    chosen = [DEVICES[name] for name in args.devices]
    entities = [device["entity"] for device in chosen]

    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(connector=connector) as session:
        rows = await entries(session, url, token)
        writable = [e for e in rows if e["domain"] == "bthome_writable"]
        pi = next(
            e
            for e in rows
            if e["domain"] == "bluetooth" and PI_ENTRY_TITLE in e["title"]
        )
        silenced = [
            e
            for e in rows
            if e["domain"] in ("esphome", "bluetooth")
            and e["disabled_by"] is None
            and any(fragment in e["title"] for fragment in args.without)
        ]

        ws_url = (
            url.replace("http://", "ws://").replace("https://", "wss://")
            + "/api/websocket"
        )
        async with session.ws_connect(ws_url, timeout=30) as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": token})
            if (await ws.receive_json()).get("type") != "auth_ok":
                raise SystemExit("Home Assistant refused the token")
            bus = Bus(ws)
            await bus.start()

            before = await states(bus)
            caps_set: list[str] = []
            pi_was_enabled = pi["disabled_by"] is None
            try:
                for entry in writable:
                    await set_cap(session, url, token, entry["entry_id"], args.cap)
                    caps_set.append(entry["entry_id"])
                if args.without_pi and pi_was_enabled:
                    await set_pi(bus, pi["entry_id"], False)
                for entry in silenced:
                    await set_pi(bus, entry["entry_id"], False)
                    print(f"silenced: {entry['title']}")
                await asyncio.sleep(args.warmup)

                await bus.subscribe(
                    {"type": "subscribe_events", "event_type": WRITE_EVENT}, "write"
                )
                await bus.subscribe(
                    {"type": "bluetooth/subscribe_connection_allocations"},
                    "allocations",
                )
                await asyncio.sleep(1.0)

                wanted = [
                    "turn_off" if before.get(entity) == "on" else "turn_on"
                    for entity in entities
                ]
                started = time.monotonic()
                results = await asyncio.gather(
                    *(
                        command(bus, entity, service)
                        for entity, service in zip(entities, wanted, strict=True)
                    )
                )
                spread = round(time.monotonic() - started, 2)
                await asyncio.sleep(SETTLE_S)
                run = {
                    "label": args.label or f"cap {args.cap}, {len(entities)} devices",
                    "cap": args.cap,
                    "without_pi": bool(args.without_pi),
                    "silenced": [e["title"] for e in silenced],
                    "devices": args.devices,
                    "wall_seconds": spread,
                    "commands": list(results),
                    "events": list(bus.events),
                    "allocations": list(bus.allocations),
                }
            finally:
                after = await states(bus)
                for entity in entities:
                    was = before.get(entity)
                    if was in ("on", "off") and after.get(entity) != was:
                        back = "turn_on" if was == "on" else "turn_off"
                        with contextlib.suppress(Exception):
                            await command(bus, entity, back)
                if args.without_pi and pi_was_enabled:
                    with contextlib.suppress(Exception):
                        await set_pi(bus, pi["entry_id"], True)
                for entry in silenced:
                    with contextlib.suppress(Exception):
                        await set_pi(bus, entry["entry_id"], True)
                await bus.stop()
                for entry_id in caps_set:
                    original = next(e for e in writable if e["entry_id"] == entry_id)
                    with contextlib.suppress(Exception):
                        await set_cap(
                            session,
                            url,
                            token,
                            entry_id,
                            original.get("options", {}).get("max_connections", 2),
                        )
    return run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--devices", nargs="+", required=True, choices=tuple(DEVICES), metavar="NAME"
    )
    parser.add_argument(
        "--cap", type=int, default=6, help="the host cap to set everywhere"
    )
    parser.add_argument(
        "--without-pi",
        action="store_true",
        help="disable the Pi's own adapter for the run",
    )
    parser.add_argument(
        "--warmup", type=float, default=10.0, help="seconds to settle first"
    )
    parser.add_argument(
        "--without",
        nargs="*",
        default=[],
        metavar="TITLE",
        help="also disable every scanner entry whose title contains this",
    )
    parser.add_argument("--label", default="", help="what this run is, for the report")
    parser.add_argument("--out", default="", help="write the run to this JSON file")
    args = parser.parse_args()

    if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    run = asyncio.run(run_storm(args))
    report(run)
    if args.out:
        serialisable = {k: v for k, v in run.items() if k != "allocations"}
        serialisable["allocations"] = [rows for _, rows in run["allocations"]]
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(serialisable, handle, indent=1)
        print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

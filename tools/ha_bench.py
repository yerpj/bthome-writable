"""Put Home Assistant into a known state for a measurement, and put it back.

A latency figure is only comparable with another one taken the same way, and two
things on this bench move it several-fold if left alone:

* **the ESP32 Bluetooth proxy**, which reuses a recent link and so produces first
  commands faster than catching an advertisement allows (D-054);
* **the automation that writes to the nice!nano every 30 s**, which keeps that
  device permanently inside its fast-advertising window.

Both were disabled by hand before every campaign so far, which is one more thing
to remember and one more way for a run to be quietly incomparable. This module
does it, records what it changed, and restores exactly that on the way out --
including leaving alone anything that was already in the wanted state.

    async with bench_prepared(session, PROXY_ENTRY, OLED_AUTOMATION) as changed:
        ...                     # measure
                                # restored here, whatever happened

Needs `HA_URL` and `HA_TOKEN` in the environment. Reads and writes only the
entries and automations it is given.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from typing import Any

import aiohttp

PROXY_ENTRY = "01M2QKAFXHKY07577VZ1PDZ8F2"
"""The ESPHome Bluetooth proxy's config entry on this bench.

Disabling this one is what takes the proxy out of the picture. The proxy also
appears as a `bluetooth` entry of its own, `esp32-bluetooth-proxy-1f1020`, which
stays loaded either way: it is the adapter registration, not the link."""

PI_ADAPTER_ENTRY = "01KBYN6ECQYR1FYPSPHP5HVHQD"
"""The Raspberry Pi's own bcm43438, which is the bench's default radio.

Disabling it is how a measurement is forced through the proxy instead, which is
a different GATT path: the central is then an ESP32 on the far side of Wi-Fi,
with its own connection slots and its own service cache."""

OLED_AUTOMATION = "automation.puck_illuminance_oled"
"""The automation that writes the Puck's illuminance to the nice!nano."""


def _base() -> str:
    return os.environ["HA_URL"].rstrip("/")


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + os.environ["HA_TOKEN"]}


async def _ws(session: aiohttp.ClientSession, payload: dict) -> Any:
    """One WebSocket command, because config entries have no REST equivalent."""
    url = _base().replace("http://", "ws://").replace("https://", "wss://")
    async with session.ws_connect(url + "/api/websocket") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": os.environ["HA_TOKEN"]})
        if (await ws.receive_json())["type"] != "auth_ok":
            raise RuntimeError("Home Assistant refused the token")
        await ws.send_json({"id": 1, **payload})
        while True:
            message = await ws.receive_json()
            if message.get("id") == 1 and message.get("type") == "result":
                if not message.get("success", True):
                    raise RuntimeError(f"{payload['type']}: {message.get('error')}")
                return message.get("result")


async def entry_enabled(session: aiohttp.ClientSession, entry_id: str) -> bool:
    for entry in await _ws(session, {"type": "config_entries/get"}):
        if entry["entry_id"] == entry_id:
            return entry["disabled_by"] is None
    raise LookupError(f"no config entry {entry_id}")


async def set_entry_enabled(
    session: aiohttp.ClientSession, entry_id: str, enabled: bool
) -> None:
    await _ws(
        session,
        {
            "type": "config_entries/disable",
            "entry_id": entry_id,
            "disabled_by": None if enabled else "user",
        },
    )


async def automation_on(session: aiohttp.ClientSession, entity_id: str) -> bool:
    async with session.get(
        f"{_base()}/api/states/{entity_id}", headers=_headers()
    ) as response:
        if response.status == 404:
            raise LookupError(f"no automation {entity_id}")
        return (await response.json())["state"] == "on"


async def set_automation(
    session: aiohttp.ClientSession, entity_id: str, on: bool
) -> None:
    service = "turn_on" if on else "turn_off"
    async with session.post(
        f"{_base()}/api/services/automation/{service}",
        headers=_headers(),
        json={"entity_id": entity_id},
    ) as response:
        response.raise_for_status()


@asynccontextmanager
async def bench_prepared(
    session: aiohttp.ClientSession,
    proxy_entry: str = PROXY_ENTRY,
    automation: str = OLED_AUTOMATION,
):
    """Disable the proxy and the automation for the duration, then restore.

    Yields the list of what it actually changed, so a run can record the bench
    it was taken on rather than the bench it assumed.

    **Restoring what it changed is not the same as restoring a known state**, and
    the difference bit once: a run killed part-way left the proxy disabled, the
    next run found it already disabled, changed nothing, and faithfully put it
    back as it found it. Correct by this contract, and still a bench left dirty.
    A caller that finds nothing to change is therefore told so in as many words,
    because the usual reason is a previous run that died.
    """
    changed: list[str] = []
    proxy_was = await entry_enabled(session, proxy_entry)
    automation_was = await automation_on(session, automation)
    try:
        if proxy_was:
            await set_entry_enabled(session, proxy_entry, False)
            changed.append("disabled the ESP32 proxy")
        if automation_was:
            await set_automation(session, automation, False)
            changed.append("turned off the OLED automation")
        if not changed:
            changed.append(
                "nothing to change -- the bench was already prepared, which "
                "usually means an earlier run did not finish; it will be left "
                "exactly as found"
            )
        yield changed
    finally:
        # Restoring only what was changed: a bench someone else had already put
        # into this state stays in it.
        if proxy_was:
            await set_entry_enabled(session, proxy_entry, True)
        if automation_was:
            await set_automation(session, automation, True)


@asynccontextmanager
async def radio_through_proxy(
    session: aiohttp.ClientSession,
    proxy_entry: str = PROXY_ENTRY,
    adapter_entry: str = PI_ADAPTER_ENTRY,
    automation: str = OLED_AUTOMATION,
    settle: float = 30.0,
):
    """The opposite of `bench_prepared`: the proxy alone, no local adapter.

    Everything Home Assistant hears and every connection it opens then goes
    through the ESP32, which is a different central with its own connection
    slots and its own view of a device's GATT table. A measurement taken this
    way is not comparable with one taken on the Pi's own radio, and that is the
    point: a receiver-side fault that only appears behind a proxy cannot be
    found with the proxy switched off.

    The proxy is enabled first and given time to come up, because disabling the
    only working adapter before the other one is up leaves Home Assistant with
    no radio at all and every device unavailable, which looks exactly like the
    device having died.

    Restores what it changed, with the same caveat as `bench_prepared`: a bench
    already in this state is left in it.
    """
    changed: list[str] = []
    proxy_was = await entry_enabled(session, proxy_entry)
    adapter_was = await entry_enabled(session, adapter_entry)
    automation_was = await automation_on(session, automation)
    try:
        if not proxy_was:
            await set_entry_enabled(session, proxy_entry, True)
            changed.append("enabled the ESP32 proxy")
            await asyncio.sleep(settle)
        if adapter_was:
            await set_entry_enabled(session, adapter_entry, False)
            changed.append("disabled the Pi's own adapter")
            await asyncio.sleep(settle)
        if automation_was:
            await set_automation(session, automation, False)
            changed.append("turned off the OLED automation")
        if not changed:
            changed.append(
                "nothing to change -- the bench was already on the proxy alone"
            )
        yield changed
    finally:
        if adapter_was:
            await set_entry_enabled(session, adapter_entry, True)
            await asyncio.sleep(settle)
        if not proxy_was:
            await set_entry_enabled(session, proxy_entry, False)
        if automation_was:
            await set_automation(session, automation, True)

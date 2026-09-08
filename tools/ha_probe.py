"""Ask a running Home Assistant what it knows about BTHome.

Used through the hardware-test loop, where the same questions come up after
every change: what version is this, did the integration load, what entities
exist, and what is in the log.

    HA_URL=http://haosjry.local:8123 HA_TOKEN=... python -m tools.ha_probe
    ... python -m tools.ha_probe bthome        # filter entities by substring

The token is read from the environment, never from a file in the repo, and is
sent only to HA_URL.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_URL = "http://haosjry.local:8123"
TIMEOUT = 15

INTERESTING_COMPONENTS = (
    "bluetooth",
    "bluetooth_adapters",
    "bthome",
    "bthome_writable",
    "esphome",
    "hassio",
)


def call(path: str, url: str, token: str, data: dict[str, Any] | None = None) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    request = Request(
        f"{url.rstrip('/')}{path}",
        data=None if data is None else json.dumps(data).encode("utf-8"),
        headers=headers,
        method="GET" if data is None else "POST",
    )
    with urlopen(request, timeout=TIMEOUT) as response:
        body = response.read().decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body


def heading(text: str) -> None:
    print(f"\n=== {text} ===")


def main() -> int:
    url = os.environ.get("HA_URL", DEFAULT_URL)
    token = os.environ.get("HA_TOKEN")
    needle = sys.argv[1].lower() if len(sys.argv) > 1 else "bthome"

    if not token:
        print("HA_TOKEN is not set. Create a long-lived access token in Home")
        print("Assistant (profile -> Security) and export it as HA_TOKEN.")
        return 2

    try:
        config = call("/api/config", url, token)
    except HTTPError as error:
        print(f"{url}: HTTP {error.code} - is the token valid?")
        return 1
    except URLError as error:
        print(f"{url}: not reachable ({error.reason})")
        return 1

    heading("Home Assistant")
    print(f"version     {config['version']}")
    print(f"location    {config.get('location_name')}")
    print(f"config_dir  {config.get('config_dir')}")

    components = set(config.get("components", []))
    heading("Components")
    for component in INTERESTING_COMPONENTS:
        print(f"{component:<20} {'loaded' if component in components else '-'}")

    heading(f"Entities matching {needle!r}")
    states = call("/api/states", url, token)
    matches = [
        state
        for state in states
        if isinstance(state, dict) and needle in json.dumps(state).lower()
    ]
    for state in matches[:40]:
        name = state.get("attributes", {}).get("friendly_name", "")
        print(f"{state['entity_id']:<48} {state['state']:<14} {name}")
    if not matches:
        print("none")
    elif len(matches) > 40:
        print(f"... and {len(matches) - 40} more")

    heading(f"Log lines mentioning {needle!r} or bluetooth")
    try:
        log = str(call("/api/error_log", url, token))
    except HTTPError:
        log = ""
    lines = [
        line
        for line in log.splitlines()
        if needle in line.lower() or "bluetooth" in line.lower()
    ]
    for line in lines[-30:]:
        print(line)
    if not lines:
        print("nothing")

    return 0


if __name__ == "__main__":
    sys.exit(main())

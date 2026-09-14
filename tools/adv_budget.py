"""How much BTHome service data will this radio actually accept?

    python -m tools.adv_budget --address C8:80:32:AD:F7:B9

PROTOCOL.md §2.3 works the budget out as `31 - 3 (Flags) - 4 (service data
header) = 24` bytes. A Puck.js disagrees, and by enough to matter: an encrypted
device spends 8 of those on the counter and MIC, so the difference between 24
and the truth decides whether encryption fits at all (decisions.md D-030).

This asks the radio directly, for each combination of the options the module
sets, and reports the largest payload each one takes.

It is safe to run only because the rail can be cut: a rejected payload can leave
the radio stopped, and a device that advertises nothing cannot be connected to
(D-029). The BLE console this runs over is the lifeline -- an open connection
survives advertising stopping -- and `tools.ooty cycle` is the recovery if it
does not. Nothing is written to flash.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import re
import sys

from tools.espruino_deploy import UART_RX, UART_TX, connect, discover

NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")

# The options the module sets, and the ones worth suspecting. Espruino adds the
# device's name to the payload when it fits, which is the obvious candidate for
# the missing bytes -- `Puck.js f7b9` alone is 14 of them with its AD header.
CASES = {
    "module defaults": "connectable:true,discoverable:true,whenConnected:true",
    "without whenConnected": "connectable:true,discoverable:true",
    "without discoverable": "connectable:true,whenConnected:true",
    "showName false": (
        "connectable:true,discoverable:true,whenConnected:true,showName:false"
    ),
    "showName false, no whenConnected": (
        "connectable:true,discoverable:true,showName:false"
    ),
}

# Restored between probes so the device keeps advertising something valid even
# if the next attempt is refused: device-info, packet id, one count.
SAFE = "[0x40,0x00,0x01]"


def script() -> list[str]:
    lines = [
        "function probe(n,o){try{NRF.setAdvertising({0xFCD2:new Uint8Array(n)},o);"
        "return true;}catch(e){return false;}}",
        f"function safe(){{NRF.setAdvertising({{0xFCD2:{SAFE}}},"
        "{interval:1000,connectable:true,discoverable:true});}",
        "function most(o){var best=0;for(var n=1;n<=24;n++){if(probe(n,o))best=n;}"
        "safe();return best;}",
    ]
    for label, options in CASES.items():
        key = label.replace(" ", "_").replace(",", "")
        lines.append(f'print("MAX|{key}|", most({{interval:1000,{options}}}));')
    return lines


async def run(address: str) -> int:
    device = await discover(address, 180.0)
    if device is None:
        print(f"{address}: not seen", file=sys.stderr)
        return 1

    client = await connect(device)
    out = bytearray()
    try:
        await client.start_notify(UART_TX, lambda _s, data: out.extend(data))

        async def send(text: str, settle: float = 1.0) -> None:
            data = text.encode()
            for offset in range(0, len(data), 50):
                await client.write_gatt_char(
                    UART_RX, data[offset : offset + 50], response=False
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(settle)

        # Stop the sketch: its own timer would reset the advertising underneath
        # every probe and the answers would be about its payload, not ours.
        await send("\x03")
        await send("clearInterval();clearWatch();\n")
        out.clear()
        for line in script():
            await send(line + "\n", settle=4.0 if line.startswith("print") else 0.8)
        await asyncio.sleep(2)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()

    results: dict[str, int] = {}
    for line in NOISE.sub("", out.decode("utf-8", "replace")).splitlines():
        text = line.strip()
        if text.startswith("MAX|") and "print(" not in text:
            parts = text.split("|")
            if len(parts) >= 3:
                with contextlib.suppress(ValueError):
                    results[parts[1].replace("_", " ")] = int(parts[2].strip())

    if not results:
        print("the device answered nothing", file=sys.stderr)
        return 1

    print(f"{'advertising options':38} max service data")
    for label in CASES:
        got = results.get(label)
        print(f"{label:38} {got if got is not None else '?'}")
    print("\n§2.3 assumes 24. An encrypted device needs 8 of whatever this is.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    return asyncio.run(run(args.address))


if __name__ == "__main__":
    sys.exit(main())

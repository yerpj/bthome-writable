"""Cycle the bench host's own Bluetooth radio, from user space.

The Windows host gets into a state where it still *hears* devices perfectly --
a scan returns dozens of advertisements a second -- but every attempt to connect
fails. It is not the device: the same device answers Home Assistant throughout,
and a scan from here sees it. It is the host's stack, and the only remedy short
of a reboot is to turn its radio off and on again.

    python -m tools.host_radio state
    python -m tools.host_radio cycle

This is the host equivalent of `tools.ooty`, which does the same for the board
under test. No administrator rights are needed: Windows exposes the radio switch
to applications through `Windows.Devices.Radios`, the same one the Settings
toggle uses.

Cycling the radio drops every Bluetooth connection this machine holds, including
an Espruino console someone else is using -- it is a bench write, so take the
lock first.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

SETTLE_S = 3.0
"""Seconds to let the stack come back before anything tries to use it.

Measured rather than guessed: a scan started immediately after the radio reports
itself on returns nothing for the first couple of seconds."""


async def _radios() -> list:
    from winrt.windows.devices.radios import Radio, RadioKind

    return [r for r in await Radio.get_radios_async() if r.kind == RadioKind.BLUETOOTH]


async def state() -> int:
    for radio in await _radios():
        print(f"{radio.name}: {radio.state.name}")
    return 0


async def cycle(off_seconds: float) -> int:
    from winrt.windows.devices.radios import RadioAccessStatus, RadioState

    access = await _request_access()
    if access != RadioAccessStatus.ALLOWED:
        raise SystemExit(f"Windows refused access to the radio: {access.name}")

    radios = await _radios()
    if not radios:
        raise SystemExit("no Bluetooth radio on this host")

    for radio in radios:
        print(f"{radio.name}: {radio.state.name} -> OFF", flush=True)
        await radio.set_state_async(RadioState.OFF)
    await asyncio.sleep(off_seconds)
    for radio in radios:
        await radio.set_state_async(RadioState.ON)
        print(f"{radio.name}: ON", flush=True)
    await asyncio.sleep(SETTLE_S)
    print(f"settled after {SETTLE_S:.0f} s")
    return 0


async def _request_access():
    from winrt.windows.devices.radios import Radio

    return await Radio.request_access_async()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("state", help="what the host's radios are doing")
    cycled = sub.add_parser("cycle", help="turn the Bluetooth radio off and on")
    cycled.add_argument("--off-seconds", type=float, default=3.0)
    args = parser.parse_args()

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    if args.action == "state":
        return asyncio.run(state())
    return asyncio.run(cycle(args.off_seconds))


if __name__ == "__main__":
    sys.exit(main())

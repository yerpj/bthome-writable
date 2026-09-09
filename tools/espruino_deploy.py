"""Install a sketch the way Espruino means it to be installed.

`espruino_upload.py` pushes everything into RAM, which is right for iterating
and wrong for leaving a device running: it costs RAM that a Puck.js does not
have, and it does not survive a power cut without `save()`, whose memory image
is a fragile thing to depend on.

The idiomatic layout, and what this writes:

    Storage "BTHome"           the upstream module, by its bare name
    Storage "BTHomeWritable"   this project's module, likewise
    Storage ".bootcde"         the application, run at boot

`require("X")` resolves from Storage under exactly `X`, no extension — see
`jswrap_modules.c`, "Has it been manually saved to Flash Storage?". So the
application keeps its ordinary `require()` calls and the modules live in flash
rather than in RAM.

    python -m tools.espruino_deploy --address C8:80:32:AD:F7:B9 \
        --app espruino/examples/light-loop.js

The failure this avoids is worth naming: an application in `.bootcde` whose
modules are *not* in Storage boots, throws on the first `require`, and leaves a
device that answers its console and advertises nothing — indistinguishable from
a flat battery (decisions.md D-022).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import re
import sys

from bleak import BleakClient, BleakScanner

from tools.build_espruino_bundle import strip_comments
from tools.espruino_upload import UART_RX, UART_TX, fetch_module

ROOT = Path(__file__).resolve().parent.parent

# Espruino Storage filenames are short; a module name must fit.
MAX_STORAGE_NAME = 28

# Each Storage.write() is one console statement, and the console truncates a
# statement well before a module fits in one.
CHUNK = 384

NOISE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")

# Modules this project provides itself, rather than fetching from espruino.com.
LOCAL_MODULES = {"BTHomeWritable": ROOT / "espruino" / "BTHomeWritable.js"}


def required_modules(source: str) -> list[str]:
    return sorted(set(re.findall(r"""require\(\s*["']([\w.-]+)["']\s*\)""", source)))


def collect(app_code: str) -> dict[str, str]:
    """Every module the application needs, transitively, by bare name."""
    modules: dict[str, str] = {}
    pending = required_modules(app_code)

    while pending:
        name = pending.pop()
        if name in modules:
            continue
        if len(name) > MAX_STORAGE_NAME:
            raise SystemExit(f"module name {name!r} is too long for Storage")

        if name in LOCAL_MODULES:
            source = LOCAL_MODULES[name].read_text(encoding="utf-8")
        else:
            source = fetch_module(name)

        modules[name] = prepare(source)
        pending.extend(required_modules(modules[name]))

    return modules


def prepare(source: str) -> str:
    """The form of a source file that gets stored on the device.

    Comments go: they are a third of this project's module, Espruino keeps the
    text of every function it parses, and the board has 64 kB. Stripping them
    also happens to leave pure ASCII, which the next paragraph needs.

    An Espruino string is a byte array, not a sequence of code points, and this
    uploader addresses Storage by byte offset. Rather than reason about what a
    `\\u2014` in a console line becomes on the far side, refuse the file: every
    non-ASCII character in this project lives in a comment, so anything that
    survives the strip is something the author should look at.
    """
    stripped = strip_comments(source)
    if not stripped.isascii():
        offending = next(c for c in stripped if not c.isascii())
        raise SystemExit(
            f"non-ASCII character {offending!r} outside a comment; "
            "Espruino strings are bytes, so this cannot be uploaded verbatim"
        )
    return stripped


def write_statements(name: str, content: str) -> list[str]:
    """The console statements that put `content` into Storage as `name`.

    `content` is ASCII (see `prepare`), so slicing it by characters and slicing
    it by bytes are the same thing, and a chunk boundary cannot fall inside a
    character.
    """
    total = len(content)
    statements = [f'require("Storage").erase({json.dumps(name)});']
    for offset in range(0, total, CHUNK):
        piece = json.dumps(content[offset : offset + CHUNK])
        # The first write declares the final size, which allocates the flash
        # region; the rest fill it in at their offset. Espruino requires them in
        # this order.
        size = ",0," + str(total) if offset == 0 else "," + str(offset)
        statements.append(
            f'require("Storage").write({json.dumps(name)},{piece}{size});'
        )
    return statements


async def discover(address: str, timeout: float):
    """Wait for the device to advertise, rather than sampling for a while.

    `find_device_by_address` scans for its whole timeout and then answers, which
    is the wrong shape here: a device at a 5 s advertising interval reaches this
    host about twice a minute, so a fixed window is a coin toss that costs its
    full length when it loses. This returns the moment the address appears.
    """
    wanted = address.upper()
    loop = asyncio.get_running_loop()
    found: asyncio.Future = loop.create_future()

    def seen(device, _advertisement) -> None:
        if device.address.upper() == wanted and not found.done():
            found.set_result(device)

    async with BleakScanner(seen):
        try:
            return await asyncio.wait_for(asyncio.shield(found), timeout)
        except asyncio.TimeoutError:
            return None


async def connect(device, attempts: int = 6) -> BleakClient:
    """Connect, retrying, because one attempt is not a fair test.

    A central can only *begin* a connection when it catches a connectable
    advertising event. At a 5 s advertising interval those are rare, and a host
    that misses the window reports something final-sounding ("Unreachable")
    for what is really a race. Retrying is the honest reading of that error.

    Windows' service cache is left alone here, which is the opposite of what the
    integration does. The integration must not cache: the BTHome characteristic
    it writes to belongs to a layout that changes, and a stale view of it made
    writes vanish silently (decisions.md D-012). This tool only ever talks to
    the Nordic UART service, which is fixed for the life of the firmware, so
    there is nothing for a cache to get wrong. Asking WinRT to rediscover
    anyway is not free: on this host it hangs so hard that `asyncio.wait_for`
    cannot cancel it.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        client = BleakClient(device, timeout=30.0)
        try:
            # bleak's own `timeout` covers reaching the device but not the
            # service discovery that follows, which on WinRT can block with no
            # ceiling at all. This is the ceiling.
            print(f"  connecting, attempt {attempt}/{attempts} ...")
            await asyncio.wait_for(client.connect(), timeout=45)
            return client
        except Exception as error:  # bleak raises several unrelated types here
            last = error
            reason = error if str(error) else type(error).__name__
            print(f"  connection attempt {attempt}/{attempts} failed: {reason}")
            try:
                await client.disconnect()
            except Exception:
                pass  # nothing to clean up if it never opened
            await asyncio.sleep(3)
    raise SystemExit(f"could not connect to the device: {last}")


async def run(address: str, app: Path, reboot: bool, scan_timeout: float) -> int:
    # Prepared before the scan, so that a `require()` written inside a comment
    # — this project's module has one in its usage example — is not mistaken for
    # a dependency and chased to a 404.
    app_code = prepare(app.read_text(encoding="utf-8"))
    modules = collect(app_code)

    print(f"application  {app}  ({len(app_code)} bytes)")
    for name, source in modules.items():
        print(f"module       {name}  ({len(source)} bytes)")

    device = await discover(address, scan_timeout)
    if device is None:
        print(
            f"{address}: not seen in {scan_timeout:.0f}s",
            file=sys.stderr,
        )
        return 1

    console = bytearray()
    # Deliberately not `async with`: the client arrives already connected, and
    # `__aenter__` would call connect() a second time — which on WinRT hangs
    # rather than returning, and hangs uncancellably.
    client = await connect(device)
    try:
        print("connected; subscribing to the console")
        await asyncio.wait_for(
            client.start_notify(UART_TX, lambda _s, data: console.extend(data)),
            timeout=20,
        )

        async def send(text: str, settle: float = 0.35) -> None:
            data = text.encode("utf-8")
            for offset in range(0, len(data), 50):
                # Nordic UART RX is write-without-response; asking for an
                # acknowledgement it never sends is a way to wait forever.
                await asyncio.wait_for(
                    client.write_gatt_char(
                        UART_RX, data[offset : offset + 50], response=False
                    ),
                    timeout=20,
                )
                await asyncio.sleep(0.02)
            await asyncio.sleep(settle)

        # Stop whatever is running before rewriting the flash under it.
        print("interrupting the running program")
        await send("\x03")
        await send("clearInterval();clearWatch();\n")

        # A `save()` image is restored at boot *instead of* running `.bootcde`,
        # so leaving one behind would make this whole upload invisible: the
        # device would come back running the old code and nothing would say so.
        await send('require("Storage").erase(".varimg");\n')
        console.clear()

        for name, source in modules.items():
            print(f"writing {name} ...")
            for statement in write_statements(name, source):
                await send(statement + "\n", settle=0.25)

        print("writing .bootcde ...")
        for statement in write_statements(".bootcde", app_code):
            await send(statement + "\n", settle=0.25)

        await send('print("FILES=", JSON.stringify(require("Storage").list()));\n', 1.2)
        printed = NOISE.sub("", console.decode("utf-8", errors="replace"))
        for line in printed.splitlines():
            if line.startswith("FILES="):
                print(f"storage now holds {line[6:].strip()}")

        if reboot:
            print("rebooting onto the stored code ...")
            await client.write_gatt_char(UART_RX, b"load();\n", response=False)
            await asyncio.sleep(2)
    finally:
        # A link left half-open keeps the device believing a central is still
        # attached, which blocks the next connection for a supervision timeout.
        try:
            await client.disconnect()
        except Exception:
            pass

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--app", type=Path, required=True, help="the sketch to boot")
    parser.add_argument(
        "--no-reboot",
        action="store_true",
        help="leave the device running whatever it is running",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=180.0,
        help="how long to wait for the device to advertise (default 180s)",
    )
    args = parser.parse_args()
    return asyncio.run(
        run(args.address, args.app, not args.no_reboot, args.scan_timeout)
    )


if __name__ == "__main__":
    sys.exit(main())

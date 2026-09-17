# T1.1 — hardware test procedure `[HW]`

Everything below needs a physical nRF52-class Espruino board. The software side
is complete and unit-tested; this is the part that cannot be verified without a
radio.

> **Every step below has been run on protocol version 2**, on a Puck.js
> (`C8:80:32:AD:F7:B9`, 2v27) driven from the host — the results are recorded
> under each step and collected in `decisions.md` D-049. What still wants a pair
> of human eyes is the LED itself, the power-cycle behaviour and the Web IDE
> coexistence.

Where a step says "nRF Connect", `tools/espruino_deploy.py`,
`tools/bthome_write.py`, `tools/reject_matrix.py`, `tools/closed_loop.py` and
`tools/multi_instance.py` do the same job from a terminal against any host with
a Bluetooth adapter.

**Acceptance criterion (T1.1):** a write over GATT toggles the GPIO, and the
device acknowledges it.

## What you need

- An Espruino nRF52 board: Puck.js, MDBT42Q breakout, or Bangle.js.
- The [Espruino Web IDE](https://www.espruino.com/ide/).
- **nRF Connect for Mobile** (Nordic, Android/iOS) or nRF Connect for Desktop.

## Setup

1. In the Web IDE, open the sandbox and check that `require("BTHome")` resolves
   — the IDE pulls it from espruino.com/modules automatically.
2. Copy `BTHomeWritable.js` into the IDE's `modules/` folder (Settings →
   Project → Project Directory, then a `modules` subfolder), so
   `require("BTHomeWritable")` resolves locally.
3. Open `examples/single-light.js` and send it to the board. RAM is fine while
   you are still changing things. To leave it installed, do not use `save()` —
   put the modules in Storage under their bare names and the application in
   `.bootcde`, which is what `tools/espruino_deploy.py` does (D-023):

   ```
   python -m tools.espruino_deploy --address <mac>        --app espruino/examples/single-light.js
   ```

On upload the console should print the board's MAC address and:

```
writable entries: [ 30 ]
```

`30` is `0x1E`, BTHome's `light`: the declaration lists the object *types* the
device accepts writes for, in characteristic order. If it prints something else,
stop — the layout is wrong and every step below will mislead you.

## Step 1 — the advertising is well-formed

In nRF Connect, scan and find the board by its MAC. Expand its advertising data
and look at the **Service Data** for UUID `0xFCD2`.

Expected, with `<pid>` incrementing and `<batt>` your battery level:

```
40 00 <pid> 01 <batt> FF 1E
```

- `40` — BTHome v2, unencrypted.
- `00 <pid>` — packet id, changes every interval.
- `01 <batt>` — battery.
- `FF 1E` — the declaration, last in the service data: one entry, `0x1E`
  (`light`), served on characteristic `2FAA0001`.

The light's own value is **not** there, and must not be (§2.3).

**Record the exact hex string.** If `FF 1E` is missing, `setup()` threw — check
the IDE console.

> **Done, 2026-09-17.** `light-loop.js` advertises
> `40 00 <pid> 01 64 05 <lux×3> FF 1E`, 11 bytes, packet id incrementing.

## Step 2 — the service is discoverable

Connect to the board in nRF Connect. You should see a custom service with one
characteristic per declared entry:

```
2FAA0000-3B0B-4B1A-9E2A-B4C2952E62F2
  └─ 2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2   (WRITE)
```

Entry *k* is at `2FAA000k`, in hexadecimal: entry 10 is `2FAA000A`. A
characteristic is also READ only when the entry's value can change without a
write (step 7).

## Step 3 — a write toggles the GPIO

With the characteristic selected, write the byte string `1E01` (hex).

Expected: **LED1 lights up.** The console prints nothing (a successful write is
silent).

Write `1E00`. The LED goes out.

> **Done, 2026-09-17.** `python -m tools.bthome_write --address <mac> --payload
> 1e01` is acknowledged 16 ms after the link is up, the link itself taking 1.7 s
> from a Windows host.
>
> The LED physically lighting was verified too, and without anyone watching it:
> `examples/light-loop.js` drives the green LED and reads the Puck's light
> sensor, which works through the red one. Commanding the light on raises the
> device's own illuminance reading from 103 to 595 — **5.8x** — and commanding
> it off brings it back. Rerun with
> `python -m tools.closed_loop --address <mac>`.

## Step 4 — the write response is the acknowledgement

Version 1 confirmed a write through the refreshed advertising. Version 2 does
not: writable values are not advertised, and the GATT write response is what
says the bytes arrived (§4.2). So the thing to check here is that the device
*applies* what it acknowledged, which needs evidence of its own:

1. a measurement the device publishes — `tools/closed_loop.py`, step 3;
2. or the sketch's console — `print(lamp.on)` after the write;
3. or, on a device that reports state, a read (step 7).

What must **not** happen is the light's value appearing in the advertising.

> **Done, 2026-09-17.** All three routes agree, and nothing writable is
> advertised.

## Step 5 — bad writes are rejected, not partially applied

These exercise §4.2's strictness. The console prints the rejection code each
time, thanks to the `onError` hook in the example.

| Write | Expected console output | Expected LED |
|---|---|---|
| `1F01` (not the entry's object ID) | `write rejected: objectid_mismatch` | unchanged |
| `1E` (truncated) | `write rejected: truncated` | unchanged |
| `1E01FF02` (trailing bytes) | `write rejected: trailing_bytes` | unchanged |
| `` (empty) | `write rejected: truncated` | unchanged |

The trailing-bytes case is the important one: it is a stand-in for a second
object smuggled into one write. A parser that accepted the prefix would apply
it.

> **Done, 2026-09-17.** All four cases produced exactly the codes in the table,
> and `lamp.on` was unchanged afterwards. Rerun with
> `python -m tools.reject_matrix --address <mac>`.

## Step 6 — the entry number addresses the instance

Send `examples/three-lights.js`: three `light` entries, `FF 1E 1E 1E`. Write
`1E01` to `2FAA0001`, then to `2FAA0002`, then to `2FAA0003`.

Expected: each write moves one lamp, and it is the one whose number was
addressed. Then write `0F00` to `2FAA0001` — a `generic` object where the entry
says `light` — and expect `objectid_mismatch` with nothing changed.

> **Done, 2026-09-17.** Each entry moved only its own lamp; the mismatched write
> was refused. Rerun with `python -m tools.multi_instance --address <mac>`.

## Step 7 — reading back, when the device can change by itself

Send `examples/button-light.js`: the same light, switchable by the board's
button as well. Its entry has a `get`, so its characteristic is readable and the
advertising carries BTHome's settings revision (`0x65`).

1. Write `1E01`. Read the characteristic: `1E01`. The revision does **not** move
   — the receiver that wrote it already knows (§3.2).
2. Press the button. The revision changes, and a read returns the new value.

> **Done, 2026-09-17.** Read `1E01` after the write, revision unchanged at
> `0x50`; after a button press the revision went to `0x51` and the read returned
> `1E00`. `python -m tools.bthome_write --address <mac> --payload 1e01 --read`.

## Step 8 — it survives a reconnect and a reboot

1. Write `1E01`, disconnect, reconnect, write `1E00`. Still works.
2. Reset the board (`reset()` or the button). The LED starts off, advertising
   restarts, and a write still works.

## What to report back

- The exact service-data hex from step 1.
- Whether the LED followed every write in step 3.
- What proved the write was applied in step 4, and how long it took.
- The rejection codes from step 5, and whether the LED ever moved.
- Anything the IDE console printed that this document does not predict.

If any step fails, the hex string and the console output are enough to diagnose
it — send those rather than a description.

## One failure mode that looks like a bug in the module

A sketch sent over the console without `reset()` leaves the previous one's
globals, its `NRF.on()` listeners and the module cache in RAM. After three
deployments a Puck.js had 109 of 2630 blocks free, and the next
`require("BTHomeWritable")` failed with `Got UNFINISHED TEMPLATE LITERAL` — an
out-of-memory message wearing a syntax error's clothes (D-049). `reset()` first.

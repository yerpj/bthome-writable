# T1.1 — hardware test procedure `[HW]`

Everything below needs a physical nRF52-class Espruino board and a phone or
laptop running nRF Connect. The software side is complete and unit-tested; this
is the part that cannot be verified without a radio.

**Acceptance criterion (T1.1):** a write over GATT toggles the GPIO, and the
advertising reflects the new state within one advertising interval.

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
3. Open `examples/single-light.js` and send it to the board (RAM is fine for the
   test; `save()` only once it works).

On upload the console should print the board's MAC address and:

```
writable positions: [ 2 ]
```

Position 2, not 1, because BTHome's packet-id object occupies position 0
(PROTOCOL.md §8.3). If it prints something else, stop — the layout is wrong and
every step below will mislead you.

## Step 1 — the advertising is well-formed

In nRF Connect, scan and find the board by its MAC. Expand its advertising data
and look at the **Service Data** for UUID `0xFCD2`.

Expected, with `<pid>` incrementing and `<batt>` your battery level:

```
40 00 <pid> 01 <batt> 1E 00 FF 04
```

- `40` — BTHome v2, unencrypted.
- `00 <pid>` — packet id, changes every second.
- `01 <batt>` — battery.
- `1E 00` — light, currently off.
- `FF 04` — the declaration: bit 2 set, so position 2 (the light) is writable.

**Record the exact hex string.** If `FF 04` is missing, `setup()` threw — check
the IDE console.

## Step 2 — the service is discoverable

Connect to the board in nRF Connect. You should see a custom service:

```
2FAA47BC-3B0B-4B1A-9E2A-B4C2952E62F2
  └─ 639333F3-F21F-4558-9D85-06FCAC3436C2   (WRITE, WRITE NO RESPONSE)
```

## Step 3 — a write toggles the GPIO

With the characteristic selected, write the byte string `1E01` (hex).

Expected: **LED1 lights up.** The console prints nothing (a successful write is
silent).

Write `1E00`. The LED goes out.

## Step 4 — the advertising confirms it (the real acceptance criterion)

This is the one that matters, and it is easiest to see if you **disconnect
first**, because nRF Connect stops showing advertising while connected.

1. Write `1E01`, disconnect.
2. Scan again and read the service data.

Expected: `1E 01` where it read `1E 00`, and a different packet id.

**Measure the latency.** The device refreshes its advertising immediately on
applying the write (§6.2) rather than waiting for the next interval. With
`interval: 1000`, the new state should appear well under one second after the
write — not on the next round second. If it consistently takes a full interval,
the immediate refresh is not working, which matters for battery devices that
advertise every 10 s. Note what you observe.

## Step 5 — bad writes are rejected, not partially applied

These exercise §4.2's strictness. The console prints the rejection code each
time, thanks to the `onError` hook in the example.

| Write | Expected console output | Expected LED |
|---|---|---|
| `1F01` (wrong object ID) | `write rejected: objectid_mismatch` | unchanged |
| `1E` (truncated) | `write rejected: truncated` | unchanged |
| `1E01FF02` (trailing bytes) | `write rejected: trailing_bytes` | unchanged |
| `` (empty) | `write rejected: truncated` | unchanged |

The trailing-bytes case is the important one: it is a stand-in for a replayed
advertisement, which carries the declaration after the light object. A parser
that accepted the prefix would apply it.

## Step 6 — it survives a reconnect and a reboot

1. Write `1E01`, disconnect, reconnect, write `1E00`. Still works.
2. Reset the board (`reset()` or the button). The LED starts off, advertising
   restarts, and a write still works.

## What to report back

- The exact service-data hex from steps 1 and 4.
- Whether the LED followed every write in step 3.
- The latency observed in step 4 (immediate, or one full interval).
- The rejection codes from step 5, and whether the LED ever moved.
- Anything the IDE console printed that this document does not predict.

If any step fails, the hex string and the console output are enough to diagnose
it — send those rather than a description.

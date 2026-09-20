# Measurements

Everything this project has actually measured, in one place, with the command
that produces it again. The reasoning behind each number lives in
`spec/decisions.md`; this file is the numbers themselves, so they can be
compared, quoted and re-run without reading the log.

Each section says **when**, **on what**, and **with which tool**. A number
without those three is not a measurement, and several of the ones below read
very differently once the host is named.

## The bench

| | |
|---|---|
| **Puck.js** | `C8:80:32:AD:F7:B9`, Espruino 2v27, CR2032. Runs `light-loop.js` or `button-light.js` |
| **nice!nano** | `CD:F5:77:3A:B2:16`, Espruino 2v29.396, SSD1306 over I²C, USB powered. Runs `oled-text.js` |
| **Receiver** | Home Assistant 2026.7.4 (HAOS) on a Raspberry Pi 3, built-in `bcm43438` adapter, plus an ESP32 Bluetooth proxy (`esp32-bluetooth-proxy-1f1020`) |
| **Bench host** | Windows workstation with its own adapter, for the `tools/` measurements |

Two properties of the bench host are in every number it produces: WinRT takes
about 0.5 s longer to establish a link than BlueZ does, and it stops delivering
advertisements for several seconds after a disconnect (D-047). Where that
matters, the section says so.

## The radio conditions

Every timing in this file was measured in these conditions, and several of them
depend on it. Surveyed 2026-09-20; repeat with
`netsh wlan show networks mode=bssid` on the bench host.

| | |
|---|---|
| **2.4 GHz access points in range** | 5, **all on WiFi channel 1**, all at full signal, mean channel utilisation 33 % |
| **5 GHz access points in range** | 11 — they cost BLE nothing |
| **Other BLE devices advertising** | 8 to 13, depending on the scan |
| **Puck.js heard by** | the bench host at −42 dBm, the Raspberry Pi at −56 dBm |
| **nice!nano heard by** | the bench host at −62 dBm, the Raspberry Pi at −63 dBm |

WiFi channel 1 spans 2401–2423 MHz. BLE advertises on 2402, 2426 and 2480 MHz,
so **one of the three advertising channels sits under a permanently busy
transmitter** — and it is channel 37, the first one a scanner listens on. The
building has nothing on WiFi channels 6 or 11, which would otherwise impair
channel 38 as well.

This is not a footnote. A device at −66 dBm should have 24 dB of margin against a
BLE receiver's −90 dBm sensitivity, yet at that level a first command took five
times as long as at −44 dBm (§ below, and D-056). A quieter site will do better
than these figures; a site with access points spread over channels 1, 6 and 11
will do worse. Treat the numbers here as this building's, not the protocol's.

The two devices are also 20 dB apart as one receiver hears them, the nice!nano
being the weaker despite sitting closer to the bench host — a property of that
board's antenna and matching, and the reason its figures are slightly worse
throughout (D-056).

---

## 1. From a command to the write acknowledgement

**2026-09-18, both devices, through Home Assistant.** The sweep is
`tools/latency_sweep_write.py`; `tools/summarise_latency.py` prints the tables
below from the raw samples in `data/`, and the figure is
[`figures/latency-vs-interval.png`](figures/latency-vs-interval.png).

```
python -m tools.latency_sweep_write --device nano --idle 5 --fast-timeout 3000 \
    --out docs/data/write-nano-text.json
python -m tools.latency_sweep_write --device puck --idle 5 --fast-timeout 3000 \
    --out docs/data/write-puck-switch.json
python -m tools.summarise_latency docs/data/write-*.json
```

**What is timed.** From the command arriving in Home Assistant to the device
acknowledging the GATT write, split into the wait in the queue, the time to open
the link, and the write itself. Nothing downstream of the radio is counted: not
the device applying the value, not the refreshed advertising, not the entity
update. The integration measures it and fires `bthome_writable_write`; the sweep
subscribes to that event, so no witness on the device is involved.

**Two cases.** A *first* command is issued after the device has returned to its
idle advertising interval; *following* commands are issued straight after it,
while it is still advertising fast. Ten first commands and eight following ones
per interval, per device — 250 measurements in all.

**One thing was changed to make the sweep affordable:** `bw.setFastTimeout(3000)`
for its duration, restored to 30 s afterwards. Every first command has to wait
that window out, and the module's 30 s default turns each interval into eight
minutes of waiting. It does not touch what is measured — only how long it takes
to get the device back to its idle interval.

### Puck.js light switch

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | of which queued | Lost |
|---|---|---|---|---|---|---|---|---|
| 100 ms | 0.42 s | 0.45 s | 0.22 – 0.87 | 0.33 s (3.3×) | 36 ms | 1.90 s | 1.52 s | — |
| 200 ms | 0.55 s | 0.72 s | 0.20 – 2.50 | 0.51 s (2.5×) | 36 ms | 1.87 s | 1.58 s | — |
| 400 ms | 0.68 s | 0.73 s | 0.30 – 1.66 | 0.65 s (1.6×) | 36 ms | 1.88 s | 1.52 s | — |
| 700 ms | 1.43 s | 1.54 s | 0.22 – 3.53 | 1.40 s (2.0×) | 32 ms | 1.84 s | 1.46 s | — |
| 1.2 s | 1.90 s | 3.00 s | 0.27 – 9.15 | 1.86 s (1.6×) | 36 ms | 1.86 s | 1.42 s | — |
| 2 s | 4.41 s | 5.41 s | 0.24 – 12.00 | 4.38 s (2.2×) | 36 ms | 2.09 s | 1.58 s | — |
| 4 s | 9.34 s | 13.37 s | 4.76 – 44.48 | 9.30 s (2.3×) | 36 ms | 1.86 s | 1.54 s | — |

### nice!nano OLED text

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | of which queued | Lost |
|---|---|---|---|---|---|---|---|---|
| 100 ms | 0.31 s | 0.53 s | 0.17 – 1.60 | 0.26 s (2.6×) | 43 ms | 2.13 s | 1.54 s | — |
| 200 ms | 1.03 s | 0.91 s | 0.30 – 1.65 | 0.78 s (3.9×) | 43 ms | 2.15 s | 1.40 s | — |
| 400 ms | 0.77 s | 0.88 s | 0.16 – 1.66 | 0.73 s (1.8×) | 43 ms | 2.13 s | 1.46 s | — |
| 700 ms | 1.84 s | 2.12 s | 0.24 – 3.95 | 1.79 s (2.6×) | 43 ms | 1.81 s | 1.46 s | — |
| 1.2 s | 2.74 s | 2.63 s | 0.24 – 6.53 | 2.70 s (2.2×) | 43 ms | 2.26 s | 1.34 s | — |
| 2 s | 3.72 s | 4.05 s | 0.32 – 10.85 | 3.68 s (1.8×) | 43 ms | 1.90 s | 1.54 s | — |
| 4 s | 14.69 s | 16.02 s | 5.08 – 35.50 | 14.56 s (3.6×) | 43 ms | 1.94 s | 1.56 s | — |

### What the numbers say

**Opening the link is the cost, and it tracks the interval.** The Puck's median
connect time runs 0.33, 0.51, 0.65, 1.40, 1.86, 4.38, 9.30 s across the ladder
and the nice!nano's 0.26, 0.78, 0.73, 1.79, 2.70, 3.68, 14.56 s — two devices,
two firmwares, two payload types, agreeing within the spread. As a multiple of
the interval both sit between **1.5× and 3.9×**, with no systematic trend: the
cost is one or two advertising events plus the connection's own handshake, and
which of those dominates depends on where in the cycle the command lands.

**The write itself is never the cost**: 36 ms on the Puck, 43 ms on the
nice!nano, one byte or a whole string.

**Following commands are flat** at about 1.9 s on both devices at every
interval — and most of that was the receiver's own queue, not the radio: the
*queued* column reads 1.4–1.6 s, which was this integration holding a second
command behind the first. So the interval is a cold-start dial, not a latency
dial, and the warm path was bounded by the receiver.

> Measured before D-059. The 250 ms pause that produced most of that queued time
> went with the batching it served, and a following command now reconnects as
> soon as the one before it is acknowledged. The *first command* column, which is
> the protocol's own cost and the subject of this report, is unaffected — it never
> waited on that pause. The following-command figures are kept as the record of
> what was measured, not as a prediction of what the current code does; they are
> worth re-running before release.

**Nothing was lost.** 252 commands, 0 failures, 0 writes stalled past 5 s.

### How this run was set up, and why

Three things were changed after the first attempt, each of which had been
distorting the result:

- **The ESP32 proxy was disabled**, leaving Home Assistant to use the Raspberry
  Pi's own adapter. Through the proxy, some commands connected in less than half
  an interval — faster than catching an advertisement allows — because it reuses
  a recent link. Both devices are heard by the Pi at −56 and −63 dBm.
- **Each first command is issued after a random fraction of one interval**, on
  top of the idle wait. A fixed wait samples one phase of the advertising cycle
  ten times; the phase is exactly what determines how long the receiver waits.
- **The advertising was checked on the air** before starting: one BTHome train
  per device and nothing faster, with observed gaps at 0.98–1.01× the configured
  interval. A first check read 0.14× on the Puck — it was taken inside the
  device's fast-advertising window, which the sweep shortens to 3 s and waits
  out before every sample.

---

## 2. Version 2 round trip, on hardware

**2026-09-17, Puck.js, `tools/bthome_write.py` and Home Assistant** (D-049).

| What | Result |
|---|---|
| Write acknowledged | 16 ms after the link is up; 1.7–2.4 s including the connection, from the bench host |
| Physical effect (`tools.closed_loop`) | illuminance 103 → 595 lux → 103, a factor of 5.8 |
| Malformed writes (`tools.reject_matrix`) | `objectid_mismatch`, `truncated` ×2, `trailing_bytes`; state unchanged |
| Entry addressing (`tools.multi_instance`) | each of three entries moved only its own lamp |
| Read-back after a local change | settings revision 0x50 → 0x51, read returns the new value |
| Local change seen by Home Assistant | 4 s, of which 2 s was the bench host letting go of the device's single connection |

## 3. Earlier latency work, protocol version 1

Kept because the shape of the result still holds: the interval is a cold-start
dial, not a latency dial.

| Measurement | Result | Where |
|---|---|---|
| Click → confirmed, Home Assistant, 1 s interval | 1.7 s best, 3.3 s typical | D-013, D-016 |
| Click → confirmed at a 5 s interval | 1.7 s — the device is in fast mode for the interaction | D-024 |
| First command after idle, 500 / 2000 / 5000 ms | 4.2 s / 5–9 s / 8.1–36.9 s, one failure | D-021 |
| Idle refresh rate at a 5 s interval | a reading every 4.8–5 s | D-024 |

D-021's cliff is the same phenomenon §1 measures with more points: past a couple
of seconds, a missed advertising event costs a whole further interval plus the
connector's backoff, so the cost grows faster than the interval does.

## 4. How much a write can carry

| Board | MTU | Largest text that arrived | Binding constraint | Where |
|---|---|---|---|---|
| Puck.js 2v27, Windows host | 53 | 48 characters | MTU − 3, refused outright above it | D-017 |
| nice!nano 2v29.105 | — | 126 characters | the module's `maxWriteLength` of 128 | D-035 |

So neither the MTU nor the device alone predicts the ceiling; probe it with
`tools/text_limits.py` before designing around a number.

## 5. Advertising budget

The specification works the budget out as 31 − 3 (flags) − 4 (service data
header) = 24 bytes. Two boards disagree, in different directions, and both are
measured with `tools/adv_budget.py` or by bisection on the device.

| Board, firmware | Service data accepted | Note | Where |
|---|---|---|---|
| Puck.js 2v27, module defaults | 17 bytes | `showName:false` buys 3 more | D-030 |
| Puck.js 2v27, `showName:false` | 20 bytes | encrypted leaves 11 for objects | D-030 |
| nice!nano 2v29.242, with name | 7 bytes | this firmware refuses rather than shortening the name | D-046 |
| nice!nano 2v29.242, `showName:false` | 22 bytes | | D-046 |
| nice!nano 2v29.396, with name | 5 bytes | the 16-bit UUID is emitted again, costing 2 | D-049 |
| nice!nano 2v29.396, `showName:false` | 20 bytes | | D-049 |

For scale: a declaration costs one byte per writable entry plus the `0xFF`, and
version 2 advertises no writable values at all. Three writable lights are 4
bytes.

## 6. Encryption cost, on the device

**2026-09-10 and 2026-09-12, Puck.js 2v27** (D-026, D-028), reproducible with
`tools/ccm_bench.py`.

| What | Cost |
|---|---|
| One AES-CCM frame, first implementation | 31.8 ms, of which 4.5 ms is AES |
| One AES-CCM frame, the implementation that survives memory pressure | 75 ms |

Paid per packet rebuild rather than per advertisement, so at a 1 s interval it is
7 % of one second's work and nothing at all between rebuilds. The nice!nano had
no AES at 2v29.105 (D-035) and has it at 2v29.396 (D-045).

## 7. Availability

**2026-09-14, power under program control** (D-040).

| Event | Delay |
|---|---|
| Device powered off → entity `unavailable` | 3 min 34 s |
| Device powered on → entity back | first advertisement, ~1 s |

The delay belongs to Home Assistant's Bluetooth tracker, not to this
integration: nothing here can make a device grey out faster.

---

## Reproducing any of this

Every tool above takes `--address` and nothing else that matters, and every one
of them is safe to run against a device someone else is using except for the
sweep in §1, which changes the device's advertising interval. Take the bench
lock first (`docs/shared-bench.md`):

```
python -m tools.bench_lock acquire --note "latency sweep"
...
python -m tools.bench_lock release
```

The sweep leaves the interval wherever it stopped. Put it back with
`python -m tools.set_adv_interval --address <mac> --ms 1000` — and note that at
10 s that can take several attempts from a host whose adapter scans badly, which
is the same effect §1 measures.

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

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | Lost |
|---|---|---|---|---|---|---|---|
| 100 ms | 0.34 s | 0.52 s | 0.21 – 2.03 | 0.32 s (3.2×) | 36 ms | 1.97 s | — |
| 200 ms | 0.41 s | 0.54 s | 0.25 – 1.27 | 0.38 s (1.9×) | 36 ms | 1.94 s | — |
| 400 ms | 0.53 s | 0.70 s | 0.29 – 1.79 | 0.50 s (1.3×) | 36 ms | 2.02 s | — |
| 700 ms | 0.74 s | 1.28 s | 0.21 – 4.79 | 0.71 s (1.0×) | 36 ms | 2.02 s | — |
| 1.2 s | 0.42 s | 1.60 s | 0.22 – 4.60 | 0.39 s (0.3×) | 36 ms | 2.05 s | — |
| 2 s | 0.40 s | 1.78 s | 0.23 – 7.07 | 0.37 s (0.2×) | 36 ms | 1.94 s | — |
| 4 s | 0.43 s | 2.53 s | 0.14 – 13.51 | 0.40 s (0.1×) | 36 ms | 2.04 s | — |

### nice!nano OLED text

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | Lost |
|---|---|---|---|---|---|---|---|
| 100 ms | 0.44 s | 0.60 s | 0.29 – 1.29 | 0.31 s (3.1×) | 44 ms | 2.46 s | — |
| 200 ms | 0.54 s | 0.68 s | 0.24 – 2.20 | 0.40 s (2.0×) | 43 ms | 2.01 s | — |
| 400 ms | 0.68 s | 1.03 s | 0.24 – 2.19 | 0.46 s (1.1×) | 43 ms | 2.05 s | — |
| 700 ms | 0.60 s | 1.39 s | 0.28 – 6.69 | 0.56 s (0.8×) | 43 ms | 2.11 s | — |
| 1.2 s | 0.89 s | 1.74 s | 0.24 – 5.87 | 0.43 s (0.4×) | 44 ms | 2.35 s | — |
| 2 s | 1.90 s | 4.30 s | 0.24 – 15.72 | 1.86 s (0.9×) | 43 ms | 1.97 s | — |
| 4 s | 6.53 s | 5.27 s | 0.46 – 11.00 | 6.46 s (1.6×) | 100 ms | 2.33 s | 2 |

### What the numbers say

**The median is the number to read.** These distributions are not symmetric: a
connection attempt that misses its advertising window waits out another
interval, so each interval carries a few samples far above the rest. Where the
mean sits well above the median — 2.53 s against 0.43 s on the Puck at 4 s — the
gap is that tail, not noise to average away.

**Opening the link costs a floor plus part of an interval.** In seconds, the
Puck's median connect time runs 0.32, 0.38, 0.50, 0.71, 0.39, 0.37, 0.40 across
the ladder, and the nice!nano's 0.31, 0.40, 0.46, 0.56, 0.43, 1.86, 6.46. There
is a floor of roughly 0.3–0.4 s that owes nothing to advertising. Below about a
second of interval the floor dominates, which is why the same figure reads as a
large multiple of a small interval (3.2× of 100 ms is 0.32 s).

**The write itself is never the cost**: 36 ms on the Puck, 43 ms on the
nice!nano, whether the object written is one byte or a whole string.

**Following commands are flat** at about 2 s on both devices, at every interval,
because `fastTimeout` keeps a device advertising at 100 ms for 30 s once a
receiver has been in touch. This is the result that matters for a user
interacting with a device: the interval is a cold-start dial, not a latency
dial.

**Failures.** Two commands of 250 were never delivered, both on the nice!nano at
4 s. Each was logged on its entity as *the command did not reach the device*.

**A caution about the long intervals.** At 1.2 s and above the Puck connects in
less than half an interval — faster than a fresh connection should average. The
proxy is probably reusing a recent link. Those rows therefore say less about the
cost of catching an advertisement than the short ones do.

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

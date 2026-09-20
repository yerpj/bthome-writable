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

**2026-09-20, both devices, through Home Assistant**, on the one-command-per-
connection build (D-059). The sweep is `tools/latency_sweep_write.py`;
`tools/summarise_latency.py` prints the tables below from the raw samples in
`data/`, and the figure is
[`figures/latency-vs-interval.png`](figures/latency-vs-interval.png) — which plots
the mean alone, with nothing drawn around it, so the curve's shape reads at a
glance. The spread stays here, in the tables.

```
python -m tools.latency_sweep_write --device puck --out docs/data/write-puck-switch.json
python -m tools.latency_sweep_write --device nano --out docs/data/write-nano-text.json
python -m tools.summarise_latency docs/data/write-puck-switch.json docs/data/write-nano-text.json
```

**What is timed.** From the command arriving in Home Assistant to the device
acknowledging the GATT write, split into the wait in the queue, the time to open
the link, and the write itself. Nothing downstream of the radio is counted: not
the device applying the value, not the refreshed advertising, not the entity
update. The integration measures it and fires `bthome_writable_write`; the sweep
subscribes to that event, so no witness on the device is involved.

**Two cases, and the one thing that could have confused them.** A *first*
command is issued after the device has returned to the idle interval under test;
a *following* command is issued while it is still advertising fast. Those are
the two sides of the fast window (D-024), so a sample on the wrong side of it
measures the other case under this one's label — the single error that would
make the whole table meaningless.

It is not left to the arithmetic of the idle waits. The sweep stamps every
connection to the device, the ones that set the interval included, and records
with each sample how long the device had been left alone **when the command was
issued**. A first command counts only if that exceeds `fastTimeout`, a following
one only if it does not; anything else is flagged and dropped. Across both
campaigns, **251 delivered commands, none on the wrong side**.

The window was set to 8 s for the sweep (`bw.setFastTimeout(8000)`, restored to
30 s afterwards) with a 12 s idle wait plus a random fraction of one interval
before each first command, and a 1 s gap inside bursts. Long enough that a burst
stays inside the window, short enough that waiting it out does not dominate the
campaign. The sweep refuses to start unless the idle wait clears the window by
3 s and the burst gap falls inside it.

Ten first commands and eight following ones per interval, per device — 252
measurements in all.

### Puck.js light switch

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | of which queued | Lost |
|---|---|---|---|---|---|---|---|---|
| 100 ms | 0.31 s | 0.32 s | 0.19 – 0.53 | 0.28 s (2.8×) | 36 ms | 0.34 s | 0.00 s | — |
| 200 ms | 0.59 s | 0.59 s | 0.34 – 1.02 | 0.56 s (2.8×) | 36 ms | 0.29 s | 0.00 s | — |
| 400 ms | 1.01 s | 1.41 s | 0.35 – 5.12 | 0.98 s (2.4×) | 36 ms | 0.35 s | 0.00 s | — |
| 800 ms | 1.99 s | 3.65 s | 0.33 – 14.36 | 1.95 s (2.4×) | 36 ms | 0.33 s | 0.00 s | — |
| 1.6 s | 5.09 s | 5.87 s | 1.89 – 12.99 | 5.06 s (3.2×) | 36 ms | 0.46 s | 0.00 s | — |
| 3.2 s | 8.70 s | 14.02 s | 3.39 – 40.20 | 8.66 s (2.7×) | 36 ms | 0.31 s | 0.00 s | — |
| 5 s | 9.26 s | 13.75 s | 5.22 – 49.84 | 9.22 s (1.8×) | 36 ms | 0.38 s | 0.00 s | — |

### nice!nano OLED text

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | of which queued | Lost |
|---|---|---|---|---|---|---|---|---|
| 100 ms | 0.47 s | 0.96 s | 0.31 – 3.70 | 0.42 s (4.2×) | 43 ms | 0.57 s | 0.00 s | — |
| 200 ms | 0.50 s | 0.76 s | 0.37 – 1.71 | 0.41 s (2.0×) | 43 ms | 0.37 s | 0.00 s | — |
| 400 ms | 0.82 s | 1.19 s | 0.56 – 2.92 | 0.78 s (1.9×) | 43 ms | 0.42 s | 0.00 s | — |
| 800 ms | 3.23 s | 3.86 s | 1.07 – 10.91 | 3.10 s (3.9×) | 43 ms | 0.71 s | 0.00 s | — |
| 1.6 s | 5.79 s | 6.01 s | 1.74 – 11.79 | 5.68 s (3.5×) | 43 ms | 0.50 s | 0.00 s | — |
| 3.2 s | 11.72 s | 12.86 s | 3.92 – 35.12 | 11.68 s (3.6×) | 43 ms | 0.37 s | 0.00 s | — |
| 5 s | 8.87 s | 13.11 s | 0.50 – 39.62 | 8.83 s (1.8×) | 43 ms | 0.76 s | 0.00 s | 1 |

### What the numbers say

**Opening the link is the whole cost of a first command.** Subtract the connect
time from the median and 30 to 50 ms remain. The interval is therefore the only
dial that moves this number, and it moves it proportionally: 0.31 s at 100 ms,
9.26 s at 5 s on the Puck.

**It costs more than one advertising event, consistently.** As a multiple of the
interval the median connect time sits at **1.8–3.2× on the Puck and 1.8–4.2× on
the nice!nano**, with no interval where either device managed one. A receiver
does not listen continuously: it scans with a duty cycle and divides its
attention across the three advertising channels, so several of a device's
advertising events go by before one is caught — and on this bench one of those
three channels sits under a permanently busy WiFi transmitter (§ the radio
conditions). Two to three events is what that costs here. A quieter site, or a
receiver scanning at a higher duty cycle, should do better; neither was isolated
in this campaign, so treat 2–3× as this bench's figure rather than the
protocol's.

**Following commands are now flat and cheap**: median **0.34 s on the Puck and
0.52 s on the nice!nano**, at every interval, and the queue contributes **0.00 s**
everywhere. This is where D-059 shows: the previous campaign measured 1.9 s, of
which 1.4–1.6 s was the integration holding the second command behind the first.
Removing the batching removed the pause it needed, and a following command is
now a connection to a device that is already advertising at 100 ms — which is
exactly what the two-speed advertising exists to provide.

**The write itself is never the cost**: 36 ms on the Puck, 43 ms on the
nice!nano, one byte or a whole string.

**One command out of 252 was lost**, on the nice!nano at a 5 s interval: no
acknowledgement inside 60 s. Nothing stalled past 5 s. The weaker of the two
links (§ the radio conditions) failing once at the slowest interval is the shape
one would expect; it is one sample, not a rate.

**The mean is worth reading next to the median.** They agree at short intervals
and diverge above 400 ms — 8.70 s against 14.02 s on the Puck at 3.2 s. Each
missed advertising event costs a whole interval, so the tail is made of samples
that waited two or three more of them. The median says what usually happens; the
gap says how often it does not.

### How this run was set up, and why

The bench conditions of the previous campaign (D-054) were kept, because each of
them had been distorting the result before it was applied:

- **The ESP32 proxy was disabled**, leaving Home Assistant on the Raspberry Pi's
  own adapter. Through the proxy, some commands connected in less than half an
  interval — faster than catching an advertisement allows — because it reuses a
  recent link. Both devices are heard by the Pi at −56 and −63 dBm.
- **Each first command is issued after a random fraction of one interval**, on
  top of the idle wait. A fixed wait samples one phase of the advertising cycle
  ten times; the phase is exactly what determines how long the receiver waits.
- **The automation that writes to the nice!nano every 30 s was turned off.** It
  would have kept that device permanently inside its fast window.

Two things are new in this campaign:

- **Home Assistant was restarted onto the D-059 build** before starting, and the
  absence of `WRITE_DEBOUNCE` on the receiver was verified rather than assumed.
  The previous numbers were measured on the batching build and are kept in
  `data/archive/write-*-batched.json`.
- **The fast window is checked per sample, not assumed** — see *Two cases* above.

One correction was made after the fact and is worth stating plainly. The sweep
first stamped the idle time *after* each command returned, which charged the
command's own duration to it, and flagged one 9.6 s following command on the
nice!nano as though it had been issued outside the fast window. It had been
issued 1.9 s after the previous one. The tool now reads the idle time when the
command is issued, and the two stored datasets carry the corrected annotation,
derived exactly as `idle_for_s - total_ms/1000`. No timing was changed by this:
the correction affects one boolean on one sample, and that sample is back in the
5 s row of the nice!nano table.

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

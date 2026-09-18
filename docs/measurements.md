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

## 1. Response time against advertising interval

**2026-09-17, both devices.** The sweeps are `tools/latency_sweep.py` (from the
bench host) and `tools/latency_sweep_ha.py` (through Home Assistant); the figure
is [`figures/latency-vs-interval.png`](figures/latency-vs-interval.png), redrawn
from the raw samples in `data/` with `tools/gen_latency_figure.py`.

```
python -m tools.latency_sweep --address C8:80:32:AD:F7:B9 --kind switch \
    --out docs/data/latency-puck-switch.json
python -m tools.latency_sweep_ha --device nano --out docs/data/ha-nano-text.json
python -m tools.latency_sweep_ha --device puck --out docs/data/ha-puck-switch.json
python -m tools.gen_latency_figure docs/data/*.json \
    --out docs/figures/latency-vs-interval.html
```

**What is timed, and from where.** Two vantage points, because they answer two
questions:

- **From the bench host** — catch an advertisement, connect, write one object,
  receive the write response. This is the protocol itself, timed in its three
  phases. It also carries this host's WinRT penalty, which is large (D-047).
- **Through Home Assistant** — a service call, over the Pi's adapter or the
  ESP32 proxy, until the *device* shows it acted. The service call returns in
  about 0.3 s, long before anything reaches the device, so each device needs a
  witness that does not take its single BLE connection: the nice!nano's USB
  console, which prints what it drew, and the Puck's own light sensor.

**Two cases, because they are two different questions.** A device advertises at
its idle interval only when nothing has talked to it recently: after any
disconnection this module advertises at 100 ms for 30 s (`fastTimeout`). So each
*first* sample is preceded by a 35 s silence, and the *following* samples are
taken straight after it, while the device is still in fast mode. Three first
commands and five following ones per interval, alternating the value written so
the device really acts each time.

### Puck.js switch, from the bench host

| Interval | First command | Spread | Following commands |
|---|---|---|---|
| 100 ms | 0.89 s | 0.87 – 0.90 | 1.69 s |
| 200 ms | 1.86 s | 1.50 – 2.16 | 1.15 s |
| 500 ms | 3.82 s | 2.67 – 5.38 | 0.44 s |
| 1 s | 10.81 s | 2.91 – 16.89 | 0.49 s |
| 2 s | 15.46 s | 6.69 – 24.79 | 0.35 s |
| 5 s | 33.17 s | 19.93 – 54.68 | 0.42 s |
| 10 s | 44.82 s | 34.89 – 54.59 | 0.70 s |

### Puck.js switch, through Home Assistant

Witness: the device's own light sensor, read back as a Home Assistant sensor.

| Interval | First command | Spread | Following commands | Failed |
|---|---|---|---|---|
| 100 ms | 4.99 s | 1.23 – 12.49 | 1.51 s | 1 |
| 200 ms | 1.43 s | 1.24 – 1.63 | 1.73 s | 1 |
| 500 ms | 3.40 s | 3.19 – 3.60 | 2.09 s | 1 |
| 1 s | 3.70 s | 2.02 – 5.49 | 3.05 s | 1 |
| 2 s | 8.27 s | 7.69 – 8.94 | 2.60 s | — |
| 5 s | 11.47 s | 8.48 – 14.75 | 9.88 s | 1 |
| 10 s | 24.55 s | 14.39 – 33.99 | 17.94 s | 2 |

Seven of 49 commands never produced a visible effect. Home Assistant logged each
on the entity: *the command did not reach the device … Failed to connect.*

### nice!nano text, through Home Assistant

Witness: the sketch's own console over USB, which prints what it drew.

| Interval | First command | Spread | Following commands | Failed |
|---|---|---|---|---|
| 100 ms | 1.01 s | 0.84 – 1.25 | 1.27 s | — |
| 200 ms | 1.46 s | 1.02 – 1.90 | 1.04 s | 1 |
| 500 ms | 1.65 s | 1.01 – 2.04 | 1.00 s | — |
| 1 s | 1.85 s | 1.01 – 2.63 | 1.07 s | — |
| 2 s | 4.85 s | 2.56 – 8.92 | 1.15 s | — |
| 5 s | 8.16 s | 4.68 – 14.91 | 0.98 s | — |
| 10 s | 8.19 s | 4.86 – 14.72 | 1.33 s | 1 |

Two of 56 commands never reached the device. Both are real failures a user would
see, not measurement artefacts — Home Assistant logs them on the entity.

**The interval is a cold-start dial, not a latency dial.** Where the witness
sees the command itself — the nice!nano's console, or the bench host's write
response — the line for following commands is flat: 0.35 – 1.7 s everywhere, at
100 ms and at 10 s alike. That is `fastTimeout` doing its job: once a receiver
has been in touch, the device advertises at 100 ms for the next 30 s, so the
idle interval does not apply to the interaction at all.

What the interval buys battery with is the idle refresh rate and the cost of the
*first* command after a quiet period, and that cost grows faster than the
interval does: on the Puck from the bench host, twenty times the interval
(0.5 s → 10 s) costs twelve times the wait, with the worst single sample at
55 s. The mechanism is in the phases the sweep records: at a 2 s interval, 57 to
82 % of a first command is spent waiting to catch an advertisement, before any
connection is attempted.

**Fast advertising speeds the radio, not the packet.** The Puck's
through-Home-Assistant line does *not* flatten for following commands: it climbs
to 18 s at a 10 s interval, where the nice!nano stays at 1 s. The two are
measuring different things, and the difference is in the module.
`goFast()` changes how often the radio transmits, but the packet itself is
rebuilt — and its sensors re-read — on a timer that keeps running at the idle
interval. The Puck's witness is a *sensor value*, so it waits for that rebuild;
the nice!nano's witness is the sketch's console, which sees the write as it
lands. A user watching a state that comes from advertising therefore waits an
idle interval for it, however fast the command itself was.

**The receiver matters as much as the device.** At a 5 s interval the same kind
of first command takes 33 s from this Windows host and 8 s through Home
Assistant — the Pi and the ESP32 proxy scan continuously, where WinRT stops
delivering advertisements for seconds around every disconnection (D-047). Read
the bench-host curve as an upper bound on a poor receiver, and the Home
Assistant curve as what a user experiences.

**Writes do fail, and the rate is worth stating.** Seven of 49 commands to the
Puck through Home Assistant never produced an effect, against two of 56 to the
nice!nano. Each is logged on the entity, so a user is told; none was silent.
Whether the difference is the device, its battery or where it sits relative to
the proxy is not established here.

**Two cautions about the bench host.** Its Bluetooth stack stopped being able to
open connections part-way through the campaign; cycling the radio (the Windows
`Radio` API, no administrator rights needed) fixed it. And a first reading of
"the host has gone deaf" was wrong: both devices were sitting at a 10 s interval
at the time, so one or two packets in 25 s was exactly right. The number that
means something is not the packet count but whether a connection opens.

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

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
the median alone, with nothing drawn around it, so the curve's shape reads at a
glance. The median and not the mean, because the figure is asked what the
mechanism typically does and the mean at the slow paliers is carrying this
receiver's connection retries (*The retries*, below). The mean, the spread and
the retry count all stay here, in the tables.

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
one only if it does not; anything else is flagged and dropped. Across every run
here, **439 delivered commands, none on the wrong side**.

The window was set to 8 s for the sweep (`bw.setFastTimeout(8000)`, restored to
30 s afterwards) with a 12 s idle wait plus a random fraction of one interval
before each first command, and a 1 s gap inside bursts. Long enough that a burst
stays inside the window, short enough that waiting it out does not dominate the
campaign. The sweep refuses to start unless the idle wait clears the window by
3 s and the burst gap falls inside it.

Ten first commands and eight following ones per interval, per device. The two
rows marked † pool a second run of the same paliers, made on 2026-09-21 because
the first one's numbers there did not look right: thirty first commands each,
and the reason is the subject of *The retries* below. The cell marked ‡ pools a
third run of repeated commands only, for the reason given under the tables.
**444 commands in all.**

### Puck.js light switch

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | of which queued | Lost |
|---|---|---|---|---|---|---|---|---|
| 100 ms | 0.31 s | 0.32 s | 0.19 – 0.53 | 0.28 s (2.8×) | 36 ms | 0.34 s | 0.00 s | — |
| 200 ms | 0.59 s | 0.59 s | 0.34 – 1.02 | 0.56 s (2.8×) | 36 ms | 0.29 s | 0.00 s | — |
| 400 ms | 1.01 s | 1.41 s | 0.35 – 5.12 | 0.98 s (2.4×) | 36 ms | 0.35 s | 0.00 s | — |
| 800 ms | 1.99 s | 3.65 s | 0.33 – 14.36 | 1.95 s (2.4×) | 36 ms | 0.33 s | 0.00 s | — |
| 1.6 s | 5.09 s | 5.87 s | 1.89 – 12.99 | 5.06 s (3.2×) | 36 ms | 0.46 s | 0.00 s | — |
| 3.2 s † | 6.53 s | 9.84 s | 3.18 – 40.20 | 6.49 s (2.0×) | 36 ms | 0.32 s | 0.00 s | — |
| 5 s † | 12.34 s | 14.50 s | 0.97 – 49.84 | 12.31 s (2.5×) | 36 ms | 0.36 s | 0.00 s | 1 |

### nice!nano OLED text

| Interval | First, median | mean | range | of which connecting | Write itself | Following, median | of which queued | Lost |
|---|---|---|---|---|---|---|---|---|
| 100 ms | 0.47 s | 0.96 s | 0.31 – 3.70 | 0.42 s (4.2×) | 43 ms | 0.57 s | 0.00 s | — |
| 200 ms | 0.50 s | 0.76 s | 0.37 – 1.71 | 0.41 s (2.0×) | 43 ms | 0.37 s | 0.00 s | — |
| 400 ms | 0.82 s | 1.19 s | 0.56 – 2.92 | 0.78 s (1.9×) | 43 ms | 0.42 s | 0.00 s | — |
| 800 ms | 3.23 s | 3.86 s | 1.07 – 10.91 | 3.10 s (3.9×) | 43 ms | 0.71 s | 0.00 s | — |
| 1.6 s | 5.79 s | 6.01 s | 1.74 – 11.79 | 5.68 s (3.5×) | 43 ms | 0.50 s | 0.00 s | — |
| 3.2 s † | 9.43 s | 11.72 s | 0.18 – 37.40 | 9.39 s (2.9×) | 43 ms | 0.43 s | 0.00 s | 2 |
| 5 s † | 11.29 s | 14.55 s | 0.50 – 39.62 | 11.24 s (2.3×) | 43 ms | 0.37 s ‡ | 0.00 s | 2 |

### What the numbers say

**Opening the link is the whole cost of a first command.** Subtract the connect
time from the median and 30 to 50 ms remain. The interval is therefore the only
dial that moves this number, and it moves it proportionally: 0.31 s at 100 ms,
12.34 s at 5 s on the Puck.

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

**Following commands are now flat and cheap**: median **0.33 s on the Puck and
0.40 s on the nice!nano**, at every interval, and the queue contributes **0.00 s**
everywhere. This is where D-059 shows: the previous campaign measured 1.9 s, of
which 1.4–1.6 s was the integration holding the second command behind the first.
Removing the batching removed the pause it needed, and a following command is
now a connection to a device that is already advertising at 100 ms — which is
exactly what the two-speed advertising exists to provide.

**The write itself is never the cost**: 36 ms on the Puck, 43 ms on the
nice!nano, one byte or a whole string. Measured from a second receiver the same
exchange takes **14 ms** (D-066), so two thirds of those figures are this
receiver's path rather than the GATT write — which changes nothing about the
conclusion, since both are negligible beside the seconds spent opening the link.

‡ **The nice!nano's repeated commands at 5 s were measured on their own**, on
2026-09-21, because sixteen samples there were being decided by two of them: one
retried connection at 41 s and one slow one at 9.6 s put the mean at 3.6 s while
the other fourteen sat between 0.27 and 1.30 s. Ten separate bursts of eight —
separate, so that one lucky stretch of air could not stand for the rest — give
**eighty samples, none lost, none retried**: median **0.36 s**, quartiles 0.29
and 0.44, ninth decile 0.59, worst 1.94. That is the mechanism's own figure for a
repeated command, and the table's cell now pools all ninety-six samples.

**Five commands out of 444 were lost** — one on the Puck, four on the
nice!nano, all at 3.2 s or 5 s, none acknowledged inside 60 s. Nothing stalled
past 5 s.

**The mean is worth reading next to the median**, and above 800 ms the gap
between them is not the advertising interval's doing. See below.

### The retries, and why the slow rows were re-measured

The first run's numbers at 3.2 s and 5 s were not reproducible: re-measuring
them moved the median by 30 to 50 %, in both directions, on both devices. That
is not a small sample being noisy around a true value — something discrete was
being sampled. Pooling both runs, 120 first commands at those two intervals, the
time to open the link falls into **two groups with an eleven-second hole between
them**:

| | n | range |
|---|---|---|
| Opened the link | 103 | 0.1 – **19.4 s** |
| *nothing at all* | 0 | 19.4 – 30.5 s |
| Opened it late | 12 | **30.5** – 49.8 s |

The far group is **10 % of first commands**, its mean is 37.7 s, and — the part
that identifies it — **it does not scale with the advertising interval** while
the near group does. A cost that is the same at 3.2 s and at 5 s is not made of
advertising events.

It is the receiver's own connection layer. `establish_connection` is called with
`max_attempts=2`: an attempt that times out is followed by a second one, and the
pair costs a fixed penalty on top of whatever the advertising interval was going
to cost. The five lost commands are the case where the second attempt failed
too, inside the sweep's 60 s window.

**What this changes.** Nothing about the protocol, and nothing about the first
five rows, where no sample fell in the far group. But at 3.2 s and 5 s it
inflates the mean by several seconds and it dominates the range, so those two
rows are quoted here from thirty samples rather than ten. Excluding the retried
commands, the link opens in **1.9–2.9× the interval** at these paliers —
the same two-to-three advertising events as everywhere else in the table. The
slow end of the ladder is not where the protocol degrades; it is where the
receiver's retry becomes visible against a longer baseline.

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

## 1b. What encryption costs

**2026-09-21, Puck.js, through Home Assistant.** The same campaign as the
regression guard, on the same device, at the same advertising interval, run once
with `light-loop.js` in clear and once with `encrypted-light.js` sealed under the
published test-vector bindkey. Raw samples in
[`data/encrypted-vs-plain.json`](data/encrypted-vs-plain.json).

```
python -m tools.espruino_deploy --address <mac> --app espruino/examples/encrypted-light.js
python -m tools.regression --device puck
```

| | In clear | Encrypted |
|---|---|---|
| First command, median | 1.74 s | 2.32 s |
| First command, 90th percentile | 5.58 s | 3.81 s |
| Repeated command, median | 0.31 s | 0.36 s |
| Repeated command, 90th percentile | 0.51 s | 0.65 s |
| **The write itself** | **36.0 ms** | **36.1 ms** |
| Delivered | 8/8 and 16/16 | 8/8 and 16/16 |
| Connected without a retry | 100 % | 100 % |

**No measurable difference.** Every figure sits inside the run-to-run spread of
the unencrypted build against itself, which moved the first-command median from
1.74 s to 2.25 s on an unchanged device (D-065). The write itself is identical to
a tenth of a millisecond, and nothing was lost on either side.

### What this measurement cannot see, and it matters

**The device acknowledges a write before it decrypts it.** That is §3, and it is
deliberate: the GATT layer answers, and only then does the module unseal the
payload, check the counter and apply the value. So the AES-CCM cost on the
device falls *after* the acknowledgement this campaign times, in the window
between Home Assistant believing it is done and the lamp actually moving.

The figure to distrust, therefore, is not the one above but any claim that
encryption is free. What the table establishes is narrower and still useful:
**sealing costs nothing on the path a user experiences as command latency** —
catching an advertisement, opening the link, and getting the write acknowledged.
On this device the whole of that is seconds, and AES-CCM does not touch it.

What it costs on the device is unmeasured here. Two figures bound the
expectation: one AES-CCM frame took 31.8 ms in the first implementation and
75 ms in the one that survives memory pressure (D-028), and a sealed packet
spends 8 of its service-data bytes on the counter and MIC — which is why the
encrypted example carries no battery reading. Measuring the applied-effect
latency rather than the acknowledgement, with the light loop as the witness,
would settle it.

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

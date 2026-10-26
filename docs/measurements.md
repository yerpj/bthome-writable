# Measurements

Everything this project has actually measured, in one place, with the command
that produces it again. The reasoning behind each number lives in
`spec/decisions.md`; this file is the numbers themselves, so they can be
compared, quoted and re-run without reading the log.

Each section says **when**, **on what**, and **with which tool**. A number
without those three is not a measurement, and several of the ones below read
very differently once the host is named.

Every write latency here except §13 was measured before D-117, so before an
acknowledged write to a readable entry was checked against the device. That
check is one GATT read inside the connection already open; §13 is what it costs
and what it is worth.

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
times as long as at −44 dBm (D-056, from `docs/data/tx-power-puck.json`). A
quieter site will do better
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
interval the median connect time sits at **2.0–3.2× on the Puck and 1.9–4.2× on
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

**The device acknowledges a write before it decrypts it.** That is §4.2, and it is
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

For scale: a declaration costs one byte per writable entry plus two — the
`0xFF` and the count — and version 2 advertises no writable values at all.
Three writable lights are 5 bytes: `ff 03 1e 1e 1e`.

## 6. Encryption cost, on the device

**2026-09-10 and 2026-09-12, Puck.js 2v27** (D-026, D-028), reproducible with
`tools/ccm_bench.py`.

| What | Cost |
|---|---|
| One AES-CCM frame, first implementation | 31.8 ms, of which 4.5 ms is AES |
| One AES-CCM frame, the implementation that survives memory pressure | 75 ms |

**Broken down, 2026-10-12, Puck.js 2v27** — asked for by Gordon Williams on
`EspruinoDocs#763`, *"do you know which bits in particular?"*. A 7-byte BTHome
frame, 20 runs:

| | ms | % of frame |
|---|---|---|
| Whole frame (7-byte payload) | 54.9 | |
| &nbsp;&nbsp;`tagOf`, the CBC-MAC half | 19.1 | 34 |
| &nbsp;&nbsp;`stream`, the keystream half | 25.7 | 46 |
| &nbsp;&nbsp;&nbsp;&nbsp;the cipher itself | 2.9 | 5 |
| &nbsp;&nbsp;&nbsp;&nbsp;`macBlock`, per-block bookkeeping | 9.2 | 16 |
| &nbsp;&nbsp;&nbsp;&nbsp;`counters`, the same shape plus one AES | 12.3 | 22 |

A 30-byte payload is 92.2 ms. Directly: `AES.encrypt` of 32 bytes is 2.07 ms in
ECB and 2.35 ms in CBC, and a 7-byte frame makes one call of each — so **the
cipher is under a tenth of what sealing costs**, and the rest is the
JavaScript around it. That has not moved since the first implementation: 4.5 ms
of AES then, 2.9–4.4 ms now. What grew was the bookkeeping.

**And JIT does not rescue it** (`"jit"`, Puck.js builds it):

| | speedup |
|---|---|
| `macBlock` as written, JIT | 1.37× |
| A loop of pure arithmetic, JIT | 2.16× |
| The same bookkeeping rewritten as plain byte loops so JIT has arithmetic to compile | **4.1× slower** than the typed-array methods, and still 1.9× slower after JIT |

The last row is the finding. `fill`, `set` and `subarray` are native and already
the fast path; JIT cannot accelerate a method call, and replacing them with the
loops it *can* compile loses more than it gains. What is left to pay is the
interpreter's per-call and per-statement cost, which is not something a
compiler reaches at this granularity.

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

## 8. What rebuilding the advertisement costs, and what the fix removes

**Puck.js `C8:80:32:AD:F7:B9`, 2026-10-19**, after the three D-106 fixes. This
board has `AES` but no `AES_CCM`, which is @enaon's configuration exactly: the
`AESCCM` module's JavaScript fallback over the hardware block cipher. It is
therefore the first board here that could measure the sealed case at all.

Rebuilds are counted on the device, by wrapping `NRF.setAdvertising` from the
console, because a scanner's duplicate filtering hides most packets from the
host.

### One rebuild

| | |
|---|---|
| plaintext, packet id + illuminance + declaration | **22 ms** |
| sealed, same packet | **133-142 ms** |

So **sealing is six times the rest of the rebuild**, and at a 1 s interval a
sealed device that rebuilds every second spends 13% of its single thread doing
it. That is the shape of @enaon's +135 uA.

### Idle, nothing connected

| | |
|---|---|
| `single-light.js`, battery with no interval | **11 rebuilds in 20 s** |
| the same entry at `interval: 300000` | **0 rebuilds in 25 s** |
| `encrypted-light.js`, illuminance at `interval: 0` | **27 rebuilds in 25 s** |
| the same entry at `interval: 300000` | **0 rebuilds in 25 s** |

Before the fix all four would have been one per advertising interval: 20, 25,
25, 25.

**The saving depends on the advertised values being stable, which is worth
saying plainly.** `E.getBattery()` on a CR2032 returns 61 then 62 then 61; at
1% resolution that is a real change, and a real change is a real packet. An
entry read every tick on a noisy sensor therefore still rebuilds about half the
time -- correctly, since its data moved. The examples that give the battery
`interval: 300000` get the whole saving; `single-light.js` does not, because it
gives its battery no interval at all.

### A burst of writes

| | |
|---|---|
| 100 plaintext writes in 1.78 s | **2 rebuilds**, median 15.0 ms per write |
| 50 sealed writes in 0.72 s | **0 rebuilds**, median 13.8 ms per write |

Measured before the fix: **112 rebuilds for 100 writes**. Sealed, those 56
rebuilds a 50-write burst would have triggered are 7.5 s of CPU queued behind
0.72 s of writes -- which is the dimming stutter @enaon reported, and which
never showed in the write latency because Espruino acknowledges a GATT write
before running `onWrite`.

The two plaintext rebuilds are the connection itself (the advertising rate
changes, which is a real change) and one tick where the battery reading moved.
The sealed burst arrived while the device was already advertising fast, so not
even that one was needed.

### What it saved, measured by someone else

@enaon ran a PPK2 against the fix on his own nice!nano, bindkey and counter
report, 1 s interval: **~235 uA before, ~50 uA after**, against a baseline of
~45 uA with the module not loaded at all. His variant that keeps the bytes and
patches the counter came out at ~85 uA. His conclusion, which agrees with the
profile above: the cost was the reconstruction of the payload, not the call to
`NRF.setAdvertising`.

### Two clocks

2000 iterations on the Puck, with the interpreter's own 209 us of loop overhead
subtracted: **`Date.now()` costs 240 us a call, `getTime()` 162 us.** Raised by
@enaon. At one call per tick it is 0.008% of the thread, which is why the module
still calls `Date.now()`.

### The same thing on a nice!nano, over the cable

`CD:F5:77:3A:B2:16`, nRF52840, 2v29.396, `AES` but no `AES_CCM` -- @enaon's
chip and @enaon's cipher path. Measured with a bench sketch holding his
configuration: one voltage entry at five minutes, one writable light, 1 s
interval, bindkey and counter report. **The console is on USB here**, so the
device could be asked what it was doing while nothing at all was connected to
its radio -- which is what "idle" was supposed to mean on the Puck and could
not quite be.

| | |
|---|---|
| one rebuild, plaintext | **20 ms** |
| one rebuild, sealed | **90-91 ms** |
| 30 s idle, sealed, nothing connected | **0 rebuilds** |
| 25 s idle, plaintext | **0 rebuilds** |
| 100 writes over the air, counted over USB | **0 rebuilds** |

So AES-CCM from JavaScript is **~70 ms of the 90**, three and a half times the
rest of the rebuild, on the faster of the two chips. And the plaintext figure
cross-checks @enaon's profile: he measured 26-29 ms before the fix, of which he
attributed 8.5 ms to the declaration and the sort, which are now computed at
`setup()`. 26-29 minus 8.5 is 18-21, and this board rebuilds in 20.

**One bench artifact worth knowing.** Espruino moves its console to Bluetooth
the moment a central connects, so counting rebuilds during a burst needs
`USB.setConsole(true)` to keep the console on the cable. With the console
pinned that way, the same hundred writes took **400 ms each** instead of 15:
the link runs at a slower connection interval when Espruino's console is not
using it. Rebuild counts are unaffected, but no latency measured with the
console pinned to USB means anything -- and it is a lead worth following for a
receiver that writes several entries in one connection.

### Reproducing it

The three scripts live in the session scratchpad rather than in `tools/`: they
patch the running sketch from the console, which is a measurement technique
rather than something to ship. `bw.plan().ordered[n].readInterval` is writable
from the console, which is how the stable case was measured without
redeploying.

## 9. What the two follow-up proposals are worth

**nice!nano `CD:F5:77:3A:B2:16` over its cable, 2026-10-20**, 2v29.396, `AES`
without `AES_CCM`. Measured with the module exactly as EspruinoDocs#765 merged
it, before writing a line of the proposals, because a proposal that cannot show
its gain is a proposal that should not be offered. Plaintext figures are
`examples/oled-text.js` (die temperature at 30 s, a writable text entry, 9 bytes
of service data); sealed ones are a bench sketch in @enaon's configuration
(voltage at 300 s, a writable light, bindkey, counter report, 17 bytes).

Two proposals are on the table, both from `espruino#8024` after the merge:

* **P1, @gfwilliams'**: *"have readAdvertised return the minimum time until the
  next thing needs updating"* -- because with `interval: 1000` and an entry at
  `interval: 300000` the timer wakes 300 times to act once.
* **P2, this bench's**: stop rebuilding the packet when only the advertising
  *rate* changes -- `goFast()` and the fast window expiring both call
  `refreshAdvertising()` to alter one field of the advertising options.

### One empty wake of the interval timer

Espruino will not let the console shadow a builtin: after `setInterval = f`,
`""+setInterval` still prints `function () { [native code] }` and the module's
own call is unaffected. The timer cannot be wrapped, so it was weighed instead
-- a fixed computation run while the timer fires at a known rate, then again
with every timer cleared. That also counts the part a JavaScript wrapper could
never see: the interpreter leaving its idle loop.

The advertised entry keeps its 30 s interval throughout, so every wake measured
here is a wake that found nothing to do.

| 2 697 interpreted loop iterations, median of five | |
|---|---|
| timer at 1000 ms (0.8 wakes inside the bench) | 789.6 ms |
| timer at 20 ms (**40** wakes inside the bench) | 802.3 ms |
| `clearInterval()`, no timer at all | 802.6 ms |

So forty empty wakes cost **-0.3 ms**: nothing, below this instrument's noise.
An empty wake is under ~10 us of CPU, and the 1 s run came out *faster* than no
timer at all, which says the same thing twice.

The other end of the bound is @enaon's PPK2: the fixed module idles at ~50 uA
against ~45 with it not loaded at all. **Everything P1 could possibly recover is
inside that 5 uA**, wakes, timer bookkeeping and all.

A by-product worth keeping: the interpreter costs **297 us per iteration** of a
one-statement loop on this board. That is why `Date.now()` at 240 us looked
expensive in D-106 -- it is cheaper than the loop that calls it.

### A rebuild, against handing the radio the bytes it already has

| | plaintext, 9 B | sealed, 17 B |
|---|---|---|
| a rebuild -- `bw.update()`, mean of five | **21.6 ms** | **92.3 ms** |
| the same bytes published again | **2.3 ms** | **3.0 ms** |

`NRF.setAdvertising` itself is 2.2 ms of that, measured separately inside the
wrapper. Everything above it -- reading the due entries, encoding each object,
sealing, framing -- is **19 ms plaintext and 89 ms sealed**, and none of it is
needed to change an advertising interval.

### What one connect/disconnect cycle spends today

Counted over the cable with the fast window shortened to 3 s, so nothing of
ours was connected while the count was read.

| | rebuilds |
|---|---|
| plaintext, connect + disconnect + window expiry | **3** |
| sealed, same cycle | **2** |

Two of them are `goFast()` and the window expiring. The plaintext third was a
tick whose die temperature had genuinely moved, which is the module working
correctly. So a sealed device spends **184 ms of its single thread per
connection** to change one field of `opts`, and a plaintext one 43 ms.

An unplanned confirmation of the same thing: a 30 s sealed idle count, taken
with nothing connected, came back as **1 rebuild** rather than 0 -- the 30 s
fast window from the *deployment's own* disconnect expiring inside the
measurement window. The cost is paid once per connection whether or not
anything was written.

### So

**P2 is worth 89 ms of a sealed device's thread per connection and can be shown
on an instrument. P1 is correctness and tidiness, not power** -- it is right
(Gordon is not wrong that 299 wakes in 300 do nothing), and it buys at most a
fraction of 5 uA. Offering it as an efficiency fix would be offering a number
this bench cannot produce.

### The bench, as left on 2026-10-20

* the integration on the bench was **six files and one version behind**
  (`0.0.1` against the repository's `0.1.0`); it is now byte for byte the
  repository, and Home Assistant was restarted onto it;
* the nano boots `examples/oled-text.js` from flash again, the Puck boots
  `examples/light-loop.js`, both with the current modules in Storage;
* the regression baseline was re-recorded on commit `7b9cb57` -- the previous
  one was from 2026-09-21, before D-102 and D-106 -- and **a second run against
  it passes every check on both devices**;
* the write itself has not moved in a month: **35.8 then 36.0 ms** on the Puck,
  **43.5 then 43.3 ms** on the nano. First-command medians are 1.5-2x
  September's (3.2 s and 5.1 s against 1.7 s and 2.5 s) with the same spread
  reappearing in the verification run (2.5 s and 3.8 s), so the cause is in
  catching an advertisement, not in the module. Unexplained, and recorded as
  unexplained; the September figures remain in `git log -p` on this file;
* the ESP32 proxy's config entry and the OLED automation were found **already
  disabled** by an earlier campaign, not by this one, and were left as found.

## 10. What P2 removed, measured before and after

**nice!nano `CD:F5:77:3A:B2:16` over its cable, 2026-10-20**, 2v29.396, `AES`
without `AES_CCM`. The same board, the same two sketches and the same instrument
as section 9: `NRF.setAdvertising` is wrapped from the console, which counts
every advertisement and, by comparing its bytes with the previous ones, says
whether it was a new packet or the one already on air. The only thing that
differs between the two columns below is the module in Storage -- the merged one
for *before*, the one with P2 for *after*.

### A rate change, end to end

`bw.setAdvertisingInterval()` is the public call that does nothing but move the
advertising rate, which makes it the whole of P2 in one measurable statement.
Median of five, alternating 1000 and 1100 ms so that every call is a real
change.

| | before | after |
|---|---|---|
| plaintext, 9 bytes of service data | 28.0 ms | **12.5 ms** |
| sealed, 17 bytes | 98.2 ms | **14.1 ms** |
| new packets published, out of five calls | 5 | **0** |

A first attempt returned 4.8 ms *before* P2, which is worth keeping because it
reads like a result and is not one: it is the function declining to publish at
all. `setAdvertisingInterval()` republishes only when no fast window is pending,
and a deployment's own disconnect arms a 30 s one. Every figure above waited
40 s first.

What remains after P2 is not the packet. Of those 14.1 ms, 3.4 is the radio call
with freshly built argument objects -- 2.7 when the same objects are handed back
-- and the rest is the function's own work, walking the entries and reinstalling
the interval timer. `bw.setFastTimeout()`, which does neither, costs 1.25 ms.

### One connect/disconnect cycle

Counted over the cable with the fast window shortened to 3 s, as in section 9.

| advertisements published / of which new packets | before | after |
|---|---|---|
| plaintext | 2 / 2 | 2 / **0** |
| sealed | 2 / 2 | 2 / **0** |

The count does not move: `goFast()` and the window expiring each still tell the
radio something. Neither of them is a packet any more. At the rebuild costs
measured on the same board in the same runs -- 23.4 then 24.1 ms plaintext,
94.5 then 95.2 ms sealed -- **a sealed connection now spends about 7 ms of its
single thread where it spent 189**, and a plaintext one 7 where it spent 47.

Section 9 counted three rebuilds for the plaintext cycle and this run counted
two, because no die temperature moved inside it. The third was never the rate
change.

### What did not move

A rebuild is 94.5 ms sealed before and 95.2 after; the radio call alone is 2.69
and 2.72. P2 costs the paths it does not touch nothing, which is the other half
of what a before-and-after is for.

### The device-side regression, with P2 deployed to both boards

`tools.regression` against the baseline recorded on `7b9cb57`, after deploying
the new module to the nano (`examples/oled-text.js` in flash) and to the Puck
(`examples/light-loop.js` in flash). **Fourteen checks, seven per device, all
ok, "no regression" on both.**

| | baseline | now | limit |
|---|---|---|---|
| Puck, the write itself | 35.8 ms | 35.9 ms | 91.6 |
| Puck, first command, median | 3.222 s | 2.392 s | 5.455 |
| nano, the write itself | 43.5 ms | 42.9 ms | 107.0 |
| nano, first command, median | 5.136 s | 3.110 s | 8.518 |

Both first-command medians came in *faster* than a baseline recorded this
morning -- the same wide spread section 9 recorded as unexplained, falling the
other way for once. Delivery and connect-without-a-retry were 1.0 on both.

## 11. What P1 changed: the read cadence, and nothing on a meter

**nice!nano `CD:F5:77:3A:B2:16` over its cable, 2026-10-20**, running
`examples/oled-text.js`: one advertised entry, the die temperature, at
`interval: 30000`, inside an advertising interval of 1000 ms. The only thing
that differs between the two runs is the module in Storage.

P1 is @gfwilliams' proposal: no fixed timer, each wake armed from whatever entry
falls due soonest. Section 9 had already measured what that saves -- 40 empty
wakes cost −0.3 ms, an empty wake is under 10 µs, and @enaon's PPK2 bounds the
whole of it inside 5 µA -- so this run was not asked for a current figure. It
was asked whether the device still reads on time, which is what P1 could break,
by watching `lastRead` on the device for 75 s.

| time between two reads of a 30 s entry | |
|---|---|
| before P1, the fixed 1 s tick | **31 000 ms**, twice |
| after P1 | **30 104 ms**, twice |

**The fixed tick was the less exact of the two, which was not expected.** A
30 000 ms deadline inspected every 1000 ms is only noticed at the first tick
*past* it, so the entry was re-read every 31 s -- the deadline quantised up to a
whole advertising interval. P1's own slack is 100 ms, fixed and known, and -- by the
same arithmetic rather than by a second measurement -- it is the quantisation
that grew with the advertising interval: this same entry on the module's default
2000 ms interval would have been re-read every 32 s.

So the 100 ms the page admits to is not a cost against what it replaces. It is a
tenth of what the quantisation was already taking here.

### What was not measured, deliberately

No current figure, and no wake count. A wake that finds nothing due does nothing
observable from the console, and the console cannot wrap `setInterval` or
`setTimeout` to count one -- Espruino refuses to let a builtin be shadowed
(section 9). The claim that a battery at five minutes now causes one wake per
five minutes rather than three hundred is a claim about the code, checked by
unit tests on the scheduler rather than by an instrument, and section 9 is why
nobody should expect to see it on a PPK2.

### Non-regression

`tools.regression` against the `7b9cb57` baseline, P1 deployed to both boards: **"no regression" on both**, thirteen of the fourteen checks plain `ok`. The write itself is 35.8 ms on the Puck -- the baseline figure to the tenth -- and 43.3 on the nano against 43.5. The one flag is a *fast* one: the nano's first-command 90th percentile came in at 4.176 s against a 14.993 s baseline, which the tool is built to question rather than celebrate (D-054, a proxy reusing a link looks exactly like this). The nano also delivered 0.958 of its commands rather than 1.000, inside the 0.900 the check allows. Both belong to the first-command spread section 9 recorded as unexplained; neither touches the read timer.

## 12. The chain, with Home Assistant in it

**2026-10-20, commit `06a3da0`** -- P1 and P2 both in, both boards redeployed
from it. `tools.chain_test`, described in [`chain-test.md`](chain-test.md),
which says what each check asserts and what it would catch. The procedure is
there; this is what it answered.

```
the chain, end to end
  ok   A  the integration is loaded                   bthome_writable
  ok   A  every entity of both devices is there       5 entities
       nothing to change -- the bench was already prepared, which usually means an earlier run did not finish; it will be left exactly as found
  watching the fast entry for 30 s ...
  ok   B  interval 0 arrives at the advertising rate  11 reports in 30 s, median gap 2.2 s, worst 4.4 s
  ok   D  a command lands on the puck                 3.63 s, write 36 ms
  ok   D  a command lands on the nano                 2.09 s, write 42 ms
  ok   E  a write through HA moves what HA measures   75 lx off, 540 lx on, difference +465 against 16 needed (noise 3.7)
  ok   F  ten commands in a row all arrive            10/10 delivered, median 0.38 s
  ok   F  and the last one is what stands             switch.bureau_mobilesensf7b9_light is off, expected off
  ok   G  the fast window closing is invisible        15 reports across it, now 75.58 lx
  ok   G  and the writable entity did not go unavailable switch.bureau_mobilesensf7b9_light is off
  waiting 165 s more for the five-minute entry ...
  ok   C  interval 300000 arrives every five minutes  1 reports in 320 s
       the same device reported its one-second entry 140 times in that window: one timer, two cadences
       the nano's 30 s die temperature reported 0 times -- it is published only when the reading moves (D-106), so few or none is correct on a board sitting still
  ok   H  nothing new in Home Assistant's log         0 new or repeated entries, none about this

the chain is qualified
```

### What the two cadences look like from Home Assistant

Checks B and C are P1 from the far end of the chain, and they are the figures
worth keeping: on one device, with one self-arming timer, Home Assistant is
told about the `interval: 0` illuminance at the advertising rate and about the
300 s battery every five minutes. Neither entry disturbs the other, which is
the whole of what @gfwilliams asked for in `espruino#8024`.

### What the radio shows next to it

A three-minute passive scan from this host, taken the same evening, counting
every advertisement from both boards:

| | advertisements in 180 s | distinct payloads |
|---|---|---|
| Puck.js, `light-loop.js` (illuminance at `interval: 0`) | 117 | 61 |
| nice!nano, `oled-text.js` (die temperature at 30 s) | 57 | **1** |

The nano advertised **fifty-seven times with one single packet**: its die
temperature did not move, so nothing was rebuilt and the radio repeated what it
held. That is D-106 and D-109 together, seen from outside the device, and it is
also why Home Assistant had not been told anything new about that entry for
seventeen minutes -- correctly.

### The same run after the audit fixes, on `be0158f`

D-114 changed `handleWrite()`, `setup()`, `update()` and what the timer calls,
so the hardware checks were taken again from the top: both boards redeployed
from that commit, then the chain test, then `tools.regression` on each.

**Chain test: every check passed again.** What moved, all in the right
direction: the first command on the Puck came in at 0.82 s against 3.63, the
burst of ten at a 0.29 s median against 0.38, and the illuminance arrived 12
times in 30 s against 11. The closed loop read 77 lx off against 545 on. Across
the 320 s window the one-second entry reported **149 times and the five-minute
entry once**, which is the same two-cadence result as before.

**Regression: fourteen checks, all plain `ok`, "no regression" on both.** The
write itself is 36.1 ms on the Puck and 43.2 on the nano, against a 35.8/43.5
baseline. Delivery came back 1.000 on both, so the 0.958 the nano showed earlier
in the evening did not recur.

### The malformed advertisements, and where they are not from

Home Assistant's own log held two payloads attributed to these boards that had
lost the `0xFF` declaration byte, which makes `bthome-ble` read the rest as
objects and warn that object ids are out of order (D-111 has the lines). What
the boards really advertise was captured at the same time:

```
nano  400010026009ff0153        packet id 16, temperature 24.0, declaration [0x53]
puck  400041015305d4d200ff011e  packet id 65, battery 83, illuminance 539.72, declaration [0x1e]
```

Both parse cleanly, in ascending object id order, declaration last, with no
warning. The Puck's logged payload differs from a real one in exactly one byte.
And of the **174 advertisements** counted in the scan above, through this host's
adapter, **none was malformed**.

So the damage is in a receive path, not in the module -- and not in this host's.
Recorded rather than explained: check H is what will say whether it recurs.

## 13. What confirming a write costs, and what it cannot prove

**2026-10-21**, branch `candidate/enaon-retest`, nice!nano running
`espruino/bench/many-writables.js` sealed with @enaon's three entries, Home
Assistant 2026.7.4 on the Pi's own adapter, the ESP32 proxy out of the way. Ten
`switch.turn_on` / `turn_off` commands on entry 1, each after twelve seconds of
idle plus a random fraction of an advertising interval. The integration's own
`bthome_writable_write` event, which gained `confirm_ms` for this.

| | median | min | max |
|---|---|---|---|
| the write itself (`write_ms`) | **58 ms** | 42 | 963 |
| to the acknowledgement (`total_ms`) | **707 ms** | 228 | 8128 |
| the read back (`confirm_ms`) | **832 ms** | 88 | 1601 |
| the service call, end to end | **4047 ms** | 3266 | 12157 |

`total_ms` stops at the acknowledgement, so the receiver's own latency is it
plus `confirm_ms`: confirming a write roughly **doubles** it, 1.5 s against
707 ms. The rest of the service call is the disconnect and Home Assistant's own
machinery, and was there before.

Why 832 ms for a read of one byte, when the write is 58: the module seals the
entry's value and hands it to `NRF.updateServices` on the tick after the write,
and the read waits behind that work on the device's single thread. It is the
same sealing cost §6 measures, met from the other side.

### And what it buys

Nothing, on this device. The same run on the first build of D-120 failed **every
`turn_off` and confirmed every `turn_on`**, four of each, with the board's own
console showing the lamp off each time it was called undelivered:

```
LAMP {"isOn":true,"bri":0.6,"auto":false}     before
HA turn_off: HTTP Error 500: Internal Server Error
LAMP {"isOn":false,"bri":0,"auto":false}      after
```

§4.3's getter is published, not served on demand. A device that applies a write
asynchronously -- a fade, a ramp, a debounce -- republishes before the effect
exists, so it answers the read with the value it had, and the asymmetry is
exactly when the application mutates its own state: `fadeTo` sets `isOn` true on
the way up and clears it twelve 20 ms steps later on the way down.

So a read back can adopt a value the device reports differently, and cannot
distinguish a lost write from one not yet republished. D-122 has what follows
from that.

## 14. What folding a burst of `changed()` calls is worth

**2026-10-22**, branch `candidate/enaon-retest`, nice!nano running
`espruino/bench/many-writables.js` -- @enaon's three writable entries, all with
a `get`, a battery advertised at five minutes, two PWM channels being
reconfigured fifty times a second -- driven with `bench.loop(20, 50)`: twenty
simulated button presses 50 ms apart, so 950 ms of pressing. The same board,
the same sketch and the same burst on either side of D-124, with the module
before it taken from the commit before the fix. `NRF.setAdvertising` was wrapped
on the console to count publications.

| 20 presses in 950 ms | before | after |
|---|---|---|
| `bw.changed()`, per call | **375 ms** (worst 397) | **2 ms** |
| publications | **20** | **3** |
| thread time in rebuilds | ~7.5 s | ~1.1 s |
| the fade ran during the burst | no, `bri` stayed 0.00 | yes, `bri` moved |
| error flags after | none | none |
| free JsVars after | 8055 | 8013 |

Seven and a half seconds of work for one second of presses is the finding. The
thread was oversubscribed eight to one, which is why the application's own fade
never got a step in edgeways: `bri` is still 0.00 twenty presses later. After the
fold it is 3 publications for 20 presses, the call itself is arming a timer, and
the fade runs.

Three rather than the four a 250 ms window suggests, because each publication
blocks for 375 ms and pushes the next window out behind it.

`LOW_MEMORY` did not appear on this board either way. It has 12 000 JsVars and
8 000 free at the worst of it, where @enaon's lamp reported `LOW_MEMORY` with
13 000 and 363 collections counted; its console was also on USB here rather than
on the BLE link. So the saturation reproduces and the exhaustion does not, which
is honest to state: what the bench shows is the cause, not his whole chain.

### Conformance, from outside the device

The same burst with `SEALED = false`, watched from this host's adapter:

```
t= 0.47s  400001015365a5ff031e1e09  pid=1 rev=165
t= 6.86s  400003015365a7ff031e1e09  pid=3 rev=167
t= 7.55s  400004015365a8ff031e1e09  pid=4 rev=168
```

The settings revision advances by exactly one per window, 165 to 168 for three
publications, the declaration is still last and the packet is still twelve
bytes. One bump per window is all S3.2 asks for: that the revision change when a
value moves by itself, not how often. A payload the scanner missed is a payload
the next window replaced.

Home Assistant, on the Pi's own adapter, re-read the device once per window:

```
14:08:39  entry 1: read object 0x1E | entry 2: read object 0x1E | entry 3: read object 0x09
14:08:51  entry 1: read object 0x1E | entry 2: read object 0x1E | entry 3: read object 0x09
14:08:58  entry 1: read object 0x1E | entry 2: read object 0x1E | entry 3: read object 0x09
```

Every entry read as the object it declares, through a burst that would have been
twenty rebuilds before. The run also caught, benignly,
`[org.bluez.Error.InProgress]` inside `async_clear_service_cache` while two
connection attempts overlapped: the same BlueZ error @enaon reported, recovered
here by D-118's own path, which dropped the cached table and read the device
again.

## 15. The sealed path, end to end, on the module of this branch

**2026-10-22**, the test that had to happen before @enaon is asked to retest.
D-123 replaced four `Math.pow` with `readUint(pl, n, n + 4)` in `openWrite()`,
which is how a sealed device reads the write counter out of a write it has not
yet decrypted. Unit tests and the shared vectors cover the function; nothing had
run it on a radio.

nice!nano running `espruino/bench/many-writables.js` sealed with @enaon's three
entries and `counterReport: true`, the test-vector bindkey set on the config
entry through the integration's own reconfigure flow, ten `switch.turn_on` /
`turn_off` on entry 1 five seconds apart, then the counter report.

| | |
|---|---|
| commands accepted | **9 of 10** |
| service call, median of the nine | **2250 ms** (min 1578, max 4422) |
| the state followed the command | every time |
| errors reported by the device | **0** |
| `E.getErrorFlags()` after | none |

Zero errors on the device is the result that matters: not one `mic_mismatch`,
not one `counter_not_increasing`, not one `truncated`. Every write that reached
the board authenticated and its counter was read correctly. The reads of all
three entries, sealed, were correct throughout (`entry 1: read object 0x1E`,
`entry 2: 0x1E`, `entry 3: 0x09`).

Faster than §13's 4047 ms because the commands are five seconds apart rather
than after twelve seconds of idle, so the device stays inside its fast
advertising window, and because a write is no longer retried when the device
reports the value it had (D-122).

### §5.6, the counter report, exercised twice

```
15:51:10  the device reports write counter 1792616629; keeping 1792677067,
          which is already ahead of it
15:53:08  write counter resynchronised to 1792777077
```

The first is the integration asking on its own after a failed write; the second
is the `Resynchronise write counter` button. Both answers were sealed under the
read direction and authenticated, which is the whole of §5.6's exchange.

### The one failure, which was not the module's

Command 2 returned HTTP 500 after 17.8 s without reaching the board. It went
through the ESP32 proxy, which had been switched back on an hour earlier and
which hears that board at **-36 dBm** against the Pi's **-63**, so it is what
gets chosen and the connection then does not complete. 92 writes failed that way
in 90 minutes, all of them the OLED automation's. The proxy is off again, and
D-127 has the rest of it: our own scoring and Home Assistant's named that same
proxy with the same number, four writes out of four, so this was never a defect
in D-117's heuristic -- which has since been removed for agreeing with the stack
at best -- and it does not explain @enaon's fault 2, which happened on his local
adapter with every proxy disabled. What it does expose is upstream's: a path
that connects and then lets a GATT operation time out costs that source nothing
in the next choice.

## 16. The slow first command, and what actually gates it

**2026-10-23, the Puck, through Home Assistant on `hci0` alone.** @enaon asked
whether his bench's behaviour is ours: his first command to a light after three
to five minutes of inactivity takes 5 to 10 s, the next one 1 to 3 s, and he
sees it on his local adapter alone, on an ESP32 proxy alone and on both. He
reads it as a Home Assistant effect.

§1 already measured the mechanism across seven advertising intervals, with the
fast window shortened to 8 s so that a campaign of 444 commands could be run at
all. What it did not answer is the part his question turns on: whether waiting
*minutes* costs more than waiting just past the window. So three runs, this time
with the module's real 30 s window.

```
python -m tools.latency_sweep_write --device puck --fast-timeout 30000     --intervals 1000 --idle 40  --first-reps 3 --burst 3
python -m tools.latency_sweep_write --device puck --fast-timeout 30000     --intervals 1000 --idle 300 --first-reps 2 --burst 2
python -m tools.latency_sweep_write --device puck --fast-timeout 30000     --intervals 3200 --idle 40  --first-reps 3 --burst 3
```

| Interval | Idle before the command | First command | Following |
|---|---|---|---|
| 1000 ms | 40 s | 0.72, 1.90, 3.39 s | 0.28, 0.79, 1.09 s |
| 1000 ms | 300 s | 3.39, 1.18 s | 0.29, 0.91 s |
| 3200 ms | 40 s | 0.47, 6.71, 4.51 s | 0.28, 0.77, 0.30 s |

**The minutes buy nothing.** Five first commands at a 1000 ms interval, three
taken 40 s after the last connection and two taken 300 s after it, all fall in
the same 0.7 to 3.4 s band, and the two slowest of the five are one from each
group. Eight samples settle no distribution, and the spread of a first command
is wide by nature (D-060) -- but if waiting five minutes cost something the
fast window does not, it would have to hide inside a band that a 40 s wait fills
just as well. What gates the slow first command is the fast window closing,
30 s by default, after which the device is back on its idle interval. Any
inactivity past that buys the same wait.

**And the interval is the dial.** At 3200 ms the first command runs 4.5 to 6.7 s
on two of three samples, which is @enaon's 5 to 10 s; at 1000 ms it is about a
third of that. Every sample's cost is the connection: `0.00 s queued` on all
eight, 23 to 65 ms of write, and everything else inside
`establish_connection` waiting for the central to catch an advertising event.
That is §1's finding again, 2 to 3 events on this bench.

**What it does not say is what his lights idle at.** This section first read his
5 to 10 s back through the 3200 ms row and concluded that his interval was
around 3 s. He corrected it an hour later, on the thread: he is at 1000 ms, and
the commands he had timed came while Home Assistant was restarting, so the
receiver was asking each light for its write counter before commanding it --
*two* connections, not one. Two connections at a 1000 ms interval land in the
same 5 to 10 s band from the table above without any slower interval being
involved. The receiver's half of that is §17; the figures in this section stand,
and the extrapolation from them to his bench did not.

**A following command is flat**, 0.28 to 1.09 s at either interval, because the
device is still inside its fast window. Those are the two sides of the same
mechanism, not two different problems.

So: not Home Assistant's doing, and not a defect. The dials are the device's,
both in the module: `bw.setFastTimeout(ms)` keeps it fast longer after a
connection, and `bw.setAdvertisingInterval(ms)` lowers the idle interval. Both
are paid for in current, which §5 and §6 price.

---

## 17. The counter question, carried on the command's own connection

**2026-10-23, the Puck, through Home Assistant on `hci0` alone.** §16's
correction says where @enaon's 5 to 10 s came from: a restart of Home Assistant,
and the §5.6 counter question going first. This section is the receiver change
that follows (D-129) and what it is worth.

**What the question cost.** `ALLOW_COUNTER_SYNC` is on (D-080), so a configured
sealed device is asked what write counter it is at before anything is written to
it: at setup, and again before the first command after its settings revision
moves. The exchange is three packets -- write an 8-byte challenge, read back
`seal(challenge || counter)` -- and it used to take **a connection of its own**.
§5.6 asks for no such thing; it specifies the exchange and says nothing about
which connection carries it. So the question now rides the connection the
command itself makes.

**What that is worth, and what it is not.** The exchange is tens of milliseconds
on a link that is already up. A connection is 0.7 to 3.4 s at a 1000 ms
advertising interval and 4.5 to 6.7 s at 3200 ms (§16, §1). So:

| When the command arrives | Separate question | Folded |
|---|---|---|
| While the question's connection is pending or not yet made | two connections, the command queued behind the first | one connection |
| Long after the question has finished | one connection | one connection, plus the exchange inside it |

The first row is @enaon's case and the reason for the change. The second row is
what it costs, and it is not zero: a device whose revision moves while nobody is
commanding it used to have its question answered in the background, and now
pays for it on the next command. The exchange is the price, and §13's reads say
what to expect of it on a sealed board: one sealed read back took 832 ms median
on a nice!nano sealing on a single thread, and 23 to 65 ms on this Puck.

**Measured here so far, on the clear path.** The restructuring moves the sealing
of a write *inside* the connection, because the counter has to be drawn after
the adoption (D-083 item 11). That is the write path of every device, sealed or
not, so it was run against the regression guard first:

```
python -m tools.regression --device puck
```

| | Baseline | This change |
|---|---|---|
| First command, median | 3.22 s | 2.07 s |
| Repeated command, median | 0.33 s | 0.42 s |
| The write itself, median | 35.8 ms | 43.5 ms |
| Delivered | 24/24 | 24/24 |
| Connected without a retry | 100 % | 100 % |

**No regression.** The write itself is 7.7 ms above the baseline, and the same
figure came back twice in a row on a bench whose five access points all sit on
WiFi channel 1 (§8); the guard allows twice the baseline plus 20 ms, and this is
inside the run-to-run spread D-065 measured on an unchanged device. Worth
recording honestly: the first of the two runs was started two minutes after the
restart and had **4 of its 24 commands undelivered**, with nothing in the log;
the second, ten minutes later, delivered 24 of 24. A bench whose Bluetooth stack
has just come up is not a bench to judge a release on.

### What is not measured yet, and the procedure to measure it  [HW]

Neither bench device is sealed today -- both config entries hold no bindkey --
so **the folded exchange has never run against a real device**. Nothing in the
clear path exercises it: without a bindkey no question is ever owed. The two
numbers still missing are the exchange's own cost inside the connection
(`counter_ms`, which this change adds to the `bthome_writable_write` event) and
the first-command latency of the two arms in the table above.

The run needs the Puck sealed, which means a sketch with a bindkey and
`counterReport: true`, and the configured device holding the same key:

```
python -m tools.bench_lock acquire --note "D-129 sealed A/B"
python -m tools.espruino_deploy --address C8:80:32:AD:F7:B9 \
    --app espruino/examples/encrypted-light.js
# then, in Home Assistant: Settings > Devices > Puck.js f7b9 > Reconfigure,
# and give it 231d39c1d7cc1ab1aee224cd096db932 (the test-vector key, public).
python -m tools.counter_question_cost --arm folded --reps 3 \
    --out docs/data/counter-question-folded.json
```

Then the other arm: set `FOLD_THE_COUNTER_QUESTION_INTO_A_WRITE = False` in the
deployed `custom_components/bthome_writable/const.py`, restart Home Assistant,
and run the same command with `--arm separate`. Afterwards put the board back
(`--app espruino/examples/light-loop.js`), clear the bindkey through Reconfigure,
restore the constant, and release the lock.

**Expected, if the reasoning above holds:** the *immediate* case about one
connection faster folded, which on this bench is one to three seconds; the
*settled* case equal within the spread, the fold's own `counter_ms` being tens
of milliseconds against a connection of seconds; and `counter_ms` zero on every
sample of the separate arm, because there the question was answered elsewhere.
A folded sample whose write is refused would say the counter was drawn in the
wrong order, which is the one thing this change could get wrong.

---

## 18. A read folded into a command: the connection count, and what it is worth

**2026-10-23, a third nice!nano, through Home Assistant on `hci0` alone.** D-130
makes a command carry the read §3.2 has already called for. This section has
three parts, and they do not all say what was expected.

### The fixture, and why one had to be built

Neither bench board can exercise this. The Puck.js advertises no settings
revision, and the nice!nano's text entry has a `set` and no `get`, so neither
owes a read at all. A third board, on `COM6`, now runs
[`espruino/bench/revision-lamp.js`](../espruino/bench/revision-lamp.js): a
`light` and a `count`, both writable **and** readable, so the device advertises a
revision, plus `bench.knob()`, which moves the count locally and calls
`bw.changed()` the way a knob would. The board counts connections itself
(`NRF.on('connect')`, `bench.conns()`), which is the only count that cannot be
argued with.

Its firmware has no crypto -- `MODULES` is
`timer,Flash,Storage,heatshrink,neopixel`, so `AES` is not defined -- so it
cannot run a sealed sketch, and §5.6's counter report (D-129) is still
unmeasured on hardware.

### The measurement, and the honest result

Per sample: reset the board's counter, issue a command, and move the knob
0.2 s later, while the command still holds the connection slot. Then wait 20 s
and ask the board how many centrals connected, and Home Assistant what the
count entity says. Nine samples per arm, the same deployed code, one constant
flipped between them and Home Assistant restarted.

| Nine samples each | `FOLD_A_DUE_READ_INTO_A_WRITE = True` | `= False` |
|---|---|---|
| Connections per sample | 1 eight times, 2 once | 1 seven times, 2 twice |
| The knob's value in Home Assistant within 20 s | **8 of 9** | **4 of 9** |
| Command, median | 2.8 s | 5.9 s |
| Command, range | 1.5 to 33.6 s | 1.7 to 17.2 s |

**The connection count barely moved, and that is the finding.** The expectation
was two connections becoming one. What happens instead is that with the fold off
the second connection *frequently never happens*: the read is requested, it
competes with the command for the device, and it fails rather than queueing --
an Espruino serves one central at a time, and the integration's own cap of two
connections per host (D-003) lets a read and a command reach for the same device
at once. So the saving does not show up as a connection removed. It shows up as
**a local change that arrives**: 8 of 9 against 4 of 9.

**The command's own latency says nothing here.** Both arms are bimodal, 1.5 to
2.1 s when nothing collides and 13 to 34 s when something does, in both arms,
and nine samples settle no distribution. The medians differ in the fold's favour
and the ranges overlap; the first three folded samples read 1.8, 1.5 and 2.8 s
and would have supported a much stronger claim than the next six allow. Recorded
as it came out.

**What this measurement also found, and it is not D-130's.** Those 13 to 34 s
commands, and the reads that vanish, are two of our own connections arriving at
one device. That is the hazard named in D-003's discussion and it is in `main`
as much as on this branch: the connection cap is per host and the serialisation a
device needs is per device. The fix is a lock per coordinator, and the fold is
not it -- the fold only removes the collision for the subset of reads a command
happens to carry.

### What it put at risk: the write path of every device

The value a write leaves behind is now decided inside the connection, and the
caller is released at the acknowledgement rather than when the link closes. That
is every command, sealed or not, so:

```
python -m tools.regression --device puck
```

| | Baseline | This change |
|---|---|---|
| First command, median | 3.22 s | 1.69 s |
| Repeated command, median | 0.33 s | 0.48 s |
| The write itself, median | 35.8 ms | 35.8 ms |
| Delivered | 24/24 | 24/24 |
| Connected without a retry | 100 % | 100 % |

**No regression**, and the write itself to the tenth of a millisecond of the
baseline. Two earlier runs of this branch each lost 4 of their 24 commands and a
baseline run between them lost none, which is why `tools.regression` now prints
*why* a sample failed: a command the integration refused and a command whose
timing event never arrived were both just `FAILED`, and the difference is the
whole diagnosis. The next time it happens the output will say which.

### Still unmeasured  [HW]

§5.6's counter question folded into a command (D-129) needs a sealed device
offering the report, which means a board whose firmware has crypto:
`espruino/bench/many-writables.js` on the `COM15` nice!nano, or the Puck.js,
both of which are shared and in use. The procedure and the tool
(`tools/counter_question_cost.py`) are in §17.

---

## 19. One central at a time, and what enforcing it is worth

**2026-10-23, the `COM6` nice!nano, through Home Assistant on `hci0` alone.**
§18 found a collision while measuring something else: a command and the read
§3.2 calls for, each holding one of the host's two connection slots (D-003) and
both reaching for a device that serves one central. D-131 gives every device its
own turn -- one lock per coordinator, taken before the host slot and never after
it -- and this is the same nine-sample harness again, three arms.

| Nine samples each | command, median | command, worst | the knob's value within 20 s |
|---|---|---|---|
| Before: no fold, no lock | 5.9 s | 17.2 s | 4 of 9 |
| The fold alone (D-130) | 2.8 s | 33.6 s | 8 of 9 |
| The fold and the lock (D-131) | 3.1 s | **6.6 s** | **9 of 9** |

```
python -m tools.espruino_upload --port COM6 --eval "bench.reset()"
# a command, then bench.knob() 0.2 s later, then bench.conns()
```

**The worst case is the result.** Four of nine commands took 13 s or more in
each of the first two arms; none did in the third, where the slowest was 6.6 s.
That is the collision closing: the read now waits for the device instead of
reaching for it, and nothing retries against a link somebody else holds.

**The median barely moves, and that is the trade, stated honestly.** 2.8 s
becomes 3.1 s, because a command that would have collided now queues behind a
read that is already connected. The delay was always being paid -- as retries,
as a 33 s command and as a lost read -- and it is now paid visibly, in
`queued_ms`, which is what the owner asked for when he said that queueing is
cheaper than failing.

**And every knob movement arrives.** Nine of nine, against four of nine before
either change. On a device that reports its own state, a local change that never
reaches the receiver is the one failure §3.2 exists to prevent, and it was
happening on more than half of them.

Three caveats, because nine samples are nine samples. The arms were taken over
about an hour on an unchanged bench, in this order, so a drift in radio
conditions would show up as a difference between them; the 20 s window decides
what counts as delivered, and one sample in the first arm arrived just outside
it; and the harness is a scratchpad script rather than a tool in `tools/`,
because what it drives -- a board on a USB console -- is not something a
measurement tool here otherwise does.

---

## 20. Two devices at once, and the wait that was not being reported

**2026-10-23, the two nice!nanos, both on USB power, through Home Assistant with
the proxy disabled as every campaign here has it.** `COM6` takes a command on a
switch; `COM15` takes one on a text entry. Different devices, so the lock of
D-131 does not apply between them and the only thing that can make one wait for
the other is the host cap of D-003, moved for this run through the options form
of D-132.

**What this found first was the instrument.** At a cap of one, with the two
commands issued at the same instant, `queued_ms` reported **2 ms** while one of
the commands plainly waited: its service call took 15 s against the other's 9 s.
`connect_started` was being taken before the gate, so every wait for a device's
turn or for a host slot was being counted as time spent connecting. The claim
made when D-131 shipped, that the delay is paid visibly in `queued_ms`, was not
true as implemented. The boundary now sits inside the gate (D-133), and the same
measurement says so:

| Cap of 1, four repetitions | `queued_ms` median | `connect_ms` median | `total_ms` median |
|---|---|---|---|
| the fast device (`COM6`) | 2.8 ms | 323 ms | 421 ms |
| the slow device (`COM15`) | **3673 ms** | 357 ms | 3991 ms |

| Cap of 2, four repetitions | `queued_ms` median | `connect_ms` median | `total_ms` median |
|---|---|---|---|
| the fast device (`COM6`) | 2.3 ms | 402 ms | 446 ms |
| the slow device (`COM15`) | 4.2 ms | 381 ms | 443 ms |

Before the fix the same cap of one reported 2 ms of queueing and 4307 ms of
connecting on that device; after it, 3673 ms of queueing and 357 ms of
connecting. The connection was never the slow part. One device was waiting for
the other, which is what a cap of one means and is now what the event says.

**Every command arrived, 8 of 8 in each arm.** Taken from Home Assistant's own
history rather than from the event stream: eight alternations of the switch and
`cap 1` through `cap 4` twice on the text entry. Three of the sixteen timing
events were missed by the harness, whose collection window closed two seconds
after the first of a pair -- which a cap of one is precisely designed to exceed.
The delivery figure is the history's, not the harness's.

**And one sample worth keeping.** At a cap of two, one command still queued for
2528 ms. Four writable devices are configured on this bench, and nothing
prioritises a command over a background state read: two reads can hold both
slots while a user is waiting. That is the next item on D-003's list, and this is
the first measurement of it costing anything.

**What is still unmeasured:** the exhaustion itself. Three devices and a
three-slot proxy cannot fill the host, so D-133's hold-off and its message are
covered by tests and by reading `bleak_retry_connector`, not by hardware.

## 21. The counter question, measured against a sealed device

**2026-10-24, the nice!nano lamp `F5:A8:93:67:CB:25`, through Home Assistant on
`hci0` and one proxy.** §17 set out what the fold of D-129 should be worth and
could not measure it: no board on this bench had a firmware with `crypto`, so no
device was ever asked for a counter. The board was reflashed today with
2v29.396, `MODULES` now lists `crypto`, and the seventeen shared CCM vectors run
on it agree with the contract. `espruino/bench/revision-lamp.js` is sealed with
the test-vector key, offers the counter report, and fits in 12 of its 12
available service-data bytes. The Home Assistant entry was given the same key
through Reconfigure.

**Thirteen samples per case per arm**, three then ten, `--arm folded` and
`--arm separate` with the deployed `FOLD_THE_COUNTER_QUESTION_INTO_A_WRITE`
switched between them and a restart and ten minutes of settling in between.

| | Folded | Separate | Folded minus separate |
|---|---|---|---|
| *immediate*, median wall | **10.12 s** (8.45 to 18.36) | **13.02 s** (10.58 to 19.56) | **-2.90 s** |
| *settled*, median wall | **7.64 s** (4.66 to 15.94) | **4.19 s** (3.08 to 7.94) | **+3.45 s** |

**The first row is what the change was for, and it holds.** Broken into phases,
the fold removes 5.0 s of queueing (median 4254 ms against 9230 ms): the command
no longer waits behind a connection made for the question. It pays 1.76 s back
inside its own connection, and keeps the difference.

**The second row was predicted to be equal within the spread, and it is not.**
§17 expected the fold's `counter_ms` to be tens of milliseconds against a
connection of seconds. It is 715 ms, and it is not the whole cost:

| Phase, *settled* median | Folded | Separate |
|---|---|---|
| queued | 1 ms | 1 ms |
| connect | 3196 ms | 1287 ms |
| counter exchange | 715 ms | 0 ms |
| write | 797 ms | 42 ms |
| confirm | 402 ms | 671 ms |

**Two things in that table are worth more than the totals.**

*The write costs 42 ms on a link that carries nothing else and about 800 ms when
it carries the question.* Twenty times, for an exchange that is already counted
in its own column. The folded values are quantised: 797, 997, 1197, in steps of
almost exactly 200 ms, where the separate arm's are 40 to 42 ms every time. A
write does not become slower because a read preceded it on the same link, so
this is a wait on something periodic, and 200 ms is the shape of a connection
interval rather than of arithmetic. It is the one number here that looks like a
defect rather than a cost.

*The separate arm's connect is 1.9 s faster, and that is an artifact of the
comparison rather than a merit of the arm.* In the separate arm a connection was
made for the question 40 s earlier, which leaves the path warm: a cached GATT
table, a known route through the adapter or the proxy. In the folded arm nothing
has connected since the reload, so the command pays for a cold path. Against an
unsealed device, where no question is ever asked, the settled command would be
cold in both arms. So **the fold's own cost in the settled case is the counter
exchange plus the write inflation, about 1.5 s, not the 3.45 s the wall times
show.**

**No write was refused in any of the twenty-six folded samples.** That was the
one thing this change could get wrong: the counter has to be drawn after the
adoption, not before, or the write goes out behind what the device has already
accepted and is refused in silence (§4.2). It is drawn in the right order.

### Where the 200 ms comes from, and it is not the fold

Looked at per sample rather than per median, the quantisation is not confined to
the write. **Every phase after the counter exchange is a multiple of about
199 ms**, and the read-back is the clearest case: `confirm_ms` is 401.8 ms in 18
of the 26 folded samples and 601.7 ms in 5 more, which is two units and three.
The write is 2, 4, 5 or 6 of the same unit.

**In the separate arm nothing is quantised at all.** The write is 40 to 42 ms in
25 of 26 samples, and the read-back after it is spread continuously from 55 ms to
1201 ms. Same board, same firmware, same deployed code, one constant apart.

What separates the two is not the fold but *when in the connection the write
happens*. In the separate arm the write is the first ATT operation on the link,
about 40 ms after it comes up. In the folded arm the counter exchange goes first,
so the write starts 520 to 1360 ms in. Sorted by `counter_ms`, the one folded
sample whose exchange was quick (98 ms) is also the only one whose write is not a
clean multiple: 371.8 ms. Everything above 500 ms is on the grid.

So **a connection changes regime about half a second in**, and whatever runs then
pays an integer number of 199 ms intervals. That is a connection interval, and it
is nobody's arithmetic here: the integration has exactly one `asyncio.sleep` and
it is the slot cooldown; the module's own constants are 100 ms of read slack,
250 ms of change hold and a 100 ms fast advertising interval; and this sketch
does not pin the console, so it is not §8's `E.setConsole("USB")` artifact
either.

**§8 saw this a week ago from the other side.** With the console pinned to USB, a
hundred writes over the air took 400 ms each instead of 15, and that section
called it a lead worth following for a receiver that writes several entries in
one connection. This is that lead arriving in production: it is not about the
console, and it is not about encryption. **Any second operation late in a
connection pays it**, which includes D-130's folded read on a device that has
moved its revision.

**What this costs the fold, properly attributed.** Of the 1.5 s the fold seemed
to add in the settled case, about 750 ms is this regime, which a command pays for
being late in its own connection rather than for carrying a question. The fold's
own cost is the counter exchange, 715 ms.

**The experiment, run the same night, and it half answers.** Twelve ATT reads
inside one connection, from this Windows host rather than through Home Assistant,
reading GAP Device Name (0x2A00), which the SoftDevice answers without waking
JavaScript. Two passes per board: reads from the first moment, and reads after
1.5 s of silence.

| | Reads from the first moment | Reads after 1.5 s of silence |
|---|---|---|
| Puck.js, battery, in clear | 15 to 31 ms | 15 to 31 ms |
| the lamp, first run | 15 to 16 ms | **500, then 390 to 407 ms, all twelve** |
| the lamp, six runs after | 16 to 63 ms | 15 to 47 ms |

**So the step does not follow the operation index.** Twelve reads back to back
stay at 15 ms; the slow pass was slow from its *first* read and stayed slow for
all twelve, 6 s of link. A regime a connection is in, then, not a cost that
accumulates: a link that comes up fast stays fast, and one that comes up slow
never recovers. That is the shape of connection parameters, and ~400 ms is two of
the ~199 ms unit.

**And it is not plain silence either**, which is the honest part of this result.
A sweep of seven delays from 0 to 2 s on the same board, minutes later, found
nothing slower than 47 ms, and alternating SoftDevice-served and
JavaScript-served reads in one connection found nothing slower than 63 ms. The
slow regime was seen once, whole and unmistakable, and could not be summoned
again from this host.

**Which points at the central rather than at the device.** This host's adapter
keeps a link fast whatever the age of the connection; the figures in the tables
above were produced by Home Assistant on the Pi's `hci0`, whose connection
parameters are its own and are not reproducible from here. The production data is
the stronger evidence, because it is near deterministic: 25 of 26 folded writes
on the grid, 25 of 26 separate writes at 40 to 42 ms, and the separate arm's
read-back, which lands in between at 55 to 1201 ms, continuous, exactly where a
transition would put it.

**So the remaining question is one measurement on the Home Assistant side**: the
live link's connection interval, from `btmon` on the host or from a proxy's log,
at 40 ms into a connection and again at 1 s. That needs a shell on HAOS, which
this session does not have.

**One correction this experiment forced**, worth more than it looks: *this host
can* open a GATT connection to the nice!nano lamp, which `docs/shared-bench.md`
said it could not. It needs an active scan and up to 45 s of it, because the
board advertises an unchanging sealed payload and Windows coalesces duplicates.
Measurements that do not need Home Assistant in the loop can therefore be made
from here, with this host's connection parameters rather than the Pi's, which is
both the opportunity and the catch.

### The 199 ms unit is the connection interval, and the device sets it

**2026-10-25, from the Espruino source and then from the bench.**
`jswrap_ble_setConnectionInterval` in `libs/bluetooth/jswrap_bluetooth.c` names
the number in its own documentation comment:

> By default, when connected as a peripheral Espruino automatically adjusts the
> connection interval. When connected it's as fast as possible (7.5ms) but when
> idle for over a minute it drops to 200ms. On continued activity (>1 BLE
> operation) the interval is raised to 7.5ms again.

**200 ms is the unit measured here at 199.4, and §22 proves it by removing it**:
with `NRF.setConnectionInterval(7.5)` on the device and nothing else changed,
every phase of the same command falls off the grid and the command itself takes
2.2 s less. So the attribution two paragraphs above, *"which points at the
central rather than at the device"*, is **wrong**: the interval belongs to the
peripheral, and this host's inability to summon the slow regime was never
evidence about where it came from.

**What does not hold is the idle part of the sentence.** The obvious reading,
that a device left alone for over a minute is found slow and a device just
connected to is found fast, predicts that two commands differing only in that
would differ. They do not: §22 ran both, 130 s of quiet against seconds after the
previous connection, and the grid is identical in each. What decides is *where in
the connection the operation falls*, exactly as this section measured before
knowing why: the first ATT operation is served at 37 to 42 ms, and everything
from about half a second in pays whole intervals. A plain command with no counter
exchange still writes in 38 ms today, on a lamp nobody had touched for a day.

So the link comes up at the interval the central asked for, @enaon's `hci0` log
showing 6 units of 1.25 ms, and the peripheral's own 200 ms arrives a few
hundred milliseconds later, after which nothing in these short connections
raises it again. Why activity does not is the open question, and it is a firmware
question for @gfwilliams rather than a bench one.

**§8 saw this a week ago from the other side.** With the console pinned to USB, a
hundred writes over the air took 400 ms each instead of 15, and that section
called it a lead worth following for a receiver that writes several entries in
one connection. This is that lead, arriving in production and now explained: it
is not about the console, and it is not about encryption. Any operation late in a
connection pays it, D-130's folded read included.

**What this costs the fold, properly attributed.** Of the 1.5 s the fold seemed
to add in the settled case, about 750 ms is this regime, which a command pays for
being late in its own connection rather than for carrying a question. The fold's
own cost is the counter exchange, and §22 measures that at 116 ms once the
interval is pinned, which is the order §17 predicted.

Samples in `docs/data/counter-question-folded.json`,
`counter-question-separate.json` and the same two names with `-n10`.

```
python -m tools.bench_lock acquire --note "D-129 sealed A/B"
# set BINDKEY in espruino/bench/revision-lamp.js, then
python -m tools.build_espruino_bundle
python -m tools.espruino_upload --port COM6 espruino/dist/revision-lamp-standalone.min.js
# then Reconfigure the entry with the same key, and
.venv-ha/Scripts/python.exe -m tools.counter_question_cost --device lamp --arm folded --reps 10
```

---

## Reproducing any of this

Most of the tools above take `--address`; `tools.regression` and
`tools.latency_sweep_write` take `--device` instead, naming a board from
`tools/devices.py`. Every one
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

## 22. Pinning the connection interval, and what that is worth

**2026-10-25, the sealed lamp `F5:A8:93:67:CB:25` through Home Assistant**, the
same board, bindkey, deployed integration and radio as §21, with the fold on.
Each sample moves the device's own dimmer with `bench.knob()` over the USB
console, waits 4 s for the moved settings revision to reach Home Assistant in an
advertisement, then commands the switch: that is the shape of @enaon's report, a
local change followed by a command, and it is the only shape that owes the
counter question of §5.6. Two arms, one variable:

* **auto** -- the device exactly as deployed, Espruino adjusting the interval
  itself;
* **pinned** -- `NRF.setConnectionInterval(7.5)` sent once over the console
  before the run. No code change, no reflash, no change to the integration.

Twelve samples per arm, alternating *cold*, after 130 s of quiet, and *warm*,
seconds after the previous command's connection.

| Median of 12 | auto | pinned at 7.5 ms | ratio |
|---|---|---|---|
| wall | **5.2 s** (4.6 to 7.0) | **3.0 s** (2.9 to 5.8) | **-2.2 s** |
| counter exchange | 952.6 ms (681 to 1151) | **115.7 ms** (100 to 130) | 8x |
| write | 797.5 ms (797 to 997) | **87.8 ms** (73 to 121) | 9x |
| read back | 401.6 ms (391 to 402) | **26.2 ms** (17 to 106) | 15x |
| connect | 324.5 ms (197 to 986) | 332.3 ms (183 to 919) | unchanged |

**The grid is gone, not reduced.** In the auto arm the write is 4.00 to 5.01
units of 199 ms in 12 samples of 12, and the read back is 2.02 units in 11 of
12. In the pinned arm nothing is a multiple of anything: 73.3, 75.8, 84.3, 87.7,
87.8, 98.2, 98.7, 99.4, 119.3, 120.9. That the connect time is the same in both
arms is the control: pinning the interval does not make the link easier to
establish, it makes operations on an established link cheap.

**Cold and warm are the same, which refutes half of the hypothesis.** The
firmware comment says the drop to 200 ms follows a minute of idle, so a command
after 130 s of quiet and one issued seconds after the previous connection should
differ. They do not, in either arm:

| auto, write | cold | warm |
|---|---|---|
| the four pairs | 797.6, 797.3, 796.8, 797.2 | 797.2, 994.0, 807.5, 796.9 |

So the device is in the slow regime whenever its own adjustment is in charge,
whatever happened a minute earlier, and the thing to fix is not when it goes
slow but that it does.

**One failure in 11 delivered commands, pinned**, *"Light could not be reached:
the command was not delivered. [org.bluez.Error.Failed] Not connected"*, against
none in 12 on auto. Eleven samples cannot tell a 9% failure rate from bad luck,
and a 7.5 ms interval does leave less room for a retransmission inside the same
supervision timeout, so this is the one thing a longer run has to settle before
the interval is pinned anywhere but on a bench.

**What it would be worth to a user.** Every command this project makes pays the
grid: 2.2 s of the 5.2 s measured here, on a device whose radio is otherwise
idle. That is larger than everything 0.2.0 changed put together, and it is one
line on the device rather than anything in Home Assistant. D-141 is the decision
it asks for, including the power question, which is the only argument against it
and is not answerable here.

**@enaon got there first, and his figures are the independent half of this.**
In espruino#8024 on the same day, before this run, he set
`NRF.setConnectionInterval(7.5)` on his own board, first in a connect handler and
then noting that once is enough, and posted both arms (`counter_ms` /
`write_ms` / `confirm_ms`):

| @enaon, `eT-Black-4` | default | pinned at 7.5 ms |
|---|---|---|
| a write with no prior `changed()` | 0 / 610.5 / 1202 | 0 / **53.6** / **47.3** |
| a write after a button press | 1314.1 / 405.3 / 614.3 | **106.2** / **50.2** / **17.2** |

His counter exchange pinned is 106.2 ms against our 115.7, his read back 17.2
against our 26.2. Two boards, two benches, two radios, the same result, and the
finding is his.

**He is also right that setting it once is enough**, which simplifies D-141: the
interval only exists while a central is connected, so a pinned value costs
nothing between connections and the connect and disconnect handlers buy nothing
for a device that is only connected to while a command is in flight. They are
worth having only where something keeps a link open, a Web IDE session or an
Espruino Hub, which is also the only case where the power question has teeth.

### A hundred commands per arm

**The same evening, 100 samples per arm rather than 12**, because a failure in
eleven commands decides nothing and it was the one thing standing between this
and a module default. Same shape, same board, `bench.knob()` before every
command, the arms separated by one console statement.

| 100 commands each | auto | pinned at 7.5 ms |
|---|---|---|
| delivered | **100 of 100** | **100 of 100** |
| command, median | 4.95 s | **2.98 s** |
| command, 90th centile | 5.31 s | **3.00 s** |
| over 4 s | 99 of 100 | **3 of 100** |
| counter exchange, median | 885.9 ms | **115.2 ms** |
| write, median | 797.4 ms | **94.1 ms** |
| read back, median | 401.7 ms | **27.4 ms** |
| write a whole number of 199.4 ms | 97 of 100 | **0 of 100** |

**Nothing failed in either arm.** The one failure of the twelve-sample run was
bad luck, and 200 commands say the fast interval is not less reliable on this
bench. The pinned arm is also far tighter: its median and its 90th centile are
30 ms apart, against 360 ms in the default arm, which is what removing a
quantised wait from four phases of the same command does.

**One sample in the pinned arm took 23 s**, of which 20.5 s was spent opening
the link, and it is the only sample in either arm whose connect exceeded 2 s.
That is not the interval's doing: a connection interval governs operations on an
established link, the default arm's connect median is the same 330 ms, and
`bleak_retry_connector` is the thing that spends twenty seconds. It is the
ordinary tail this bench has always had.

**So the only open question left in D-141 is power**, and the owner is
measuring it himself on an Otii Arc Pro: §23 is the procedure, D-142 is why it
also goes on the module page.

Samples in `docs/data/connection-interval-auto.json`,
`connection-interval-pinned.json` and the hundred-sample pair,
`connection-interval-100-auto.json` and `connection-interval-100-pinned.json`; the script is `interval_knob.py` in the
session scratchpad, a measurement technique rather than something to ship, like
the three of §8.

```
python -m tools.bench_lock acquire --note "D-141: pin the connection interval"
python interval_knob.py --reps 2 --quiet 130              # auto
python interval_knob.py --reps 2 --quiet 130 --pin 7.5    # pinned
python interval_knob.py --reps 1 --quiet 10  --pin auto   # and put it back
```

## 23. What the module costs in current, and the procedure to measure it  [HW]

**Nothing in this file is a current measurement of this module on this bench.**
Every microamp quoted above is @enaon's PPK2 on his own nice!nano, at a 1 s
advertising interval, measuring a *difference*: ~235 uA before the rebuild fix
and ~50 uA after, against ~45 uA with the module not loaded at all (§8); and the
bound that everything P1 could recover is inside 5 uA (§9). Those are the right
numbers for the questions they were asked, and they are the wrong numbers for
the question an adopter asks, which is *what will this do to my battery*. That
question wants absolutes, on both boards, at the interval the module actually
ships with.

**So current becomes a characterised quantity, and it goes on the module page
as a reference table** (D-142): sealed, the advertising interval against the
write rate, so that an adopter reads their own case out of it rather than ours.
The owner has the instrument and the two boards; this section is the procedure,
the arithmetic that turns three measured coefficients into the whole table, and
what each number should come out at, so that a rig which is wrong shows up as
wrong rather than as a surprising result.

### The rig

| | |
|---|---|
| **Instrument** | an **Otii Arc Pro** (Qoitech), the owner's: a source measure unit that supplies the board and measures what it draws, nanoamps to 5 A at 5 nA resolution, **current at up to 4 ksps** and one of its two digital inputs on the marker pin. Three numbers in its datasheet shape what the rig can see, and all three are fine for this measurement: 4 ksps is the main current channel **in the 19 mA range only** (above it the Arc auto-ranges and drops to 1 ksps, so keep the peak under 19 mA, which a Puck's 6 mA transmit does); every other channel including **GPI1 is 1 ksps**, so a marker edge is placed to a millisecond; and the current channel's analog bandwidth is **400 Hz**, so it integrates honestly and shows no peaks |
| **Puck.js** `C8:80:32:AD:F7:B9` | cell **out of the holder**, the Arc feeding 3.0 V into the 3V and GND pads. A coin cell cannot be measured in series without becoming the thing measured, and 3.0 V is inside the Arc's high-accuracy range on USB power alone |
| **nice!nano** `E0:A4:BA:16:54:89` (lamp3) | USB **unplugged**, the Arc feeding 3.7 V into the battery pads, so the figure includes the board's charger and regulator -- which is what a real device pays. 3.7 V is above the 3.75 V ceiling of the Arc's high-accuracy range on USB power, so this arm wants the **7-9 V DC adapter**. Not lamp `F5:A8:93:67:CB:25`: that one is in the §17 and §21 campaigns and should stay on its cable |
| **Sketch** | `espruino/bench/power-arms.js`, four constants selecting the arm, loaded **over the radio** from the Web IDE so that nothing is on the cable and nothing is written to flash |
| **Marker** | D1 on either board to **GPI1** on the Arc's expansion port. GPI1 is enabled in the project's Voltage tab and its logic threshold is set in the Supply tab, so tell it 3.0 V or 3.3 V to match the board. The sketch holds the pin high for exactly the connection a command runs in, and for exactly the rebuild `bench.rebuild()` forces |
| **Analysis** | `python -m tools.power_charge trace.csv --digital GPI1 --baseline auto`, which integrates each marked window into microcoulombs above the advertising floor. The Arc's own app computes a mean and a charge over a selection; the tool is for the figure arriving the same way twice and as JSON next to the others, not because the app cannot |

**One board at a time**, which the owner's rig imposes and which costs two
things worth planning around. Arm A, the floor, has to be measured in the same
sitting as the arms it is the floor for: a board swapped onto the meter is a new
rig, and a floor from last week is not a floor. And the two boards are two
sittings, so nothing in the table below is a Puck-against-nano comparison made
under one setup.

**The export format is not pinned here.** Qoitech's manual pages for the CSV
export are not reachable from this bench, so `tools/power_charge.py` sniffs
instead of assuming: it reads each column's unit from the column's own header
(seconds or milliseconds, amperes or microamps), takes the marker channel from a
second file when the app exports one file per channel (`--digital-csv`, aligned
by timestamp rather than by row), and treats a channel exported as a voltage as
high above a threshold. One ten-second export with GPI1 enabled pins the shape
for good; if its time column does not name its unit the tool says so and
`--time-unit s` settles it.

**Take the lock and put the boards back.** A connection is a write
(`docs/shared-bench.md`), the arms below connect, and the lamp entity is left
off at the end like every other run.

### The measurement, and it is lighter than it looks

**The owner's shape, 2026-10-25: sealed throughout, the advertising interval
swept from 200 ms to 10 s, the write rate swept from 1 to 6 a minute, and the
result a reference table anybody can read their own case out of.** That is the
right deliverable, and it does not want 49 recordings, because the terms add up:

```
I(T, n) = floor + (1 - f) * Qadv / T + f * Qadv / Tfast + n * Qcmd / 60
f = min(1, n * fastTimeout / 60)
```

`T` is the idle advertising interval in seconds, `n` the commands a minute,
`Qadv` the charge of one advertising event, `Qcmd` the charge of one command's
connection above the floor, and `f` the share of the minute spent in the fast
window, which each command opens for `fastTimeout` seconds at `fastInterval`. A
device that also advertises a value that moves adds `r * Qrebuild / 60`, which
is the only term the protocol itself does not set.

So **three coefficients, measured once, give every cell**, and the sweep gives
two of them at a stroke: plot the mean current of each step against 1/T and the
floor is the intercept, one advertising event the slope.

| recording | what it is | how long |
|---|---|---|
| **1. the sweep** | `SWEEP = [200, 500, 1000, 2000, 3200, 5000, 10000, 100]` in `power-arms.js`, `SWEEP_MS = 120000`: the device walks the intervals on its own. No central, no reload, one recording, and no marker channel either -- the steps are read out of the advertising rate in the current itself (`power_charge --segment`), which also checks each step against the interval that was programmed. 100 ms is in it because that is `fastInterval`, so the fast term is measured rather than extrapolated, and it is **last** because it is the one step that touches a code path the others do not | **17 min** |
| **2. the commands** | 10 commands from Home Assistant, **45 s apart** because `fastTimeout` is 30 s and a command sent sooner is measured inside the fast window rather than from idle. The marker is high over each connection, and the median excess above the floor is `Qcmd` | **8 min** |
| **3. the same, pinned** | recording 2 with `CONNECTION_INTERVAL = 7.5`, which is what puts D-141's cost in the same table as everything else | **8 min** |
| **4. two checks** | 10 min at 2000 ms with 1 command a minute, then 5 min at 2000 ms with 4 a minute, on the **automatic** image, which is the arm the table is built from. Compare each span's mean against what the table says it should be. It found a 14% error in the model at the second cell | **18 min** |

**Call it 45 minutes a board**, and the second board is the same 45 minutes. The
checks are not optional: a table computed from three coefficients and verified
nowhere is a table that should not go on anybody's documentation page. Two cells
are enough, one each side of the saturation below.

**Why 120 s a step is enough**, when §23 used to ask for a hundred advertising
events: the short intervals get them anyway, 1200 at 100 ms, and at the long end
the advertising term is a microamp or two of which the event count is a few per
cent, while the thing that step is really measuring is the intercept -- the
floor, which is a DC level and needs no events at all.

**The analysis is two commands.** The sweep's steps are the stretches *between*
marker pulses, which is what `--gaps` reads:

```
python -m tools.power_charge sweep.csv --digital GPI1 --gaps \
    --labels "-,100,200,500,1000,2000,3200,5000,10000" \
    --out power-puck-sweep.json
python -m tools.power_charge Enregistrement_4 --phases --commands \
    --baseline auto --capacity-mah 220 --out power-puck-checks.json
python -m tools.power_charge Enregistrement_4 --window 101500-701500 \
    --window 775400-1075400 --labels "1 a minute,4 a minute" --baseline 0
python -m tools.power_table --fit power-puck-sweep.json --command-charge 1810 \
    --command-seconds 2.34 --life --capacity-mah 220
```

**Nine labels for eight steps**, because the quiet before the first marker
pulse is a gap like any other: it is the minute the sketch spends at
`ADV_INTERVAL` while the console lets go and the fast window its disconnect
opened expires. `-` is the label that drops it, and a mismatch between labels
and windows is reported rather than silently shifting every step by one.

The fit prints its own worst residual, which is the first thing to look at: a
model that does not fit the sweep it came from has no business predicting a
cell that was never recorded.

### The order, and the three things that spoil a trace

**The Puck first, then the nice!nano.** 3.0 V is inside the Arc's
high-accuracy range on USB power alone, so the first sitting needs no DC
adapter; a CR2032 is the battery the question is actually about; and the Puck's
column goes first on the module page, so it is the one worth measuring while the
rig is new and every doubt is still being checked.

**Step 0, before any current: ask each board what it is.** `process.env.VERSION`
and `process.env.MODULES` over the console. Everything here is sealed, so
`crypto` has to be in that list -- the nice!nano `CD:F5:77:3A:B2:16` has `AES`
but not `AES_CCM` (§8), lamp `F5:A8:93:67:CB:25` was reflashed with `crypto` on
2026-10-24, and lamp3's firmware has never been looked at. A board without it
cannot produce a single row of this table.

Then the three things that quietly ruin a recording:

1. **Discard the first minute.** Loading the sketch is a connection, its
   disconnect opens a 30 s fast window, and `setup()` builds a packet. That is
   why `SWEEP_START_MS` is 60 s: disconnect the Web IDE as soon as the sketch is
   in, and the sweep starts clean.
2. **Leave the device alone during the sweep.** Home Assistant connects when the
   settings revision moves, so no `bench.knob()` and no entity touched: a
   connection in the middle of a step puts a command's charge into an
   advertising figure.
3. **Take the lock.** `python -m tools.bench_lock acquire --note "D-142: current"`,
   because the command recordings drive Home Assistant and another agent's run
   would land inside a trace.

### What the first run gave, including the two things it was not looking for

**2026-10-26, Puck.js f7b9 at 3.0 V on the Arc, sealed, boot from `.bootcde`,
18 minutes at 4 ksps.** The sweep itself failed: the device advertised at
104.5 ms for 1020 seconds while believing it had changed rate eight times,
because the first step set 100 ms, which is the module's own fast interval, and
`setAdvertisingInterval` guarded its republish on the rate differing from the
*fast* interval rather than from the one being asked for. Once the two were
equal the test was false for good. That is a module bug, it is fixed and has a
regression test, and 100 ms now goes **last** in the sweep so that the next
peculiarity at that step costs seven steps less.

What the trace gives anyway, read out of the idle minute and the long stretch:

| | measured |
|---|---|
| floor between everything | **4.34 uA** (median of 4.3 million samples) |
| one sealed advertising event, 9 bytes of service data | 5.5 to 6.75 ms, peak 4.5 to 5.6 mA, **14.6 to 21.1 uC** |
| the two-interval solve, 2003 ms against 104.5 ms | **Qadv 14.8 uC, floor 7.0 uA** |
| the device at its 2 s default | **14.4 uA**, which is 637 days of a 220 mAh cell |
| power-up | 1.41 s and **8.6 mC**, peaking at 138 mA |

**And a 7.2 uC event every 8.000 seconds that is not the radio.** Seventeen
milliseconds long, peaking at 780 uA where an advertising event peaks at 5 mA:
too slow and too weak to be a transmission, and exactly periodic. That is the
SoftDevice recalibrating the low-frequency RC oscillator, which a Puck.js needs
because it has no 32 kHz crystal. It costs **0.90 uA continuously**, which is a
fifth of the floor and a seventh of what the device spends advertising at 2 s,
and no datasheet figure or model in this file predicted it. It is also why the
fitted floor comes out at 7.0 uA against a 4.34 uA median: the floor is the
median plus the calibration plus the part of every event that falls under the
detection margin.

The power-up figure is worth keeping for a different question: a device that
sleeps and reboots rather than advertising slowly pays 8.6 mC a cycle, which is
the advertising of nine minutes at 2 s.

### The sweep, measured

**2026-10-26, Puck.js f7b9 at 3.0 V, sealed, booting from `.bootcde`, no
central, 18.9 minutes at 4 ksps, the steps read out of the advertising rate
itself.** Every detected interval came back as the one that was programmed,
which is the check a marker channel would have given and better, because it is
a reading rather than a label.

| interval | duration | mean | peak |
|---|---|---|---|
| 100 ms | 221.2 s | **148.63 uA** | 5.6 mA |
| 200 ms | 120.0 s | **79.42 uA** | 5.6 mA |
| 500 ms | 119.6 s | **36.25 uA** | 5.6 mA |
| 1 s | 118.5 s | **21.88 uA** | 5.6 mA |
| 2 s | 116.3 s | **14.35 uA** | 5.6 mA |
| 2 s, again, before the sweep began | 58.0 s | **14.47 uA** | 5.6 mA |
| 3.2 s | 115.4 s | **11.46 uA** | 5.6 mA |
| 5 s | 115.0 s | **9.86 uA** | 5.5 mA |
| 10 s | 119.0 s | **8.20 uA** | 5.6 mA |

The two 2 s figures are 0.8% apart, measured nine minutes and six intervals
from each other, which is the repeatability of the whole rig in one line.

**The fit, on all nine points: a floor of 7.35 uA and 14.19 uC an advertising
event, worst residual 1.1 uA.** Over an eighteenfold range of interval and a
range of current from 8 to 149 uA, a two-term model is never more than a
microamp out, so the additive model of this section is not an approximation
worth worrying about. The residuals lean one way, positive at the short
intervals and negative at the long ones, by about half a microamp: there is a
little convexity the model does not carry, and it is smaller than the thing it
would explain.

**And the fast window is now measured rather than modelled.** The model says a
device in its fast window draws `floor + Qadv/fastInterval` = 7.35 + 141.9 =
**149.3 uA**; the 100 ms step measures **148.63 uA**. The term the whole
saturation claim rests on is confirmed to half a per cent by a step that was in
the sweep for exactly that reason.

### The commands, measured

**2026-10-26, same board and rig, `power-commands-storage.min.js` from
`.bootcde`, 2 s idle, `CONNECTION_INTERVAL = null`, ten commands driven from
Home Assistant 45 s apart through the ESPHome proxy `bureau`.** Nine of the ten
went out; the tenth never left, because the ninth service call took longer than
thirty seconds to answer and `tools.power_commands` treated the timeout as
fatal (it no longer does). The trace holds all nine, and `power_charge --phases`
found every one of them without a marker channel.

A command is three things in the current, in this order:

| | per command |
|---|---|
| **a solid block of radio**, no gaps in it at all | **0.19 s at 3.9 mA**, 730 uC |
| **the link, at 7.5 ms** | 1.09 to 2.97 s at 0.58 to 0.82 mA |
| **the two together, above idle** | 1330 to 2725 uC, **median 1810 uC** |
| **the fast window after it** | **29.93 to 30.00 s** at 147.0 to 149.9 uA |
| its charge above idle | 3979 to 4063 uC, **median 4017 uC** |
| **one command, all in** | **5827 uC**, of which the fast window is **69%** |

The first three commands cost 2356 to 2725 uC against 1330 to 1819 for the rest:
service discovery, paid once per Home Assistant restart rather than per command,
which is why the table below takes the median of the nine and not the mean.

**`fastTimeout` and `fastInterval` are no longer assumptions.** Nine
independent measurements of the fast window give 29.93 to 30.00 s against a
30 s setting, at 104 to 105 ms against a 100 ms one, and its mean current
matches the sweep's own 100 ms step to under two per cent across two separate
recordings. The term the saturation claim rests on is measured three ways now.

**And the connection ran at 7.5 ms with nothing asking it to.** The sketch had
`CONNECTION_INTERVAL = null`, which leaves the interval to be negotiated, and
every one of the nine connections came out at **7.5 ms** -- the minimum the
specification allows. **That bears directly on D-141**, whose option 1 is to
pin 7.5 ms in `setup()`: through an ESPHome proxy there is nothing left to pin,
because the link is already there. Pinning would still matter for a central
that negotiates something slower, so what the measurement settles is that the
option is free of cost here rather than that it is worthless: recording 3, the
pinned arm, should come out indistinguishable from this one, and if it does
then D-141 needs no guard for this path.

**A connection is 1.9 s long for one write**, which is the other thing worth
staring at: 250 connection events at 7.5 ms to deliver one object. What they
are doing is Home Assistant's business rather than the device's, but the device
pays for it, and 1.8 of the 5.8 mC a command costs is that link being held
open.

### The blind spot this found, which is the method and not the device

The first reading of this trace gave 1078 uC a command and the check cell came
out **15% light**: 123.66 uA predicted against 142.64 measured. The missing
7225 uC were in nine stretches of 0.19 s at 3.9 mA, one per command.

**A phase is a run of gaps between radio events, which makes the reader blind
to exactly one thing: radio that never stops.** A continuous block is a single
event with no gaps in it, so it belongs to no run and was dropped without a
word -- and it was 40% of what a command costs. `phases()` now examines the
stretches between its own runs and returns any that carries current as a phase
of its own, and `power_charge --phases` **prints the share of the recording's
charge its phases account for**: 100.0% for this trace. A blind spot now
announces itself in the output rather than as a model that does not fit.

That is the third time in one day that a threshold or a window taken from the
shape of the data rather than from what the hardware does has cost a
measurement, and it is the one worth writing down: **the analysis has to
account for all of the charge, and say so.**

### The pinned connection interval, measured against it

**2026-10-26, same board and rig, `power-commands-pinned-storage.min.js` from `.bootcde`, one line different: `NRF.setConnectionInterval(7.5)`.** Ten commands 45 s apart, **ten of ten delivered**. The prediction in the section above was that this recording would be indistinguishable from the automatic one, because the link was already running at 7.5 ms with nothing asking it to. It is not, and the difference goes the other way from the one D-141 was worried about.

**Recording 4 is in this comparison and it has to be**, because it is the second automatic recording and it disagrees with the first. Medians, boot connections excluded, the two automatic recordings pooled as one arm of 39 commands:

| | automatic, 39 commands | pinned, 10 commands |
|---|---|---|
| the interval the link actually ran at | 7.5 ms | 7.5 ms |
| the opening burst of unbroken radio | 81.0 ms | 79.4 ms |
| **how long the link was held open** | **2.34 s** (1.09 to 2.97) | **1.96 s** (1.93 to 2.89) |
| **the whole connection above idle** | **1810 uC** (1330 to 2725) | **1422 uC** (1390 to 2277) |
| the fast window | 29.99 s at 148.3 to 152.7 uA | 29.99 s at 152.7 uA |

**Pinning does not cost charge, and it looks like it saves about a fifth of a command's connection.** 1422 uC against 1810, and the mechanism is the one §22 already measured as latency: the link is held open 0.38 s less. There is nothing in the fast window and nothing in the advertising, which is what D-141 needed to know -- the 27x it worried about never appears, because the central had already chosen 7.5 ms and there was no slower interval to lose.

**What this section claimed this morning about the opening burst was wrong, and recording 4 is what refuted it.** Against recording 2 alone, the pinned arm's burst of unbroken radio was 79 ms where the automatic arm's was 190, consistently across nine commands and three times the charge; the whole 388 uC looked like it lived there, and the connection parameter update procedure was the obvious explanation. Recording 4 then ran the **automatic** image and came back at 80 ms, like the pinned one. So 190 ms was recording 2's own, the burst is the same in both arms, and the saving is in the link duration instead. `CONNECTION_INTERVAL` was read back off the board as `null` after recording 4 to be sure of which image had run.

**Two things follow, and the second is the uncomfortable one.** The first is that a mechanism inferred from two recordings with one variable between them is not a mechanism: there was a second variable, unlabelled, somewhere between 11:29 and 12:54 on the Home Assistant side, and it moved a figure by a factor of two and a half. The second is that the arms are now separated by less than the automatic arm's own spread: 1330 to 2725 uC against 1390 to 2277. The medians differ by 21% and the ranges overlap almost completely, so **the right claim is that pinning is not expensive**, which is what the decision asked, and not that it saves 388 uC. The latency measurement of §22 is 100 commands an arm and it is the one that carries the direction.

**The floors say the same thing about how much to trust one recording.** 14.41 uA in recording 2 and 14.40 in recording 4, which is a reproducibility of 0.07% on an idle device two hours apart; 14.87 in recording 3, which is 3.2% above both. The pinned recording is the one with the anomalous floor, and nothing in the sketch can raise an idle device by three per cent. Supply was 3.000 V in all three.

**And the table's collapse was demonstrated by accident.** Two of the ten service calls took 20 and 23 s to return against 0.5 to 5.8 s for the other eight, and the trace says where the time went: the device advertised quietly at 2 s throughout, there is no failed connection attempt in front of either, and each command still produced exactly one connection. The delay was Home Assistant's and the device paid nothing for it -- but it arrived inside the fast window its predecessor was still spending, which truncated two windows to **25.64 and 20.81 s**. That is the mechanism the reference table predicts above two commands a minute, and it cost those commands 4293 and 5481 uC instead of 5551: **a command that arrives inside another's window is the cheap one**, because the window it would have opened was already being paid for.

### The reference table, measured, and both cells checked

Floor **7.35 uA**, one advertising event **14.19 uC**, one command's
connection **1810 uC** over **2.34 s**, `fastInterval` 100 ms and
`fastTimeout` 30 s as measured. The two command coefficients are the medians
of **39 commands** across recordings 2 and 4, both on the automatic
connection interval, which is the module as it ships.

| advertising interval | 0/min | 1/min | 2/min | 3/min | 4/min | 6/min |
|---|---|---|---|---|---|---|
| 200 ms | 78.3 | 141.2 | 198.6 | 223.2 | 247.8 | 297.1 |
| 500 ms | 35.7 | 121.6 | 198.6 | 223.2 | 247.8 | 297.1 |
| 1 s | 21.5 | 115.0 | 198.6 | 223.2 | 247.8 | 297.1 |
| 2 s | 14.4 | 111.8 | 198.6 | 223.2 | 247.8 | 297.1 |
| 3.2 s | 11.8 | 110.5 | 198.6 | 223.2 | 247.8 | 297.1 |
| 5 s | 10.2 | 109.8 | 198.6 | 223.2 | 247.8 | 297.1 |
| 10 s | 8.8 | 109.1 | 198.6 | 223.2 | 247.8 | 297.1 |

Microamps. In days of a 220 mAh CR2032:

| advertising interval | 0/min | 1/min | 2/min | 3/min | 4/min | 6/min |
|---|---|---|---|---|---|---|
| 200 ms | 117 | 65 | 46 | 41 | 37 | 31 |
| 500 ms | 256 | 75 | 46 | 41 | 37 | 31 |
| 1 s | 426 | 80 | 46 | 41 | 37 | 31 |
| **2 s** | **634** | **82** | **46** | 41 | 37 | 31 |
| 3.2 s | 777 | 83 | 46 | 41 | 37 | 31 |
| 5 s | 900 | 83 | 46 | 41 | 37 | 31 |
| 10 s | 1045 | 84 | 46 | 41 | 37 | 31 |

**Both cells are now measured rather than computed, and they bracket the table.** Recording 4 ran 10 commands a minute apart and then 20 commands fifteen seconds apart, on the same board at the same 2 s interval:

| cell | span | measured | the table | out by |
|---|---|---|---|---|
| **1 command a minute** | 600 s, 10 commands | **116.90 uA** | 111.8 | **4.4% low** |
| **4 commands a minute** | 300 s, 20 commands | **236.45 uA** | 247.8 | **4.8% high** |

**The two residues have opposite signs, and the reason is not the model.** A command's charge is mostly Home Assistant holding the link open, and it held it for **2.85 s** in the first cell against **2.25 s** in the second: 1970 uC a command against 1550, a 27% spread inside one recording. Given each cell its own measured connection, the model lands **2.2% under both**, with the same sign and the same size, which is the residue of a two-term model rather than of a coefficient. So the table's 5% is the spread of the central's behaviour, not arithmetic, and it is the honest accuracy to publish.

Recording 2 is a third cell of its own: nine commands over 422 s is 1.279 a
minute at 2 s, for which the table says **138.9 uA** and the recording
measures **142.64 uA**, which is **2.6%**.

**Three sentences come out of this table, and none of them is "a write is
expensive".**

1. **A device nobody writes to lives on its advertising interval alone**, and
   the range is wide: 117 days at 200 ms against 1045 at 10 s, with the module's
   2 s default at 634.
2. **One command a minute costs eight times what advertising does.** At 2 s it
   takes the device from 634 days to 82, and two thirds of that is not the
   write: it is the thirty seconds of fast advertising the write leaves behind.
3. **From two commands a minute the advertising interval stops mattering
   entirely.** Every row collapses: 46 days whether the device advertises at
   200 ms or at 10 s, because the fast window never closes. The only lever left
   is `fastTimeout`, and nobody has said so before.

The first column and the last are what a reader should compare: **1045 days
against 31**, both of them this same device, differing only in how often it
is asked to do something and how long it stays alert afterwards.

### The model was 14% out at four commands a minute, and the check caught it

The first version of this table said **270.0 uA** at four commands a minute
where recording 4 measures **236.45**. That is the one cell whose value
carries the third sentence above, and it was wrong for a reason worth
writing down.

**A connection is not a fast window, and the model billed the same seconds twice.** `I = floor + (1-f) Qadv/T + f Qadv/Tfast + n Qcmd/60` charges the whole minute to the two advertising terms and then adds the commands on top. But a device that is connected advertises at neither rate: its 2.34 s belong to the link. At one command a minute that is 2.34 s of 60 and the error hides inside the idle term, which is why cell 1 was never going to catch it. At four a minute it is 2.34 s of 15, and the fast window is 141.9 uA, so the double count is **22 uA of 248** -- the whole discrepancy, to within a microamp.

`power_table` now carries a fourth coefficient, `Tcmd`, and a connected
share `c = min(1, n Tcmd / 60)` that comes out of both advertising terms.
Two consequences beyond the corrected cell:

* **the saturation moves from 2.00 to 1.855 commands a minute**, since a command has to fit its own seconds into the minute as well as its window. The third sentence above still holds at two a minute, with less margin than it had;
* **the rows collapse exactly rather than nearly.** Taking the connection's seconds out of the idle term as well as the fast one is what makes the 2/min column identical at 200 ms and at 10 s; leaving them in the idle term left 5 uA of the advertising interval showing at saturation, which would have been a second wrong claim hiding behind a right one.

**This is the fourth time in two days that a figure taken from the shape of the arithmetic rather than from what the hardware does has cost a measurement**, and it is the first one the checks caught instead of the bench. Two cells were in the plan for exactly this and the plan was right: a 49-cell table computed from four coefficients and verified nowhere would have gone on the module page 14% wrong in the cell it exists to make.

### What the model already says, before anything is measured

**The write rate stops mattering almost immediately, and the advertising
interval stops mattering with it.** A command opens the fast window for 30 s, so
**two commands a minute hold it open permanently**: above that, every row of the
table collapses onto the same number, the idle interval cannot be read in the
current at all, and `fastTimeout` is the only lever left. With the order of
magnitude below -- 9 uC an event, so 90 uA at the 100 ms fast interval -- that
collapse is to something like four times what advertising at 2 s costs when
nobody writes.

That is worth stating before the measurement because it decides what the table
is *for*: not "how much does a write cost" (a few microamps, at any plausible
rate) but "how much does the responsiveness after a write cost", which is a
different knob on a different line of `setup()`. If the measurement confirms it,
the module page's own advice changes: a device commanded more than twice a
minute should be shortening `fastTimeout`, not lengthening `interval`.

### The arms this replaces, and when to go back to them

The nine-arm version of this section is in the history of this file and the
pieces still exist in `power-arms.js`. Three of them are worth coming back to,
and only for cause:

* **a board with no sketch at all**, if the fitted floor looks wrong: it is the
  one figure the sweep infers rather than measures;
* **forced rebuilds**, `bench.rebuild()` sealed and in clear, if the table is to
  cover devices that advertise a sensor whose value moves -- that is `Qrebuild`,
  and `power_table --rebuild-charge` takes it;
* **a link held open**, `tools/hold_link.py`, auto against pinned, which is the
  one case a per-command charge cannot represent and the one that could still
  put a guard into D-141.

### What to expect, so that a broken rig looks broken

Order of magnitude, from the radio's own datasheet figures rather than from
anything measured here, and **the sample rate decides which of these the rig can
actually see**: at 4 ksps a sample is 250 us, so a connection is twelve thousand
samples and a rebuild of 26-38 ms is a hundred, both of which integrate
honestly, while one advertising event is six samples and its *peak* is not a
figure this rig produces, the 400 Hz analog bandwidth having smoothed it before
the sampler ever saw it. That costs nothing, because what a battery cares about
is the mean over minutes, and every coefficient in the model above is a charge
rather than a peak.

**A PPK2 would see the peaks and would not help.** Nordic's kit samples current
at 100 ksps, twenty-five times the Arc, which is what it takes to draw the
shape of a single transmit; the Arc answers a different question, and this is
that question. Where the Arc is the better instrument here is the floor: 5 nA of
resolution against the PPK2's 100 nA, on a measurement whose whole long-interval
end *is* the floor. The one place the rate does bite is the marker, at 1 ksps on
GPI1: a window edge is right to a millisecond, which is 0.4% of a 250 ms
connection and invisible in a 120 s sweep step, so the one-second pulses of
`power-arms.js` are deliberately coarse. an advertising event on three channels is roughly 1.5 ms
of radio at about 6 mA, so **9 uC per event** -- 9 uA at a 1 s interval, 4.5 at
2 s, 2.8 at 3.2 s. An empty connection event is shorter, call it 4 uC, so **20
uA at a 200 ms interval and about 530 uA at 7.5 ms**, which is where the 27x of
D-141 comes from.

That gives three predictions worth stating before the measurement, because each
of them changes a decision if it is wrong:

1. **The firmware's floor dominates.** @enaon's board idles at ~45 uA with the
   module not loaded, ten times what advertising at 2 s should cost. If that
   holds on both boards, then the honest sentence for the module page is that
   this module is not what empties the battery, and the advertising interval is
   the only lever in it that matters.
2. **A command is cheap and pinning is affordable.** 5 s of connection at 20 uA
   is ~100 uC; 3 s at 530 uA is ~1.6 mC. So pinning costs about **1.5 mC per
   command**, which at 20 commands a day is 8 uAh against the ~110 uAh a day
   that advertising at 2 s already spends. Two orders of magnitude apart, and
   the comparison that settles it is arm I: the fast window after one disconnect
   is 30 s at ~90 uA, **2.6 mC**, already larger than the pinned command. A
   module that spends that without anyone objecting cannot object to this.
3. **A held-open link is the exception, and it is a big one.** At 530 uA a
   220 mAh cell is gone in about 17 days of being connected, against years at
   200 ms. If a device somebody leaves connected to Espruino Hub is a case this
   module supports, option 1 of D-141 -- pin it once in `setup()` -- needs a
   guard after all, and the held-open recording is what decides it.
4. **The table is flat above two commands a minute**, for the reason in the
   model above. If it is not flat, either `fastTimeout` is not doing what the
   module says it does or the fast window is not running at `fastInterval`, and
   both are bugs rather than surprises.

### What lands where

Each recording produces one CSV and one JSON next to it:
`docs/data/power-<board>-sweep.json`, `-commands.json`, `-commands-pinned.json`,
`-checks.json` and `-checks-cells.json`, written by `tools.power_charge --out`,
the call schedules as `-calls.json` beside them, plus the table itself
as `power-<board>-table.json` from `tools.power_table --out`. The CSV traces stay
out of the repository: sixteen minutes at 4 ksps is nearly four million samples,
and the JSON holds every figure anything quotes.

**And then the module page gets the table**, which is the point of the
exercise: an adopter deciding whether to put this on a coin cell should not have
to read a measurements file, and a reference table lets them read their own case
rather than ours. The shape, to be filled with real figures and not before:

```
What it costs on a battery
--------------------------

Sealed, nothing advertised that has to be re-read, <board> at <voltage>.

| advertising interval | 0/min | 1/min | 2/min | 3/min | 4/min | 6/min |
|----------------------|-------|-------|-------|-------|-------|-------|
| 200 ms               |       |       |       |       |       |       |
| 1 s                  |       |       |       |       |       |       |
| 2 s                  |       |       |       |       |       |       |
| 10 s                 |       |       |       |       |       |       |

Microamps, and the same table again in days on a CR2032.

Measured: the floor and one advertising event from a swept recording, one
command's charge from ten commands, two cells checked against the rest.
Everything else is those three numbers added up, and the arithmetic is
`tools/power_table.py` in the project repository.
```

Two sentences have to go with it, because they are what an adopter actually
decides on: that a write costs a microamp or two at any plausible rate, and that
what costs is the fast window the write opens -- so the lever for a device that
is commanded often is `fastTimeout`, not `interval`.

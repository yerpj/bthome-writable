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

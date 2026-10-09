# Decisions log

One entry per resolved question. `[VERIFY]` entries record the measured result
that closed a risk; `[DECISION]` entries record an owner ruling. Entries are
append-only: supersede, never rewrite.

---

## D-005 — `bthome-ble` tolerance of the `0xFF` declaration object  [VERIFY, T0.5]

**Status:** closed, 2026-09-08. **Closes risk #1.** **Result: primary path confirmed** —
the declaration lives in the BTHome service data; the manufacturer-data fallback
(§3.1, open decision 3) is **not needed** and stays a documented contingency only.

**Method.** `bthome-ble` 3.24.0 (latest on PyPI at the time of writing), fed
synthetic BTHome v2 advertisements through `BTHomeBluetoothDeviceData.update()`.
Reproducible as `tools/tests/test_bthome_ble_tolerance.py` (8 tests, part of CI).

**Findings.**

1. **`0xFF` is free.** `MEAS_TYPES` holds 95 object IDs, the highest assigned is
   `0xF2`. No collision with the declaration ID.
2. **An unknown object ID is skipped quietly, not fatally.** In the V2 branch of
   `_parse_payload`, an ID absent from `MEAS_TYPES` logs at **DEBUG**
   (`"Invalid Object ID found in payload"`) and `break`s out of the object loop.
   No exception, no WARNING/ERROR, and every object parsed *before* it is kept
   and dispatched normally.
3. **Therefore placement is not free: the declaration MUST be last.** Objects
   after it are silently lost. Verified both ways — declaration last keeps
   `battery` + `light`; declaration first yields no sensors at all. §3.1's
   SHOULD becomes a **MUST** in the normative spec (see D-006).
4. **"Last" also satisfies the ascending-ID rule for free.** `bthome-ble` emits a
   real `WARNING` when object IDs are not in ascending order. `0xFF` is above
   every assigned ID, so putting the declaration last is simultaneously the
   ordering-compliant position. No warning observed.
5. **Multi-instance works and its upstream naming matches our model.** Three
   `0x1E` objects in one packet become `light_1`, `light_2`, `light_3` —
   suffixed by 1-based occurrence index *in packet order*. Upstream entity
   naming and our positional bitmask indices therefore agree by construction,
   which is a free consistency win for §3.1 multi-instance.
6. **The write-only pattern (§3.2) is safe upstream.** A zero-length object
   (`0x53` text, len 0) is skipped by `bthome-ble` (`obj_data_length == 0` →
   `continue`, and the loop still advances — no hang) and produces no sensor
   entity. Preceding sensors are unaffected. So a write-only placeholder costs
   nothing on the core-BTHome side.
7. **Encrypted advertising behaves identically.** The declaration sits inside the
   ciphertext and meets the same object loop after decryption; a payload with a
   trailing `0xFF` declaration decrypts, verifies the bindkey, and yields its
   sensors. Nonce confirmed as `MAC(6, natural order) || 0xD2 0xFC ||
   device-info byte || counter(4 LE)`, matching §3.4's plan to vary the
   device-info byte per direction.

**Consequences for the spec.** §3.1 placement becomes normative (MUST be last);
open decision 3 (manufacturer-data container details) is de-prioritised;
risk #1 closed.

**Caveat.** This pins behaviour of `bthome-ble` 3.24.0. Point 3 in particular is
an implementation detail of upstream's parser, not a documented guarantee —
worth re-running on version bumps (the test is in CI, so a regression surfaces
on the next dependency update).

---

## D-006 — Declaration placement: last element  [DECISION, T0.2]

**Status:** proposed by the agent on the strength of D-005, awaiting owner
confirmation.

Normative wording: the declaration object MUST be the last element of the
BTHome service data. Rationale in D-005 points 3 and 4.

---

## D-001 — GATT service and characteristic UUIDs  [DECISION, T0.2]

**Status:** revised 2026-09-10 on Gordon's advice, superseding the values chosen
by the owner on 2026-09-08.

```
Service:              2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2
Write characteristic: 2FAA0002-3B0B-4B1A-9E2A-B4C2952E62F2
```

Properties on the characteristic: `write`, `write-no-response`.

The first choice was two independent UUID v4s — `2FAA47BC-…` and `639333F3-…` —
on the reasoning that the values are arbitrary and need only be collision-free.
That is true and still misses the convention: in Bluetooth one randomly assigns
*one* 128-bit UUID and varies the second 16-bit group per characteristic. The
device then stores one base instead of two unrelated UUIDs, which on a board
with 64 kB is the whole point. The base here keeps the low 96 bits of the
original service UUID, so only the discriminator is new.

This was exactly the question §6 of `for-gordon.md` put to him, and it is the
reason the values were held provisional rather than frozen early.

**Still provisional until the first public release.** They freeze permanently
there (risk #11) and must never change after.

---

## D-002 — Bitmask bit numbering  [DECISION, T0.2]

**Status:** adopted as recommended in the working document, awaiting Gordon's
acknowledgement (trivial, but pin it before anyone writes a second
implementation).

Bit *n* of the declaration bitmask refers to the *n*-th BTHome object of the
same packet, **bit 0 = the first object**, counting objects (not bytes) from the
start of the payload, the device-information byte excluded. Confirmed against
Gordon's own example: `40 0161 1E01 FF02` has battery at position 0 and the
light at position 1, and declares `0x02` = bit 1 = the light.

---

## D-003 — Simultaneous BLE connection cap  [DECISION, T0.2]

**Status:** decided by the owner, 2026-09-08. **Default 2.**

**Corrected 2026-09-23.** This said "user-configurable through the integration's
options flow". There is no options flow: `async_setup_entry` reads
`CONF_MAX_CONNECTIONS` from `entry.options`, and nothing can put it there. The
cap is effectively fixed at 2. Adding the flow is on the Home Assistant
quality-scale list rather than here.

A typical ESPHome Bluetooth proxy offers three connection slots; capping at two
leaves room for an Espruino UART/Web-IDE session (the coexistence rule of §5).
Made configurable for setups with several adapters or proxies. Zero-config is
preserved: the option has a working default and is never required.

---

## D-004 — License  [DECISION, T0.2]

**Status:** decided by the owner, 2026-09-08. **MIT**, both sides, one `LICENSE`
at the repo root. Matches Espruino's own license and keeps friction lowest for
an eventual merge into BTHome.

---

## D-007 — Confirmation timeout before revert  [DECISION, T0.2]

**Status:** decided by the owner, 2026-09-08. **Adaptive:
`max(5 s, 2 × observed advertising interval)`**, replacing the fixed 5 s default
proposed in the working document.

There is no acknowledgement in this protocol: after a write, HA shows the new
value optimistically and waits for the device's next advertisement to confirm
it. A fixed 5 s window produces false reverts on any device advertising more
slowly than that — the actuator really did change, but the HA entity snaps back.
HA already observes each device's advertising interval, so the window can be
derived from it at no configuration cost: a 5 s floor for healthy devices,
two intervals of grace for slow ones. Zero-config is preserved (§ rule 4).

Applies to read-write entities only; write-only entities (§3.2) are stateless
and never wait for confirmation.

---

## D-008 — Encrypted write payload field order  [DECISION, T0.2]

**Status:** decided by the owner, 2026-09-08. **Supersedes the working document
§3.4**, which specified `[counter][ciphertext][MIC]`.

The encrypted write payload is:

```
<ciphertext> <counter u32 LE> <MIC 4>
```

i.e. exactly BTHome's encrypted-advertising layout minus the device-information
byte, which for writes is implicit (§5.1 of PROTOCOL.md).

**Why the change.** The working document's order was almost certainly written in
passing rather than chosen: it makes the two directions differ for no benefit.
Aligning them lets both implementations share one framing routine — concretely
relevant on the Espruino side, which must build encrypted advertising *and*
parse encrypted writes on a RAM-constrained target. It also removes a gratuitous
divergence from a specification whose case to the BTHome maintainers rests on
reusing BTHome's own formats.

The rejected alternative kept the counter at fixed offset 0, so a device could
check it before decrypting without knowing the payload length. Marginal: the
length of a GATT write is always known.

**To do:** flag the correction to Gordon in espruino#8013 — it is a detail, but
the working document is the shared artefact and it now differs from the spec.

---

## D-009 — Write-only detection is limited to variable-length objects  [DECISION, T1.2]

**Status:** decided by the agent while implementing, **flagged to the owner for
relay to Gordon** — it narrows a sentence of §3 that was written loosely.

**The problem.** §3 says a write-only object is declared by advertising it "with
an empty/zero value". For a variable-length object that is unambiguous: a length
byte of 0 cannot occur any other way. For a **fixed-length** object it is not
detectable at all — a light that is off advertises `1E 00`, byte-identical to a
"zero value" placeholder. A receiver cannot tell a write-only trigger from an
actuator that happens to be in its zero state, and guessing wrong means either
exposing a stateless entity for a real switch, or applying the confirm/revert
model to something that will never confirm.

**The resolution.** Write-only is recognised only for variable-length objects
(text, raw) advertising length 0, and — once T2.1 lands them — for event-class
objects, whose "none" value is already a defined no-op rather than a state.
Every other object is treated as read-write.

**Why this loses nothing.** Write-only exists for actuators with no meaningful
uplink: a display, a buzzer, a trigger. Those are exactly the variable-length
and event-class objects. A write-only *boolean* is close to meaningless, and a
device wanting one can advertise an event object instead.

**Spec change required:** §3's "empty/zero value" should become "a
variable-length object advertising a length of 0, or an event-class object
advertising its 'none' value". Not applied to PROTOCOL.md yet — §3 is
co-designed and rule 2 sends it through Gordon.

**Cross-version re-check (2026-09-08).** D-005's findings were re-run against
`bthome-ble` **3.22.1**, the version Home Assistant 2025.1 pins — the release the
integration's test harness actually runs on. Every conclusion holds: `0xFF` is
free (that release's highest assigned ID is `0x65`), unknown IDs are skipped
quietly, and all fourteen advertising fixtures parse to exactly their expected
sensors with no log record above DEBUG. The integration's manifest therefore
requires `bthome-ble>=3.22.1` rather than the newest release.

---

## D-010 — The confirmation window opens when the write lands  [VERIFY + fix, T1.2]

**Status:** closed on hardware, 2026-09-08. Measured end to end: Home Assistant
2026.7.4 on a Raspberry Pi 3 with its built-in adapter, writing to a Puck.js
running the reference module.

**What was wrong.** The confirmation window (§6, D-007) was started as soon as
the entity queued its value. That folded four things into a window meant to
measure only one:

```
click ─┬─ debounce ─┬─ connect ─┬─ write ─┬─ disconnect ─┬─ adapter resumes ─┬─ next adv
       │            │           │         │              │  scanning         │
       └────────────────────── window was measured from here ─────────────────┘
                                          └── window should start here ───────┘
```

**What it looked like.** Every toggle bounced. Traced from the entity state:

```
turn_on    500 ms  on     (optimistic)
          5343 ms  off    (window expired -- reverted)
          7312 ms  on     (the confirming advertisement finally arrived)
```

The write always worked. The receiver simply gave up before the device could
answer, then corrected itself two seconds later — which reads to a user as an
actuator that refuses commands and then obeys anyway.

**Why the tests missed it.** They mock the transport, so a write "completes"
instantly and the two start times coincide. Only a real radio separates them:
a host with one Bluetooth adapter cannot scan while it is connected, so several
seconds pass between the click and the first moment a confirmation could even be
observed.

> **Corrected by D-047.** True of the Windows host this was measured on, not of
> single-adapter hosts in general: a Raspberry Pi running BlueZ keeps scanning
> while connected. The seconds are real, but they are connection setup. The fix
> below stands either way.

**The fix.** The coordinator now reports when a queued write has actually been
delivered, and the entity opens its window then. A write that fails outright
reverts immediately rather than waiting out a window for an answer that cannot
come.

**Result.** Three consecutive toggles from the Home Assistant UI, each settling
in under a second with no spurious transition, and the device's advertising
independently confirmed as `4000cf01641e01ff04` — light object `1E 01`.

**Consequence for the spec.** None: §6 already says the window covers the
device's refresh. This was an implementation reading of it, and the diagram
above is worth keeping for whoever implements the next receiver.

---

## D-011 — Reverting takes evidence, not just elapsed time  [VERIFY + fix, T1.2]

**Status:** closed on hardware, 2026-09-08. Refines D-010, which fixed *when*
the confirmation window opens; this fixes *what* closes it.

**What was wrong.** The window was purely a timer. A receiver could therefore
revert an entity having heard nothing at all from the device — a verdict
reached on no evidence, and quite possibly wrong, since the device may have
obeyed and simply not been heard.

That is not a corner case. A host with a single Bluetooth adapter **cannot scan
while it is connected**, and takes seconds to resume afterwards. Every write
therefore begins with a deliberate blackout of exactly the channel the
confirmation must arrive on. Measured on the development host: four
advertisements caught in thirty seconds from a device advertising every two,
with complete silence for stretches after each connection.

**The rule now.** An unconfirmed value is reverted only once **both** hold:

- the confirmation window has elapsed (D-007's adaptive value), and
- at least **two** advertisements have arrived since the write landed.

Two rather than one, because a single packet can already have been in flight
when the write was issued and says nothing about whether the device obeyed.

A ceiling still bounds the wait, so a device that has genuinely gone away does
not pin an entity optimistically forever — and in that case the entity is on its
way to `unavailable` anyway, which is the honest thing to show.

**Result.** Four consecutive toggles from the Home Assistant UI, each settling
in under half a second, none with a spurious transition. The warning logged on a
real timeout now carries both numbers, so the two failure modes read apart at a
glance: `did not advertise the written value within 1.0 s (0 advertisement(s)
heard since the write)` is a deaf host, while the same message with two or more
is a device that was asked and declined.

**Note for the spec.** §6 says a receiver "MUST revert if no confirming
advertisement arrives within its confirmation window" and leaves the window to
the implementation, so nothing there needs changing. But the window being a
duration is the obvious reading, and it is the wrong one — worth a sentence when
§6 is next revised, so the next implementer does not rediscover this.

---

## D-012 — A stale GATT cache makes a write vanish silently  [VERIFY + fix, T1.2]

**Status:** closed on hardware, 2026-09-09. Found while installing Gordon's
`homeassistant-espruino` integration alongside this one.

**Symptom.** Writes stopped taking effect, with no error anywhere. The transport
reported success, the device kept advertising, two or three advertisements
arrived after each write — and the value never changed. The receiver duly
reverted the entity and, in effect, blamed the device.

**Cause.** Every host caches a device's GATT table, and BlueZ persists that
cache across restarts of Home Assistant. **An Espruino device rebuilds its GATT
table every time code is uploaded to it**, so for this class of device the cache
going stale is routine rather than exceptional. A write resolved through a stale
cache lands on a handle that no longer means what it did, and reports success.

This is the worst failure this integration can have: nothing errors, so nothing
is retried, and the only visible effect is an entity that snaps back — which
reads as a device fault.

**The fix, in two parts.**

- Connect with `BleakClientWithServiceCache` and resolve the characteristic
  explicitly. If it is missing from the cached table, clear the cache,
  rediscover, and try once more before giving up.
- When a write *was* delivered and the device was heard from afterwards but
  never acted (the D-011 condition), drop the cached table so the next write
  rediscovers it. That is exactly what a stale cache looks like from outside,
  and clearing it is harmless in the other case — a device that genuinely
  rejected the write.

**Result.** Six consecutive real state changes, all applied, no reverts logged.
Before the fix, only the first write after a Home Assistant restart worked.

**Note for the spec.** Nothing in §4 is wrong, but this is worth a sentence in
the implementation notes: a receiver MUST NOT treat a successful GATT write as
evidence the write arrived where it was meant to. §6 already says advertising is
the only evidence of application; this is the same lesson one layer down.

**Aside.** This is also why the earlier "the host's radio is flaky" diagnosis was
only half right. The Windows adapter really does scan badly, and that did cause
several false alarms — but it was masking this, which was real.

---

## D-013 — Where the latency actually is  [VERIFY, T1.2]

**Status:** measured 2026-09-09, Home Assistant 2026.7.4 on a Raspberry Pi 3
with its built-in adapter, no proxy.

The round trip felt slow — eight to fourteen seconds from click to the device
acting — and the obvious suspect was the confirmation model. It is not. Debug
logging of the write path against entity transitions gives:

| Phase | Time |
|---|---|
| Coalescing debounce | 250 ms |
| **BLE connection, including discovery** | **5.4 – 10.4 s** |
| MTU negotiation, write, disconnect | ~2.3 s |
| Device applies, advertises, receiver parses | **~1.0 s** |

**Confirmation costs one second.** Roughly 95 % of the latency is establishing
the connection, and none of it is the protocol.

**The advertising interval is a direct lever on it**, because a central can only
begin a connection when it catches a connectable advertising event. Changing the
example device from 2000 ms to 200 ms, everything else identical:

| Advertising interval | Write path (connect + write + disconnect) | Median |
|---|---|---|
| 2000 ms | 7.7 · 12.7 · 12.7 · 8.7 s | ~10.7 s |
| 200 ms | 3.0 · 25.3 · 3.0 · 3.3 s | ~3.0 s |

A 3.5x improvement from one device-side parameter. The outliers in both rows are
a connection attempt failing and being retried, which the slower interval makes
both likelier and more expensive.

**Consequences.** The remaining ~3 s is still connection setup, so that is where
any further work belongs — not in the confirmation model, and not in the wire
format. The two directions worth pursuing are making the device easier to
connect to (advertising interval, connection parameters, staying fast for a
while after an interaction) and not reconnecting at all (holding the connection
briefly, or letting an ESPHome proxy own it while the host keeps scanning).

Note also that the MTU negotiated was 23 despite the receiver asking for 64, so
§4.4's default-MTU worst case is the live case here, not a corner case.

---

## D-014 — Device-side latency: fast advertising while interacting  [T1.1]

**Status:** implemented and measured on hardware, 2026-09-09. Follows D-013,
which established that ~95 % of the round trip is establishing the connection.

Three levers were considered on the device side. One turned out to be already
pulled, and two are now in the module.

**Connection interval — nothing to do.** Espruino already adjusts it
automatically: "when connected it's as fast as possible (7.5 ms)", relaxing only
after a minute idle. A short write burst never reaches that. Overriding it would
have been a change with no upside.

**Fast advertising while a receiver is around.** A central can only *begin* a
connection when it catches a connectable advertising event, so the idle interval
taxes every write, and again on every retry. Advertising fast all the time fixes
that and flattens the battery, so the module does it only when someone is
plainly interacting: from `NRF.on("connect")` until `fastTimeout` (default 30 s)
after `NRF.on("disconnect")`. Real use comes in bursts, so the first command
pays the idle interval and the rest do not.

**`whenConnected: true`.** The nRF52 can keep advertising during a connection,
switching to non-connectable packets for its duration — which is what floors
`fastInterval` at 100 ms, since the BLE spec does not allow non-connectable
advertising below that. Without it the device goes silent exactly when a
receiver most wants to hear it: during and just after the write it is sending.

**Measured**, same device, same receiver, six toggles each, `idle 2000 ms`:

| Configuration | Median | Min | Failures |
|---|---|---|---|
| Baseline: no fast advertising, no `whenConnected` | 10.7 s | 8.7 s | — |
| Fast advertising, `whenConnected: false` | 3.6 s | 3.2 s | 1/6 |
| Fast advertising, `whenConnected: true` | **1.7 s** | 1.7 s | 1/6 |

Steady state is **1.7 s**, from 8.7–13.8 s. The first command of a burst still
pays the idle interval (5–7 s), which is the deliberate trade for battery.

`whenConnected` halves the round trip on its own, and the failure rate is
identical with and without it — so it is not implicated in the occasional write
that does not take, which remains the cache-or-rejection question of D-012 and
self-heals.

---

## D-015 — A Bluetooth proxy is not part of the design target  [DECISION, T1.2]

**Status:** decided by the owner, 2026-09-09.

An ESPHome Bluetooth proxy would help the latency a great deal: it establishes
the connection while the host's own adapter keeps scanning, which removes the
deafness that dominates every measurement here. It is also Home Assistant's
recommended topology.

It is nevertheless **excluded from the design target**. Nothing tells us a given
user runs one, and nothing tells us their device is in range of it if they do.
A protocol whose usability depends on optional extra hardware is a protocol that
will disappoint most of the people who try it.

**So the reference environment is the worst realistic one:** a host with a
single Bluetooth adapter, which cannot scan while it is connected. Every
latency figure in these notes is measured there, and every optimisation is
judged there.

This is what makes `whenConnected` (D-014) load-bearing rather than a nicety,
and it is why the confirmation model counts advertisements rather than seconds
(D-011): on a single-adapter host, the receiver is deaf precisely because it
wrote.

> **Corrected by D-047.** "Cannot scan while it is connected" was a Windows/WinRT
> observation generalised into a property of single-adapter hosts. BlueZ on a
> Raspberry Pi keeps scanning throughout a connection. The worst realistic
> environment is still the right design target, and `whenConnected` and the
> evidence-counting confirmation are still worth having — for WinRT, for
> devices out of range or asleep — but not for the reason given here.

---

## D-016 — Receiver-side latency work  [T1.2]

**Status:** implemented and measured, 2026-09-09. Completes the latency work of
D-013 and D-014 on the side this project controls.

**Leading-edge coalescing.** The write queue used a trailing debounce: every
change waited 250 ms before going out, so that a burst produced one write. But a
single click — the overwhelmingly common case — paid that quarter second to
save a connection in the rare case. The queue now fires immediately and
coalesces *behind* the write in flight instead of in front of it. A burst still
produces two writes rather than a dozen, because the connection takes seconds
and everything queued during it merges into one follow-up.

**Redundant writes are not sent at all.** A payload identical to the one just
written, or one whose every value the device already advertises, achieves
nothing and costs a multi-second connection. Both are now skipped. This matters
more than it sounds: re-asserting state on a schedule is ordinary automation
practice. A payload carrying a write-only object is never skipped — a trigger
has no advertised value, and firing it again is the whole point.

**The MTU is only asked about when it matters.** Every write used to read
`mtu_size`, which each backend answers differently and some warn about. Now only
payloads above the 20 bytes a default MTU carries ask.

**Measured**, eight toggles, same device and receiver as D-014:

| | Median | Min | Max | Failures |
|---|---|---|---|---|
| Baseline (D-013) | 10.7 s | 8.7 s | 13.8 s | — |
| Device-side work (D-014) | 1.7 s | 1.7 s | 7.5 s | 1 in 6 |
| ...plus receiver-side (this) | **1.7 s** | **1.2 s** | 7.1 s | **0 in 8** |

The median does not move, and should not have: the round trip is connection-
bound, and none of this makes a connection faster. What it does is take a fixed
250 ms off every command, remove connections that never needed to happen, and —
on this run — clear the intermittent failure. Eight for eight is not proof that
the failure of D-012 is gone, but it is the first clean run.

**Where the remaining time is.** Roughly 1.2 s of steady-state round trip, of
which the connection is still the large majority. Further gains have to come
from establishing connections faster, which on a single-adapter host is largely
out of our hands.

---

## D-017 — How much data a write can actually carry  [VERIFY, T2.1]

**Status:** measured 2026-09-09 against a Puck.js, from a Windows host
(negotiated MTU 53). Prompted by the question of whether a Home Assistant sensor
value can be pushed to a screen on an Espruino device.

**The MTU is a hard ceiling, not a performance hint.** §4.4 says receivers
SHOULD negotiate at least 64 and devices SHOULD support long writes. What
actually happens is that a payload larger than `MTU - 3` is **refused outright**
— `BleakGATTProtocolError`, no attempt at a prepared write:

| Write payload | Text characters | Result |
|---|---|---|
| 6 – 50 bytes | 4 – 48 | arrived intact |
| 52 bytes and up | 50 and up | refused by the stack |

50 is exactly `53 - 3`. The device's characteristic was declared with room for
128 bytes, so the limit is the transport, not the device.

**So: budget a write-all payload against the MTU, and do not rely on long
writes.** A text object costs two bytes of overhead (`0x53`, length) plus its
characters, and shares the payload with every other writable object, since a
write always carries all of them (§4.2).

**What that means in practice.** At the 23-byte MTU that BLE guarantees, a whole
write-all payload is 20 bytes — around **18 characters** of text once the object
header is paid, less if the device has other writable objects. At a negotiated
53, it is 48. Enough for `21.4 °C` or `Salon 21.4C 62%` in either case; not
enough for a paragraph.

**An unresolved caveat.** The Home Assistant side reported an MTU of 23, but
that is bleak's placeholder until `_acquire_mtu()` is called on the BlueZ
backend, so the real negotiated value there is **unknown and may be higher**.
The receiver now asks properly before warning. Establishing the true figure on
that path needs the `text` platform, which is T2.1.

**And the reliability point, which matters more than the size.** A text object
is write-only, so §6's confirmation model does not apply: the device never
advertises what it was told, and nothing reports that a write landed. Combined
with D-012 — a write can be reported as successful and do nothing — pushing a
display value is currently **fire-and-forget with no way to detect a loss**.
For a value refreshed on a timer that is tolerable, since the next write
corrects it. For a one-shot command it is not, and §3 should probably say so.

---

## D-019 — `interval` is the advertising interval; each entry reads on its own  [T1.1]

**Status:** decided by the owner and implemented, 2026-09-09. Supersedes a first
attempt that split the option the wrong way.

**The model.**

- **`interval` is the BTHome advertising interval**, as BTHome and the upstream
  Espruino module mean it: how often the radio transmits. It is therefore the
  ceiling on how fresh a receiver's view can be — nothing can be perceived to
  change faster than the device transmits.
- **Each entry may carry its own `interval`**: how long its value may be reused
  before `get()` is called again. Omitted, it **inherits the advertising
  interval**, which is the fastest a change could be perceived anyway.

An entry's interval can only make a value appear *less* often than the
advertising interval, never more. The packet still goes out every advertising
interval carrying the cached reading; what is skipped is the call to `get()`.

**This is where the device's CPU budget is allocated, and only the person
writing the sketch can decide it.** Reading a relay's GPIO is free; reading a
CO2 sensor can take tens of seconds. Nothing in the module should assume either,
which is why inheritance is the default rather than "read every time".

Inheriting rather than always reading matters for one case in particular: the
packet is rebuilt not only on the advertising timer but also immediately after a
write, so that the confirmation goes out at once (§6.2). With "read every time",
every write would drag every sensor into a fresh reading — including the slow
one. `interval: 0` asks for exactly that behaviour where it is wanted, which is
a value that must be fresh in the confirmation and is cheap enough to read
there.

**The first attempt was wrong.** It kept `interval` as the sensor refresh and
added `advertisingInterval` for the radio — inverting which one is the familiar
name, and still forcing every sensor onto one schedule. The right split is
per-entry, and `interval` should mean what it means everywhere else in BTHome.
`advertisingInterval` is gone.

**Writable entries ignore their read interval** and are always read fresh.
Otherwise a write could be confirmed with a value read before it, which from the
outside looks exactly like the device refusing the write.

**Why `interval` is the knob worth tuning.** It sets three things at once: how
fresh the receiver's view is, how long the first command of a burst waits (a
central can only begin a connection when it catches an advertising event), and
what the device spends its battery on while nothing is happening. Measured on
the reference setup:

| `interval` | First command of a burst | Steady state |
|---|---|---|
| 2000 ms | 5 – 9 s | 1.7 s |
| 500 ms | 4.2 s | 1.7 s |

The steady state does not move: once a receiver is around the device is in fast
mode (D-014) and this no longer applies. What changes is the cold-start cost.

A value outside the 20–10000 ms the radio accepts is **refused at setup** rather
than silently clamped by the firmware. `setAdvertisingInterval()` changes it at
runtime — driven by `tools/set_adv_interval.py` — because choosing the number
means trying it against a real receiver, and reflashing to try a number is a
poor way to find out.

---

## D-020 — Suppressing a repeated write must not outlive the burst  [T1.2]

**Status:** found and fixed on hardware, 2026-09-09, within an hour of being
introduced.

D-016 added two suppressions for writes that would achieve nothing. One
compares the payload against what the device currently advertises — sound,
because advertising is the source of truth (§6). The other compared it against
the payload last sent, to drop the trailing write of a burst that ends where it
started.

**The second one was kept as instance state, and that was wrong.** It records
what was *sent*, not what the device *did*, and a write can be delivered and do
nothing (D-012). So after an unconfirmed write the receiver refused to send that
value ever again: the entity reverted, the user asked once more, and the request
was discarded as redundant. A transient failure became a permanent one.

Observed as five consecutive toggles failing with nothing in the log but
`skipping 1e01, which would change nothing` — the receiver quietly declining to
do the only thing that could have recovered.

The memory is now local to one flush loop, which is the only scope where it was
ever meaningful. Six toggles after the fix: median 2.2 s, min 1.3 s, no
failures.

**The lesson worth keeping.** An optimisation that skips work has to be founded
on evidence about the device, not on the receiver's memory of its own
intentions. The advertised-state check passes that test; the last-payload check
only does within a window where nothing can have changed underneath it.

---

## D-021 — The advertising interval hurts the cold start faster than linearly  [VERIFY]

**Status:** measured 2026-09-09 on the reference setup, at the owner's request
to see 5 s for himself.

| `interval` | First command after idle | Warm |
|---|---|---|
| 500 ms | 4.2 s | 1.7 s |
| 2000 ms | 5 – 9 s | 1.7 s |
| **5000 ms** | **8.1 s, 36.9 s, and one outright failure** | 1.2 – 4.6 s |

Two and a half times the interval does not cost two and a half times the wait.
A central can only begin a connection when it catches an advertising event, so a
missed or failed attempt costs a whole further interval plus the connector's own
backoff — and at 5 s those compound into tens of seconds, or into giving up.

The warm case is untouched, as ever: once a receiver is around the device is in
fast mode (D-014) and this value no longer applies.

**So the interval is not a smooth dial.** Somewhere between 2 s and 5 s the
cold-start cost stops being an annoyance and becomes a failure mode. A device
that wants a long idle interval for battery reasons needs something else to
carry the first command — the `fastTimeout` window covering the likely next
interaction, a button that wakes it into fast advertising, or an accepted
"press twice" behaviour.

---

## D-022 — A device can silently lose its program  [INCIDENT]

**Status:** cause established 2026-09-09; fixed by D-023.

Mid-session the Puck stopped advertising BTHome entirely, while still answering
its console. `bw`, `BTHomeWritable` and `setup` were all undefined — no program
was running — and `Storage` held a `.bootcde` of **3511 bytes containing only
the example source**, without the module it depends on. On boot that code runs,
throws on an undefined `BTHomeWritable`, and leaves the device with nothing.

Recovered by erasing `.bootcde` and `.varimg` and re-uploading with `save()`.

**Cause: a half-finished install of the right shape.** The owner had written
`.bootcde` by hand, which is exactly where application code belongs. What was
missing is the other half of the convention: `require("X")` resolves from
Storage under the bare name `X`, so the modules have to be there too, and they
were not. The application booted, threw on an undefined `BTHomeWritable`, and
left nothing running.

The uploader in use at the time could not have produced that layout, and its
`save()`/`.varimg` approach is what made the convention easy to get half-right:
it inlined the module into one stream rather than installing it, so there was no
step whose absence was visible. D-023 replaces it.

**Worth knowing regardless of cause.** A device whose boot code references
something its boot code does not define is bricked in a way that looks exactly
like a flat battery: still connectable, advertising nothing. Anyone debugging a
silent device should check `require("Storage").list()` early.

---

## D-023 — Install the way Espruino installs: modules in Storage, app in `.bootcde`

**Status:** adopted 2026-09-09, verified on hardware.

Until now the uploader inlined every `require`d module into one stream and
called `save()`, which writes a `.varimg` memory image. That works, and it is
the wrong shape for a device meant to be left running.

The convention Espruino actually implements, confirmed in `jswrap_modules.c`
("Has it been manually saved to Flash Storage?"), is that `require("X")` looks
in Storage for a file named exactly `X` — no `.js`. The suffix is appended only
on the network path, never on the Storage path. So:

```
Storage "BTHome"           the upstream module, by its bare name
Storage "BTHomeWritable"   this project's module, likewise
Storage ".bootcde"         the application, run at boot
```

`tools/espruino_deploy.py` writes that layout; `tools/espruino_upload.py` keeps
its place for iterating, where pushing everything into RAM is the point.

**Why it is better, not merely idiomatic.** The modules live in flash instead of
RAM, on a board with 64 kB of it. The application keeps its ordinary `require()`
calls, so the file that runs on the device is the file in the repository rather
than a generated bundle. And boot no longer depends on a memory image, which is
the fragile part: a `.varimg` is restored *instead of* running `.bootcde`, so
one left behind silently masks every subsequent install — the deployer erases it
for that reason.

Verified end to end: deploy, then `E.reboot()`, then the device advertises
`4000060164054d29001e00ff08` on its own. That is the check D-022 needed.

### Three Windows-side findings, none of them about BTHome

Worth writing down because each cost real time and each looks like a device
fault:

1. **`async with await connect(...)` connects twice.** `BleakClient.__aenter__`
   calls `connect()` itself, so an already-connected client gets connected
   again, and on WinRT the second call hangs — uncancellably, so even
   `asyncio.wait_for` will not break it. Self-inflicted, and it presented as
   "the device is unreachable".
2. **Forcing uncached service discovery hangs on this host.** The integration
   must keep doing it (D-012), because the layout it addresses changes. Tools
   that only speak Nordic UART must not: that service is fixed, so the cache
   cannot be wrong, and asking anyway wedges the adapter.
3. **A connection attempt is a race against the advertising interval**, and one
   attempt is not a fair test. At 5 s the host catches roughly one packet per
   30 s and `BleakError: Unreachable` usually means "missed the window", not
   "no device". Retrying is the honest reading — and it is the same cold-start
   cliff D-021 describes, met from the tooling side.

---

## D-024 — At 5 s, the interval costs refresh rate, not interaction latency

**Status:** measured 2026-09-09, through Home Assistant, on the flash install.

The advertising interval was raised to 5000 ms — deliberately slow — to see what
it breaks. Measured end to end, from a Home Assistant service call to the
illuminance sensor reporting the LED's effect:

```
TURN ON    t+0.7s  lux 109.4      TURN OFF   t+0.7s  lux 592.7
           t+1.7s  lux 585.0                 t+1.7s  lux 106.6
           t+6.5s  lux 591.3                 t+5.6s  lux 107.2
           t+11.4s lux 588.5                 t+11.4s lux 103.1
```

**The action and its confirmation land in 1.7 s at a 5 s interval**, and the
readings that follow arrive about every 4.8–5 s. Those two numbers measure
different things, and the distinction is the whole point:

- 1.7 s is the *warm* path. The device is in fast advertising during and after
  the connection (D-014), so the idle interval does not apply to it at all.
- ~5 s is the idle refresh rate — how often a value the user did not ask about
  gets updated. This is what the interval actually buys battery with.

So the interval is not a latency dial for anything a user clicks. It is a
latency dial for the *first* interaction after a quiet period (D-021, where the
cliff lives) and a refresh-rate dial for everything else. A device can afford a
long idle interval far more comfortably than the naive reading suggests —
provided something covers the cold start.

A caution about measuring this: an earlier run interleaved commands faster than
the confirmation arrived, and read the previous command's confirmation as the
current one's — a 590 lux "response" to turning the LED *off*. At a slow
interval, a measurement loop has to wait out the confirmation or it will report
the loop inverted.

---

## D-025 — Changing the UUIDs is invisible to discovery

**Status:** measured 2026-09-10, migrating the reference device and its Home
Assistant install to the D-001 revision.

The change worried me more than it deserved. Because **the service UUID is never
advertised** (§4.1), nothing a receiver uses to *find* a device depends on it:
discovery keys on the BTHome service data `0xFCD2`, the config flow's device
list is built from that, and the entity layout keys on positions. The UUID only
matters after a connection is already open.

So the migration is: deploy the device, put the new integration in place,
restart, re-add. Verified end to end afterwards — 102 -> 583 lux on, 591 -> 110
lux off, through Home Assistant, with the device merge (`bthome` and
`bthome_writable` on one device) intact.

The one hazard is the one already known: a receiver holding a cached GATT
database would keep writing to a characteristic that no longer exists. Nothing
new was needed for it — D-012's explicit characteristic resolution and
cache-clear-on-unconfirmed is exactly this case.

### Removing stale entities is not a registry operation

Five sensors from an earlier firmware layout (temperature, humidity, pressure
and two extra batteries) survived on the same MAC. Deleting them from the entity
registry looked like it worked and it did not: Home Assistant's `bthome`
integration restores its known sensor set from its config entry at startup, so
they were all back after the next restart.

What actually removes them is deleting the config entry and letting discovery
re-create it. Worth knowing before reaching for the registry, and worth knowing
that a device's entity list is owned by whichever integration created it — here
the stock `bthome` integration owns every sensor, and this project's owns only
the switch. That division is deliberate: we depend on `bthome-ble` for parsing
rather than duplicating it.

---

## D-026 — T1.3: AES-CCM on the nRF52 is a go, and needs no JavaScript AES

**Status:** measured 2026-09-10 on Puck.js 2v27 (nRF52832, 64 kB RAM), against
the shared test vectors. Reproducible with `python -m tools.ccm_bench`.

The task asked for ms/frame and a go/no-go on implementing CCM in JavaScript.
The premise turned out to be wrong in a useful way: **no AES has to be written
in JavaScript at all.**

Puck.js has no `AES.ccmEncrypt` — the firmware guards CCM behind `USE_AES_CCM`
and this build does not set it — but it does have native AES, and CCM is made
entirely of parts it provides:

- the tag is a **CBC-MAC**: CBC with a zero IV over `B0 || padded plaintext`,
  taking the last ciphertext block;
- the keystream is `E(A0) || E(A1) || …`, and since **ECB encrypts each block
  independently**, one ECB call over the concatenated counter blocks yields all
  of it at once, whatever the payload length.

So a frame costs **two native calls plus some framing**. All four advertising
vectors are reproduced byte-for-byte on the device, ciphertext and MIC.

```
CCM frame     31.8 ms      (superseded: see D-028, now 75 ms)
of which AES   4.5 ms
```

> These numbers are from the first implementation, which asked the cipher for
> the whole frame in two calls. That turned out to fail under memory pressure
> (D-028); the version that works costs 75 ms.

**Go.** And by a wider margin than the raw number suggests, because the cost is
per *packet rebuild*, not per advertisement: `refreshAdvertising` runs on
`interval`, and the radio then repeats that payload for free. At a 1 s interval
that is about 3 % of one core, on a device whose only other job is reading a
sensor.

### The interesting part is that AES is 14 % of it

Profiling the rest, per call:

```
8-byte XOR loop        5.62 ms     <- the single largest item
counter-block loop     3.40 ms
ECB + wrap             3.20 ms
CBC + wrap             2.53 ms
Uint8Array.set(13)     0.88 ms
```

**Touching a typed array element from JavaScript costs about 0.7 ms** on this
board. Eight of them outweigh the whole of AES. An attempt to optimise by
hoisting the buffers out of the function and patching them in place made it
marginally *worse* (28.4 ms), because `fill`, `subarray` and `set` are the same
kind of interpreted work.

The lever, if this ever needs to be faster, is removing per-byte JavaScript
loops — not touching the crypto. Which is also the shape of the upstream defect
below: a working CTR would delete the largest loop outright.

---

## D-027 — Espruino's AES CTR mode ignores its `iv`  [UPSTREAM DEFECT]

**Status:** found 2026-09-10 on Puck.js 2v27 while implementing D-026.

`AES.encrypt(data, key, {iv: …, mode: "CTR"})` returns the same bytes for any
`iv`. Two IVs sharing no byte produce identical output, and that output is
exactly `E(0…0)` — the counter block is always zero.

```
iv 000102…0e0f  ->  1838858c73da85d4885458a8e5dbda4f
iv ffeeddcc…00  ->  1838858c73da85d4885458a8e5dbda4f
E(zero block)   =   1838858c73da85d4885458a8e5dbda4f
```

CBC and ECB honour their parameters and match a reference implementation
exactly; `OFB` returns `undefined` rather than a result.

**This is worth reporting for its own sake, not only for ours.** Counter mode
with a fixed counter block reuses one keystream for every message under a key,
so two ciphertexts XOR to the two plaintexts XORed. Anyone reaching for CTR on
Espruino — the natural choice for a stream cipher over a nonce — gets something
that looks right and offers no confidentiality across messages. Written up for
espruino#8013 in `for-gordon.md`.

For this project it is only an inconvenience: the ECB route above is unaffected,
and costs one extra XOR loop that a working CTR would have absorbed.

---

## D-028 — `AES.encrypt` fails on large inputs long before memory runs out

**Status:** measured 2026-09-10 on Puck.js 2v27, while making AESCCM.js pass the
vectors on hardware.

`AES.encrypt` allocates its result as one contiguous run of the variable heap.
When no run that long is free it prints `ERROR: Not enough memory for result`
and **returns `undefined`** — which the caller then hands to
`new Uint8Array(...)`, producing `Unsupported first argument of type undefined`
several frames away from the cause.

The threshold is not a size limit. It moves with how full the heap is:

```
                        free blocks   16   32   48   64   128
sketch running                 1494    ok   ok   ok  FAIL  FAIL
fresh interpreter              2567    ok   ok   ok    ok    ok
```

and with a console session's own variables in the way, even 32 bytes failed.
`process.memory().free` is no guide, because it counts free blocks rather than
consecutive ones: a REPL `new Uint8Array(256)` succeeded in the same session
where a 48-byte AES call did not.

**What this changes.** AESCCM.js asks for at most 32 bytes per call and builds
them in a buffer allocated once, at module load, while the heap is still clean.
CBC chains across calls through its IV, so splitting the MAC costs only the
extra call. With that, all 16 vectors pass on-device including the 30-byte one,
which had failed.

The cost is real: **75 ms per frame against 38 ms** for the version that did it
in two big calls. Not, as I first assumed, from replacing `fill` with a loop —
restoring the native `fill` changed nothing measurable. It is the extra
JavaScript around the cipher: more function calls, more `subarray`, more
per-block bookkeeping. On this interpreter that is what costs, and it is the
same lesson as D-026 from the other side.

At a 1 s advertising interval, 75 ms is about 7.5 % of one core. Still a go.

**Worth reporting upstream.** An allocation failure that returns `undefined`
rather than throwing turns a resource problem into a type error somewhere else,
and the message names memory when memory is not what ran out.

---

## D-029 — A device can silence itself inside `setup()`  [INCIDENT]

**Status:** caused, understood and guarded 2026-09-11. Recovery needs the
button.

Deploying the encrypted example left the Puck advertising nothing at all. The
cause is a two-step failure, and the second step is the one that matters:

1. `NRF.setAdvertising` refused the encrypted payload with
   `ERR 0xc (DATA_SIZE)`. The module's capacity check had passed, because it
   checks the plaintext against §2.3's arithmetic and the radio's real limit is
   lower than that arithmetic says (D-030).
2. **The radio stops advertising to reconfigure**, so the throw left it stopped.
   `setup()` aborted, `.bootcde` reproduced the failure on every boot, and a
   device that does not advertise cannot be connected to — so it cannot be
   fixed over the air at all.

That is D-022's silhouette again, from a different direction: a device that is
alive, powered and completely unreachable. Only now the cause is ours.

**The guard.** `refreshAdvertising` catches a rejected payload, falls back to
the smallest valid BTHome packet — device-info and packet id, three bytes, which
any radio will take — and only then throws, naming the size the radio refused.
The device stays findable and connectable, so the next deployment fixes it.

**The lesson is narrow and worth stating plainly:** on this platform, code that
configures the radio must not fail after stopping it. Validating harder is not
enough, because the limit that matters is the radio's and it was not the one in
the specification.

Recovery on a Puck.js is physical: hold the button through boot until all three
LEDs light, then release — a self-test runs, the saved code is not loaded and
not erased, and the device is connectable again.

---

## D-030 — §2.3's budget is optimistic: this radio takes less  [SPEC ISSUE — for the owner]

**Status:** measured 2026-09-14 on Puck.js 2v27 with `tools/adv_budget.py`.
**Not acted on in the specification**, per rule 2: §2.3 is co-designed and this
needs Gordon.

```
advertising options                     max service data
module defaults                                       17
without whenConnected                                 17
without discoverable                                  17
showName:false                                        20
```

So the answer is **17, not 24**, and `showName:false` buys three of the missing
seven. Neither `whenConnected` nor `discoverable` costs anything, which rules
out the trade D-014 would have made painful. Where the remaining four go is not
established; the radio simply refuses.

Plain, this project's example spends 13 bytes and now has four to spare rather
than eleven. Encrypted it needs 21, which is why it was refused: with
`showName:false` an encrypted device has **11 bytes for objects**, and the
example had to drop its battery reading to fit in 10.

The module gained two options rather than guessing: `showName`, and
`maxServiceData` for a sketch to declare what its radio really takes. The
default stays at §2.3's 24, so nothing changes for anyone who has not measured.

§2.3 works the budget out as `31 - 3 (Flags AD) - 4 (service data header) = 24`
bytes of BTHome service data. Asked directly, with the options this module uses
(`connectable`, `discoverable`, `whenConnected`), the radio accepts 13 bytes and
refuses 20:

```
NRF.setAdvertising({0xFCD2: new Uint8Array(n)}, {interval, connectable,
                    discoverable, whenConnected})
  n = 13  ok
  n = 20  ERR 0xc  (DATA_SIZE)
  n = 24  ERR 0x9  (INVALID_LENGTH)
```

The exact ceiling between 14 and 19 is not yet known — the device silenced
itself (D-029) before the bisection ran, and it needs measuring again with the
several option combinations, since `whenConnected` is the likely culprit: it
makes the stack keep a second form of the payload.

**Why it matters more for encryption.** Plain, this project's example spends 13
bytes and fits with nothing to spare. Encrypted, the counter and MIC add 8, so
the same device asks for 21 — over the line. That is not an implementation
detail to work around: it means **§2.3's stated capacity does not hold on the
reference platform**, and an encrypted device has far less room than the
specification promises.

Options for the owner, none of them mine to pick:

1. State the real budget in §2.3 and reduce it for encrypted devices
   accordingly, which is honest but platform-specific.
2. Keep §2.3's arithmetic as the protocol's limit and require implementations to
   enforce whatever their radio actually accepts, which is what the module now
   does defensively.
3. Drop `whenConnected` for encrypted devices if that is what buys the bytes —
   trading D-014's latency work against capacity.

Until this is settled, an encrypted device on Espruino must keep its object
list short, and a receiver cannot assume 23 bytes are available.

---

## D-031 — Deployments were silently corrupt, and nothing checked

**Status:** found and fixed 2026-09-14, recovering from D-029.

After the button recovery the Puck still would not advertise, and the reason was
not the one being chased. `bw.setup()` threw `Got [ERASED] expected ID` — an
Espruino *parser* error. The module in Storage had a hole in it: a chunk of the
file that was never written, still erased flash.

The console has no flow control, `espruino_deploy.py` sends a file as a few
hundred `Storage.write()` statements back to back, and a dropped statement
leaves exactly that. **Nothing verified what arrived.**

What makes it nasty is Espruino's laziness: a function's body is parsed when it
first runs, not when the module loads. So a damaged module `require`s cleanly,
reports `typeof` as an object, and fails later from whichever function happened
to span the gap — arbitrarily far from the deployment that caused it. Both
D-022 and D-029 wore that same face, and this was hiding behind them.

**The fix is the obvious one, which should have been there from the start.**
After writing each file the deployer asks the device for `E.CRC32` of what it
stored and compares it with the host's, rewriting up to three times and failing
loudly rather than leaving a device to break later. It earned its place on the
first run: `AESCCM` came back with the wrong CRC and the rewrite fixed it.

The plain example then deployed, booted and closed its loop: 104.4 lux off,
598.3 on, 5.7x.

**Worth generalising.** Every silent-device incident in this project so far —
D-022, D-029, this one — presents identically: powered, connectable or not,
advertising nothing. The way to tell them apart is to ask the device something
and read the answer, not to infer from the radio. `require("Storage").list()`,
a CRC, `bw.plan()`: each of these would have separated these three causes in
seconds.

---

## D-032 — The bench can cut the power, so nothing has to be permanent

**Status:** in place 2026-09-14, at the owner's suggestion and on his hardware.

The Puck now sits on a switchable 3V3 rail driven by an OOTY board — a hardware
debug aid on the bench, reachable over a serial port. `tools/ooty.py` drives it:

```
python -m tools.ooty state | on | off | cycle
```

Two things follow, and together they close the worst failure mode this project
has had.

**The application no longer lives in flash.** `espruino_deploy.py` now puts the
modules in Storage, erases `.bootcde`, and sends the sketch over the console to
RAM. A sketch that throws while configuring the radio can leave a device
advertising nothing — unconnectable, therefore unfixable over the air — and from
`.bootcde` that repeats at every boot (D-029). In RAM it lasts until the next
reset. `--to-flash` is still there for a device meant to run unattended.

**And a reset is now a command.** Verified in both directions: with the sketch
running from RAM the device advertises `400014016405d328001e00ff08`; after
`ooty cycle` it comes up as a bare `Puck.js f7b9` with no service data at all.

What this buys is not convenience. Twice — D-029 and D-031 — work stopped
because a device could only be recovered by a finger on a button, which meant
waiting for someone to be in the room. Experiments that could brick the board
were, until now, things to avoid. They are now things to try: measuring what the
radio will really accept (D-030) means deliberately handing it payloads it will
refuse.

The OOTY's own protocol client is imported from its repository rather than
reimplemented here; `OOTY_PATH` points at the checkout. `VM` is not a check on
this rail — it watches the switched VBUS input, a different one.

---

## D-033 — T3.1 is done: encryption works on hardware, both directions

**Status:** verified 2026-09-14 on Puck.js 2v27, application running from RAM.

**Advertising.** The device seals its packets as BTHome v2 does, and the library
that will have to read them agrees: `bthome-ble` reports `bindkey_verified=True`
and decodes `{packet_id: 17, illuminance: 110.32, light: False}` out of
`41089f7e2ffbbedc298d8510000000368e105d`.

**Writes.** A sealed write with device-info `0xFF` in its nonce (§5.1) is
accepted and applied, and the proof is physical rather than an echo — the same
closed loop as ever, through the cipher:

```
write light on   (counter 73174)  ->  illuminance 599.64, light True
write light off  (counter 73175)  ->  illuminance 110.29, light False
replay of the first write         ->  counter_not_increasing, state unchanged
```

That last line is §5.2 doing its job: a byte-perfect replay whose MIC verifies
is still refused, because its counter does not advance. Reproduced twice.

One honest gap: the first attempt, immediately after deployment, silently
changed nothing — no error reached `onError`, and it has not recurred in the
runs since. Not explained, and not reproduced. Worth remembering if writes are
ever seen to be dropped right after an upload.

---

## D-034 — A cached module's source is an offset into flash, not a copy

**Status:** found and fixed 2026-09-14. Explains several earlier mysteries.

After the modules deployed with matching CRCs and loaded with the right exports,
the sketch still failed:

```
Uncaught SyntaxError: Got [ERASED] expected EOF
    at setup (:1:1)
```

Printing the offending function gave the answer at once. This is
`BTHomeWritable.encodeDeclaration`, straight off the device:

```
function (pos) {
t.subarray(start, Math.min(start + 16, pt
```

That body is **AESCCM's source text**. Espruino keeps a function's source as an
*offset into the flash file it was parsed from*, not as a copy, and `require()`
caches the module object in RAM. So rewriting the module files underneath a
cached module — which is exactly what a deployment does — leaves those offsets
pointing at whatever now occupies the address. The functions then read as
erased, or as a neighbour's text.

Nothing detects it: `Storage.read()` returns the right bytes, the CRC matches,
`Object.keys(module).length` is right, and the failure only appears when a
function body is finally parsed, blamed on the line that called it.

**The fix is one statement**: `Modules.removeAllCached()` after writing the
modules and before running the sketch.

### What this retrospectively explains

- **The deployment that "corrupted" AESCCM.** D-031's CRC check is still doing
  real work — it catches genuine dropped writes — but some of the confusion
  attributed to dropped statements was this instead.
- **D-033's one unexplained failure**, where the first write after a deployment
  silently did nothing. A stale cached module is a very good candidate: the
  write path would have been parsed out of moved flash.
- **Why a power cycle always seemed to fix things.** It clears the cache, which
  is the actual repair.

The general lesson matches D-031's: on this platform, a device that answers
every question correctly can still be broken, because the thing that is wrong is
only read later. Ask it to *run* something, not just to describe itself.

---

## D-035 — The screen works, and the write ceiling is not always the MTU

**Status:** measured 2026-09-14 on a nice!nano (2v29.105) with an SSD1306.

The use case the project was started for now runs: a Home Assistant sensor value
on a BLE screen, the device polling nothing and configured by nobody.

```
python -m tools.push_text --address CD:F5:77:3A:B2:16 \
    --entity sensor.bureau_mobilesensf7b9_illuminance
-> writes 5314496c6c756d696e616e6365203130332e30336c78
-> device is showing: "Illuminance 103.03lx"
```

The device advertises `40 0010 02 220b 5300 ff04` — die temperature, then the
text object at **length zero**, then a bitmask pointing at it. That is §3's
write-only placeholder on real hardware: the screen's contents never leave the
device, and there is no confirmation to be had. `push_text.py` reads the sketch's
own variable back instead, which is a debugging aid and not a protocol feature —
worth remembering when reading its output as if it were proof.

**D-017 needs qualifying.** It concluded the ceiling is MTU−3, from 48
characters at MTU 53 on a Puck.js. On this board `tools/text_limits.py` gets
**126 characters** through, and stops there because 128 is the module's
`maxWriteLength` default — `0x53`, a length byte, and 126 bytes of text. So the
MTU binds on some stacks and the device's own RAM budget on others, and a
receiver cannot assume either. Both are worth probing before deciding what a
device can be sent.

### Two things this board cannot do

- **No crypto at all.** `AES` is undefined and `process.env.MODULES` lists only
  `timer,Flash,Storage,heatshrink,neopixel`, so AESCCM has nothing to build on
  and an encrypted sketch cannot run here. Encryption is a per-firmware
  capability, not a per-project one.
- **No `E.getBattery()`** — that is a Puck.js function. The example reports the
  nRF52 die temperature instead.

---

## D-036 — The text platform, using what Home Assistant already has

**Status:** implemented and verified on hardware 2026-09-14. First half of T2.1.

Home Assistant already has the entity for this — `text`, with its
`text.set_value` service — so nothing was invented. A writable BTHome text
object becomes a `text` entity, and setting it sends one write of §4.2.

Verified end to end on the nice!nano with its SSD1306:

```
text.set_value "Salut JP depuis HA"   -> service returns in 0.34s
the entity reads back "Salut JP depuis HA"
the device's own variable reads "Salut JP depuis HA"
```

### The state is what was sent, and says so

§3 forbids applying the confirm/revert model to a write-only object, and this is
the first platform where that bites. Three consequences, each deliberate:

- **The entity's value is read out of the base class's optimistic value**, not
  kept in a field of its own. The first version did keep a separate copy, and a
  test caught what that costs: a write that never reached the device left the
  entity still displaying the text, because `_revert()` clears the optimistic
  value and knew nothing about the copy. One source of truth, and a failed write
  takes the text down with it.
- **`_write_finished` no longer opens a confirmation window for a write-only
  object.** It would have expired every time — the device advertises a
  zero-length placeholder for ever — and the entity would have dropped back a
  second after each write.
- **The state is unknown until something is sent, including after a restart.**
  No `RestoreEntity`: restoring a remembered value would assert something Home
  Assistant cannot check, and this entity's whole character is that it cannot
  check.

### What is not enforced, and why

`native_max` is 255, which is the BTHome length byte's limit rather than the
link's. The real ceiling is the smaller of the negotiated MTU minus framing and
the device's own `maxWriteLength` — 48 characters on one board, 126 on another
(D-017, D-035). Neither is knowable from the platform, so an over-long write
fails and is reported rather than being prevented by a guess.

---

## D-037 — T2.1: the object↔platform table, and the list it replaces

**Status:** written and implemented 2026-09-14. `spec/PLATFORMS.md`.

The mapping is now a document rather than four ids in a dict, and it is
**derived from `bthome-ble` at runtime** — `protocol.describe()` classifies an
object from upstream's own table, so this project never keeps a copy of BTHome's
object list to go stale. Of 95 objects: 59 numeric, 28 binary, 3 event, 1
string, 1 raw, 3 metadata.

### The switch platform was wrong, and in an interesting way

It exposed four binary classes — `generic`, `power`, `light`, `lock` — on the
reasoning that a `motion` switch is nonsense. It is, but the conclusion did not
follow. **A device does not declare an object writable by accident**: the bit
costs it a byte of advertising and a GATT service. A device advertising a
writable `garage_door` has a garage door, and refusing it made that device
unusable in the name of protecting its owner from it.

All 28 binary classes are now offered, named after the BTHome class. A device
that declares something strange presents as something strange, which is the
truthful outcome rather than a curated one.

### Numbers get their bounds from the encoding, and say so

Range, step and unit come from the object's width, signedness and factor: a
2-byte unsigned object with factor 0.01 offers 0 … 655.35 in hundredths.

These are the *encoding's* limits, not the device's. BTHome gives a device no
way to say its dimmer stops at 100, so the slider reaches 655.35 and the device
is entitled to reject the write. Not a defect to paper over with a guess —
documented instead, in `PLATFORMS.md` and in the platform's own docstring.

### Left open rather than invented: light + brightness

The task asks for a `light` with a brightness slider. **BTHome has no way to
express which level belongs to which light** — no grouping, no parent id. The
options (adjacency as a convention, a new object id, or leave them apart) all
have costs, and choosing is a protocol decision, not an implementation one
(rule 2). Written up in `PLATFORMS.md` for the owner and Gordon. Until then a
writable light is a switch and a writable level is a number, unpaired.

### A harness bug the new tests exposed

`fast_confirmation`, which shrinks the confirmation window, was an autouse
fixture declared in `test_switch.py` — so it applied only there. The number
tests ran against the production ceiling: two minutes for the suite, and a
revert test that timed out instead of reverting. Moved to `conftest.py`.

Worth remembering generally: an autouse fixture in a test module is not a
property of the suite, and the failure looks like the code being slow rather
than the harness being scoped wrongly.

---

## D-038 — T2.1 complete: the button platform, and a hole in §4.3

**Status:** implemented 2026-09-14. T2.1's four platforms are `switch`,
`number`, `text`, `button`.

A writable event object becomes **one button per value of its vocabulary**, read
from `bthome-ble`: seven for a button object, two for a dimmer. The same
reasoning as the switch platform's widening — the vocabulary is BTHome's, and
picking a favourite from it would make the rest unreachable.

Buttons never confirm. The entity base gained an explicit `_confirms` flag for
it: write-only objects are detected from the payload, but an event object is
fixed-length and looks ordinary, so nothing in the bytes says §6 cannot apply.
Without the flag every press would have logged a revert warning a second later.

### §4.3 promises a no-op that one object does not have

§4.3 says an event object is left alone by sending its "none" value, `0x00`.
Checked against `bthome-ble`'s own vocabulary:

```
0x3A button   0x00 = none
0x3C dimmer   0x00 = none
0x3B command  0x00 = off        <- a real command
```

Since a write carries *every* writable object (§4.2), a device declaring a
writable command alongside anything else cannot have that other thing written
without also sending the command something — and with the current wording that
something is `off`. Toggling a light would switch something off as a side
effect, silently, and the protocol would call the write correct.

**Not fixed here.** §4.3 is co-designed, so this is written up as
`for-gordon.md` §12 with three ways out. Meanwhile `0x3B` is not offered as a
control and `no_op_value()` refuses it rather than guessing — declining is the
conservative reading, not a decision.

This is the second time the event class has turned out to be looser than the
specification assumed; D-009 was the first. Both were found by implementing
against a real vocabulary rather than against the prose.

---

## D-039 — T2.2 on hardware: position really is the address

**Status:** verified 2026-09-14 on the Puck with three writable lights.

`espruino/examples/three-lights.js` advertises three `light` objects sharing one
object ID, and `tools/multi_instance.py` checks the claim §2.1 rests on. Both
sides count independently — a host reading a bitmask, a device that has sorted
its own objects — where every previous test had them counting the same way by
construction against a fixture.

```
declared writable: 3 objects at positions (2, 3, 4)
position 0: [0,0,0] -> [1,0,0]  (1e011e001e00)   ok, advertised [1,0,0]
position 1: [1,0,0] -> [1,1,0]  (1e011e011e00)   ok, advertised [1,1,0]
position 2: [1,1,0] -> [1,1,1]  (1e011e011e01)   ok, advertised [1,1,1]
desynchronised write (0f001e011e01)              ok, refused, unchanged
```

The last line is risk #8 on hardware: an object ID that does not match the
layout loses the whole write rather than the part the device understood.

What makes this worth running rather than only unit-testing is the shape of the
failure it looks for. Positional addressing does not fail with an error — it
switches the wrong light and reports success.

### And it found a real defect, which fixtures could not

With three lights on the air, Home Assistant showed a
`number.bureau_mobilesensf7b9_packet_id` — a slider for BTHome's packet counter.
Its unique id was `…-4`, the same position as one of the lights.

The live parsing is correct; the entity is debris from some earlier moment. But
the mechanism it proves is the point: **a declaration bit addressing the packet
id parses into a perfectly ordinary object**, and the number platform will
happily build a control from it. `PLATFORMS.md` had already written down that
the protocol's own fields are never controls; nothing enforced it.

Now one gate does, `protocol.controllable()`, which every platform passes
through — so the rule lives once rather than four times, and a fifth platform
inherits it.

The `bitmask-beyond-object-count` and `declaration-marks-itself` fixtures
covered the *malformed* cases. This was the case where the declaration is
well-formed and points somewhere it should not, which no fixture described
because no fixture was written for a device that is merely wrong rather than
broken.

---

## D-040 — T2.3: availability, measured by cutting the power

**Status:** verified 2026-09-14, with the rail under program control (D-032).

The half of T2.3 that had never been run, because until this week it needed
someone to pull a battery.

```
ooty off
  t+  1s   switch.…_light  off
  t+214s   switch.…_light  unavailable
ooty on, sketch redeployed
  t+  1s   switch.…_light  off
```

**Unavailable after 3 min 34 s**, and available again on the first advertisement
after it comes back. The delay is Home Assistant's own Bluetooth tracker, not
ours: `async_track_unavailable` decides when a device has gone quiet, and this
integration only listens. Worth knowing as a number rather than a promise —
nothing here makes a device disappear faster than that, and a user watching a
switch after unplugging something will wait a few minutes for it to grey out.

The device-merge half of T2.3 was already verified (D-025): one device card,
`bthome`'s sensors and this integration's switch on it.

### A consequence of the RAM deployment worth stating

The device came back on the rail and stayed unavailable, because there was
nothing to come back to: with the application in RAM and `.bootcde` erased
(D-032), a power cut wipes the program. That is the protection working as
intended — a sketch that breaks the radio is undone by a power cut — and it is
also why "unavailable on power-off" needed a redeployment to test its other
half.

For a device meant to run unattended, `--to-flash` puts the sketch in
`.bootcde` and a power cut becomes a reboot instead. The bench wants the
opposite, which is why it is not the default.

---

## D-041 — T3.2: the receiver half of §5, and the failure that has no symptom

**Status:** implemented and verified on the Puck 2026-09-14. Phase 3 complete.

Home Assistant now speaks §5: it reads encrypted advertising, seals its writes
with §5.1's write nonce, persists the counter §5.2 requires, and resynchronises
when it has fallen behind. All 16 test vectors reproduce through the
integration's own code.

### Encryption changes what discovery can see

For a plain device the declaration is in the advertising. For an encrypted one
**the only readable byte is the device-information byte** — everything else,
including whether the device has anything writable at all, is inside the
ciphertext. So the flow asks for the bindkey first and decides afterwards, and
the key is proved by decrypting an advertisement the device has already sent
rather than accepted on trust:

```
offered:      Puck.js f7b9 (C8:80:32:AD:F7:B9)
wrong key  -> step bindkey, error wrong_bindkey
right key  -> step confirm -> entry created
```

This also fixed a gap the plain path had hidden: `async_step_user` filtered
candidates by their declaration, so an encrypted device could be *discovered*
and never added by hand.

### The counter failure is invisible from both ends

The bench device had a persisted write counter of 73238 from earlier hardware
tests. A freshly configured Home Assistant starts at 1, so every write was
refused as a replay — and §6 gives a device no way to say so. From the user's
side: a switch that flicks on and returns to off, for ever.

That is what `note_unconfirmed()` is for. Two consecutive writes that are
delivered, followed by advertisements that do not change, and the counter jumps
forward by 100 000. Verified end to end:

```
stored counter 130 -> two unconfirmed writes -> stored counter 100133
next write accepted; the device's own counter advanced to 100135
```

Forward is the only safe direction, and it costs nothing: a device MUST accept a
jump, MUST refuse a repeat, and 32 bits is a century of writes.

### I misread my own test, twice

Worth recording because the mistake is built into the thing being tested.

The first run of four toggles "succeeded" — each command was followed 12 seconds
later by the state I had asked for. It had not succeeded: the entity was still
showing its optimistic value, because the confirmation ceiling is 60 s and I had
looked before it expired. Decrypting the advertising directly said `light:
False` throughout.

**An optimistic entity looks exactly like a working one.** Every test of this
protocol has to read the device rather than the receiver, and I have now written
that down twice (D-039 said the same about positional addressing) after failing
to apply it.

## D-042 — A bindkey outlived the firmware that needed it  [INCIDENT]

**Status:** found and guarded 2026-09-15, after the owner reported that the
Light button in Home Assistant no longer lit the LED.

Nothing was broken. Every part in isolation was healthy, which is what made it
take a diagnosis rather than a glance:

- the Puck was advertising `40 00 01 01 64 05 96 28 00 1e 00 ff 08` — packet id,
  battery, illuminance, light at 0, and `ff 08` declaring position 3 writable
- its GATT table carried `2faa0001…` / `2faa0002…` with write properties
- the integration deployed on the Home Assistant share was byte-identical to
  the repository
- writing `1e 01` directly to the characteristic was confirmed in 219 ms

The mismatch was in the config entry. It still held the bindkey from T3.2, when
the Puck ran the encrypted example; the Puck had since been reflashed with the
plain one. `_write_now` sealed every write because a key was configured, without
ever asking whether the device was still using one. The Puck read the sealed
payload as ordinary BTHome objects, failed, and rejected the whole write per
§4.2 — correctly, and in total silence.

**The asymmetry is the bug.** The opposite case was already handled: no bindkey
plus encrypted advertising is logged. A bindkey plus plaintext advertising had
no branch at all, so the only symptom available to the user was "the control
stopped working". That is the same shape as D-029, D-039 and D-041: this
protocol's failures are quiet by construction, and every one of them has to be
given a voice deliberately.

**The guard.** The coordinator now tracks `advertises_encrypted` from the
device-information byte of the last advertisement. When a key is configured and
the device is demonstrably advertising in clear, the write is refused with a
message naming both facts and the two ways out.

`None` is treated as "not yet known", not as "plain": refusing before the first
advertisement arrives would break the opening write of every session.

**Why refuse rather than downgrade.** Sending plaintext instead would have made
a stale bindkey self-healing, and would have fixed this incident with no
intervention. It is refused because an attacker able to make a keyed device
appear to advertise in clear would then be handed unsealed writes. The choice is
behind `ALLOW_PLAINTEXT_DOWNGRADE` in `const.py` — **[DECISION]** the owner may
overturn it; it is receiver policy, not part of §5.

## D-043 — The device was holding the connection, and every symptom pointed elsewhere  [INCIDENT]

**Status:** understood and cleared 2026-09-15. Cost: a Home Assistant restart, a
host reboot, two integrations disabled and re-enabled, all of them irrelevant.

Home Assistant could not write to the Puck. What it logged was:

> `Failed to connect after 9 attempt(s): No backend with an available connection
> slot ... The proxy/adapter is out of connection slots or the device is no
> longer reachable`

Both halves of that sentence were false. The adapter had three free slots of
five, and the device was advertising at RSSI -56 with `connectable: true`, heard
0 s earlier. The message is `bleak_retry_connector`'s generic blurb appended
after N failures, and it describes the receiver because that is the only side it
can see. The actual state -- **the peripheral already has a central, and an
Espruino accepts one** -- has no representation in it at all.

Chasing the receiver cost the whole evening:

- restarting Home Assistant: no change
- reloading all four Bluetooth entries: no change
- disabling the `espruino` integration (4 entries), suspected of holding the
  Nordic UART link: no change, and it was innocent
- disabling the relay automation that writes to the nice!nano continuously: no
  change
- rebooting the Home Assistant OS host: cleared two genuinely stale BlueZ
  allocations that had survived a Home Assistant restart -- and still did not
  fix the write

One power cycle of the Puck fixed it. First write afterwards: 3.1 s, then four
more at 3.0-3.4 s.

**The likely holder was this workstation.** The bench tools connect over BLE
from Windows, and Windows keeps an ACL link open well past `disconnect()`. That
also explains the one observation that should have redirected me hours earlier:
*direct writes from Windows kept working while Home Assistant never could*. I
read that as "the device is fine, so the fault is in Home Assistant". It was
evidence of the opposite -- the link was held here.

**The rule this yields.** A local BLE tool run can lock Home Assistant out of a
device indefinitely, and it presents as a receiver fault. Before blaming the
receiver, power-cycle the device. It is thirty seconds against an evening.

**What it did not turn out to be.** The coordinator does not leak connection
slots: with the relay automation running again, the nice!nano's slot is taken
and released normally, and only the `led_ble` device stays allocated -- which it
does by design. That suspicion is closed.

**What remains open.** The three ESPHome Bluetooth proxies are `loaded` as
integrations but register no scanner: every diagnostic said `1 scanner(s)
registered, 1 scanning, 1 connectable`. A working proxy would have given the
Puck a second connectable path and this incident would have been survivable
rather than total. Owner's call, outside this project.

## D-044 — T2.4 was finished without ever being written down

**Status:** audited and closed 2026-09-16. No code changed; this entry exists
because the task did not have one, and a masterplan whose record disagrees with
its repository is worse than one that is merely behind.

T2.4 asks for four things, and each is already carried by a named test rather
than by a claim:

- **Timeout and revert.** `test_an_unconfirmed_write_reverts` writes, then keeps
  the device advertising *the old value* four times. The entity goes back to
  what the device says and the log names the reason. That is §6.4 exactly: the
  device was heard from, and it did not obey.
  `test_a_write_that_never_reaches_the_device_reverts_at_once` covers the other
  half, where the write never lands, and reverts without waiting out a window
  that has nothing to wait for.
- **Warning surfacing.** The revert asserts on `caplog`, so the message is part
  of the contract rather than a courtesy. (Its promotion to the logbook belongs
  to T4.1, not here.)
- **Batching into one write-all.** `test_rapid_toggles_coalesce_into_one_write`
  spams three commands and asserts the device received exactly `["1e00"]` — one
  connection, not three. `test_a_single_click_is_not_delayed_by_the_debounce`
  guards the other direction, because a trailing debounce would have paid for
  that with the common case (D-020).
- **Stateless write-only paths.** `test_a_write_only_object_is_never_suppressed`
  — a trigger has no advertised value to compare against, and re-sending it is
  the entire point.

The confirmation window itself is covered beyond the acceptance criterion:
`test_the_confirmation_window_follows_the_advertising_interval`,
`test_a_deaf_host_waits_out_the_ceiling_instead_of_the_window` and
`test_a_heard_device_is_written_off_after_the_window_not_the_ceiling` separate
the three cases that a single fixed timeout would have conflated.

**Why it slipped.** T2.4 was implemented incrementally while chasing other
tasks, so it never had the moment of completion that produces a decision entry.
The lesson is small and worth keeping: a task that is finished in passing is a
task nobody can later prove was finished.

## D-045 — The nice!nano has AES now, and the vectors prove it on the board

**Status:** verified 2026-09-16, after the owner rebuilt the firmware.

Its build previously reported `timer,Flash,Storage,heatshrink,neopixel`. It now
reports `timer,Flash,Storage,heatshrink,crypto,neopixel` on Espruino 2v29.242,
board `NICENANO`, and `require("crypto").AES` is a function.

That list is necessary and not sufficient, so the vectors were run on the board
itself: **all 12 pass**, four advertising and eight write. Both directions, the
zero and maximum counters, the forward jump, and the two replay cases.

`tools/verify_device_ccm.py` is that check, made repeatable. It uploads
`AESCCM.js`, feeds it every vector whose MIC is meant to verify, and compares
against `test-vectors.json` — the same contract both test suites consume
(CLAUDE.md rule 6). The negative vectors are deliberately excluded: they test
that a *receiver* refuses something, which says nothing about this firmware's
arithmetic.

**Why a module list is not an answer.** Three of this project's encryption
findings were invisible from the build flags and only appeared on hardware: AES
CTR mode ignores its `iv` (D-027), `AES.encrypt` fails on large inputs long
before memory runs out (D-028), and the radio refuses payloads that §2.3's
arithmetic says should fit (D-030). A board that lists `crypto` can still be a
board that computes the wrong thing.

**Two things the reflash took with it.** `require("Storage").list()` came back
empty, so the modules and the OLED application are gone — the board advertises
as a bare `Espruino b216` with nothing but the Nordic UART. Anything depending
on it, including the illuminance relay automation in Home Assistant, is pointing
at a device that no longer runs the code. Redeploying is a `tools.espruino_deploy`
away and was deliberately not done here: the question asked was about the
firmware, and installing an application answers a different one.

## D-046 — This firmware drops the service-data UUID, and the name is not free  [INCIDENT]

> **Superseded in part, 2026-09-17.** Gordon pointed out that `2v29.242` was an
> intermediate build and that current master is fine. Verified on the same
> nice!nano reflashed to `2v29.396`: `NRF.getAdvertisingData({0x180F:[1,2,3]},
> {showName:false})` returns `2 1 6 6 22 15 24 1 2 3`, UUID present. So the UUID
> finding below was a transient bug, not a property of master, and "appears
> unreported" was wrong — it was already fixed. The raw-form workaround is not
> needed. **Re-measured on 396 (2026-09-17, D-049):** the name is still refused
> rather than shortened. Service data accepted: 5 bytes with the name
> ("Espruino b216"), 20 without -- two fewer than on `.242` in both cases, the
> two bytes of the UUID that `.396` emits again. `showName: false` stays
> necessary on this board.

**Status:** measured on the nice!nano, 2v29.242, board `NICENANO`, 2026-09-16.
Two separate findings, both from one failed deployment. The first is ours to
work around; the second is not ours at all.

### The name is part of the 31 bytes, and §2.3 never said so

Redeploying `oled-text.js` failed three times with
`the radio refused 10 bytes of service data: ERR 0x9 (INVALID_LENGTH)`. The same
application advertised the same 10 bytes on this board before it was reflashed.

Measured by bisection on the device, asking the radio to accept service data of
each length until it stopped refusing:

| `showName` | service data accepted |
| --- | --- |
| true | 7 bytes |
| false | 22 bytes |

The difference is 15 — `2 + len("Espruino b216")`, the whole name. This firmware
does **not** shorten the local name to make a packet fit; it refuses the packet.
A Puck.js gave back only 3 bytes for the same switch (D-030), so it evidently
does shorten. The reflash is what changed it here: the board previously
advertised as `WL2Home`, seven characters, and came back with the thirteen-
character default.

The arithmetic that actually holds on this board, with 31 bytes to spend:

    3  flags
    4  manufacturer data -- Espruino's company ID, always present
    4  service data header and UUID
    2 + len(name), if showName

leaving 20 bytes without a name and 5 with this one. §2.3 counts neither the
manufacturer data nor the name, which is the whole of why its budget is
optimistic (D-030) — now with the two missing terms named.

**Changed.** `oled-text.js` sets `showName: false`, and says why. The guard in
`refreshAdvertising` now drops the name in its retreat unconditionally: the
fallback packet exists to keep a device findable after a rejection, and a
fallback that can itself be refused is not a fallback. Being findable matters
more than being named.

### The bigger one: `NRF.setAdvertising` omits the 16-bit UUID

With the name gone the application ran, advertised 10 bytes, and Home Assistant
still showed nothing. The air says why. Compare the two boards:

    puck   len=16 type=0x16  d2 fc 40 00 d6 01 64 05 ef e7 00 1e 01 ff 08
    nano   len=11 type=0x16  40 00 78 02 f0 0a 53 00 ff 04

The nano's service-data structure has **no UUID**. The BTHome payload is byte-
for-byte correct and begins where `d2 fc` should be, so a receiver reads the
first two bytes as the UUID and files the device under `0x0040`. No BTHome
receiver will ever recognise it.

It is not the key form. Asked directly, every spelling produces the same
UUID-less structure, including a standard UUID that has nothing to do with this
project:

    {0xFCD2:[1,2,3]}   ->  02 01 06 04 16 01 02 03
    {"FCD2":[1,2,3]}   ->  02 01 06 04 16 01 02 03
    {64722:[1,2,3]}    ->  02 01 06 04 16 01 02 03
    {0x180F:[1,2,3]}   ->  02 01 06 04 16 01 02 03

**A workaround exists and is proven.** `NRF.setAdvertising` also takes a raw
array of AD structures, and that form emits the UUID correctly:

    NRF.setAdvertising([2,1,6, 13,0x16,0xd2,0xfc, ...payload], {showName:false})
    ->  02 01 06 0d 16 d2 fc 40 00 77 02 f0 0a 53 00 ff 04

### The cause, from Espruino's own changelog

The owner was right to send me to the changelog. The entry is in the
**unreleased** section, above `2v29`, which is exactly what a firmware calling
itself `2v29.242` is built from -- a master build 242 commits past the release:

> **BLE: switch to our own code for creating advertisement packets (shared
> across all platforms).**

and, in the same batch:

> BLE: Allow `NRF.getAdvertisingData({},{name:"foo"})` to force a name for a
> specific advertising packet

So the packet builder was rewritten, and both observations above are that
rewrite: the 16-bit service-data UUID is no longer emitted, and the local name
is no longer shortened to make a packet fit. The Puck.js, on a release build,
still has the old builder and is unaffected -- which is why two boards running
the same module disagree.

A search of the Espruino issues, discussions and forum turned up nothing about
the missing UUID, so this appears to be unreported. It is worth reporting: it is
not a BTHome problem, and any Espruino sketch advertising service data on a
master build is silently producing packets no receiver will match. The evidence
to send is the four-line probe above -- `{0x180F:[1,2,3]}` is the persuasive
one, because it has nothing to do with this project.

**[DECISION] Not taken unilaterally.** Moving the module to the raw form would
make it responsible for the flags, the name and the manufacturer data on every
board — including the ones where the object form works — to route around what
looks like a firmware regression. That trade belongs to the owner and to Gordon,
and the evidence above is what the question should be asked with.

Until then the nice!nano cannot carry BTHome on this build. The Puck is
unaffected.

## D-047 — A single-adapter host *can* scan while connected; that was WinRT

**Status:** measured 2026-09-16, after enaon challenged the claim in
espruino#8013. He was right.

The claim, repeated in seven places and posted to the discussion, was that a
host with one Bluetooth adapter cannot scan while it is connected, and that this
is where the seconds before a confirmation go. It came from the Windows host,
where the adapter did go silent around a connection and took four to eight
seconds to recover — and was then stated as a property of single-adapter hosts.

Measured on the Home Assistant Raspberry Pi (BlueZ), three runs of 15 s each.
The control is a device nobody connects to (`WL2-Time`), so it isolates the
host's scanning from anything the Puck does while connected:

| run | control, idle | control, during a write to the Puck |
|---|---|---|
| 1 | 15 adverts, widest gap 1.52 s | 12 adverts, widest gap 4.03 s |
| 2 | 12 adverts, 3.03 s | 13 adverts, 2.92 s |
| 3 | 12 adverts, 3.02 s | 12 adverts, 3.45 s |

The control keeps arriving at its usual rate; the one 4 s gap is inside the
idle spread. **The Pi scans while connected.** The Puck itself is heard *more*
during a write, which is its fast advertising after a connection (D-014).

**What survives.** The seconds are real; they are connection setup — waiting for
a connectable advertising event, connecting, the MTU exchange, the write, the
disconnect — which is what the latency figure already said ("the median is
connection-bound"). The designs the claim justified stand on other grounds:
the confirmation window still counts evidence rather than only time (WinRT
exists, and a device can be out of range or asleep), and `whenConnected` still
keeps a device audible to anyone listening.

**Corrected** in `coordinator.py`, `entity.py`, `tools/bthome_write.py`,
`tools/closed_loop.py`, and annotated rather than rewritten in D-010,
D-015, and `docs/first-use-case.md` §5.4, so the
record shows what was believed and when it stopped being.

## D-048 — Protocol v2: a list of writable types, one characteristic each, no advertised state  [SPEC, agreed with Gordon]

**Status:** agreed in espruino#8013 on 2026-09-17/18, written into
`PROTOCOL.md` 2.0-draft.1.

### How it was reached

1. Gordon asked whether events should be writable at all, since `0x3B command`
   has no "none" value and version 1's write-all forced one onto it.
2. The owner proposed four generic actuator objects (switch, level, action,
   text). Gordon declined, rightly: typed objects — icon, unit, zero
   configuration — are what BTHome is for, a thermostat target belongs in °C, and
   one object ID is easier to obtain than four. The proposal also used IDs
   `0xF0`–`0xF2`, which are taken; the free-ID check had covered only the
   measurement table.
3. Gordon proposed instead: one GATT characteristic per writable entity, and a
   `0xFF` object listing the writable object IDs, with no advertised values and
   the write response as validation.
4. Agreed with two additions from the owner's side: the object ID stays in each
   write as a desync guard, and BTHome's existing settings revision (`0x65`) plus
   readable characteristics cover devices whose values change by themselves. A
   read-after-write was proposed and dropped at Gordon's suggestion: write with
   response already says the write was delivered, and applying it is the
   device's job.

### What changed from version 1

| Version 1 | Version 2 |
|---|---|
| `FF <bitmask>` marking positions of advertised objects | `FF <id> <id> …` listing writable types |
| Writable values advertised; advertising confirms a write | Not advertised; write response is the evidence |
| One characteristic, write-all in packet order | One characteristic per entry, one object per write |
| No-op values (§4.3), write-only rules (§3) | Gone: only the entry written is touched |
| Events not safely writable (`0x3B`) | Events writable: a write triggers only its own entry |
| Confirmation window and revert (§6) | Assumed state, or read state via `0x65` |
| Up to 8 writable objects | Limited only by advertising space |

Gone with them: the packet-id shift in the bitmask, the fixed-length write-only
ambiguity, and the `0x3B` no-op problem.

### Choices made while writing it

Not discussed in the thread; implementation-level, recorded so they can be
questioned:

- **UUIDs.** Service `2FAA0000-…`, entry *k* at `2FAAkkkk-…`, as Gordon sketched.
- **Values keep BTHome's own encoding**, including the length byte of
  variable-length objects, even though a write's length is known. One encoder per
  side for advertising and writes, and "no new data format" stays literally true.
- **Reads are sealed too**, with device-information byte `0xFE` in the nonce, so a
  read, a write and an advertisement can never be replayed as one another.
- **No automatic resend of an acknowledged write**, because toggle and step are
  not idempotent.
- **A device must not bump `0x65` for a write it received**, so writing does not
  trigger a pointless re-read.
- **Entries a receiver does not know are still counted**, so the characteristic
  numbers of the entries after them do not shift.

### What it costs

The version 1 implementations, tests, vectors and several documents are
obsolete. Worth it: the receiver loses its most intricate machinery (the
confirmation window, D-010/D-011; redundancy suppression, D-020; no-op
composition), and the device loses write-all parsing and the capacity limit of
eight. What is lost is the observation of state by listening, which §3 of the
specification replaces for the devices that need it.

## D-049 — Protocol v2 on hardware: what held, and two bugs it found  [VERIFY]

2026-09-17. Puck.js `C8:80:32:AD:F7:B9` (2v27), Windows host for the bench tools,
Home Assistant 2026.7.4 through the ESP32 proxy `esp32-bluetooth-proxy-1f1020`.

**Held.**

| Check | Result |
|---|---|
| `tools.bthome_write --payload 1e01` on light-loop | acknowledged; connect 1.7 s, write 16 ms |
| `tools.closed_loop` | illuminance 103 → 595 → 103 lux, 5.8× |
| `tools.reject_matrix` | `objectid_mismatch`, `truncated` ×2, `trailing_bytes`; lamp unchanged |
| `tools.multi_instance` on three-lights | entries 1, 2, 3 each moved only their lamp; `0f00` on entry 1 refused |
| button-light: write then read | read `1e01`; revision unchanged by the write (§3.2) |
| button-light: local toggle | revision 0x50 → 0x51, read `1e00` |
| HA: first sight after restart | state read from the device, not assumed |
| HA: switch on | LED on, `lamp.on` true |
| HA: local toggle | HA shows `off` ~2 s after the bench tool let go of the link |

Advertising of light-loop is `40 00 <pid> 01 <batt> 05 <lux×3> FF 1E`, 11 bytes.

**Bug 1 — a failed re-read counted as done.** The coordinator recorded a new
settings revision as seen *before* reading it. An Espruino device serves one
central at a time; the read fired while the bench tool held the link, failed,
and the state stayed stale until the next change. Now the revision moves only
after a successful read, and a failed read is retried on a later advertisement
once `READ_RETRY` (10 s) has passed. Test:
`test_a_re_read_that_fails_is_tried_again_on_a_later_advertisement`.

**Bug 2 — deploying from RAM leaked the previous sketch.** `espruino_deploy`
stopped timers but did not `reset()`, so globals, `NRF.on()` listeners and the
module cache piled up. After three deployments the Puck had 109 of 2630 blocks
free and `require("BTHomeWritable")` failed with "Got UNFINISHED TEMPLATE
LITERAL" — an out-of-memory symptom, not a syntax error. After `reset()`, the
module plus a sketch leaves 1834 blocks free. The tool now sends `reset()`.

**Not yet on hardware:** an encrypted device on v2 (sealed write, sealed read
under 0xFE). Both sides consume the same vectors, including the read direction.

**Afterwards (same day).** The v1 entity-registry rows left in Home Assistant
(25 of them, unavailable or restored-only) were removed, and the v2 entities
renamed to the old IDs, so the `Puck illuminance -> OLED` automation reaches the
nice!nano again: the sketch reported `shown = "Lux 102.47"`. The nice!nano runs
`oled-text.js` from flash on 2v29.396, 8 bytes of service data, 10974 blocks free.
The name budget on 396 is recorded under D-046.

## D-050 — Response time against the advertising interval, and what the sweep exposed  [VERIFY]

2026-09-18, both devices, seven intervals from 100 ms to 10 s, three "first"
commands (each after 35 s of silence, past `fastTimeout`) and four or five
following ones per interval. Tools: `tools/latency_sweep.py` from the bench
host, `tools/latency_sweep_ha.py` through Home Assistant. Numbers, tables and
the figure: `docs/measurements.md` §1.

**The headline is the one D-021 and D-024 already implied, now with a curve.**
The interval is a cold-start dial: commands that follow one another land in
0.35–1.7 s at every interval, while the first after a quiet period grows faster
than the interval does — 0.9 s at 100 ms to 45 s at 10 s from the bench host,
1.0 s to 8.2 s through Home Assistant. At a 2 s interval, 57–82 % of a first
command is spent waiting to catch an advertisement.

**New: fast advertising speeds the radio, not the packet.** `goFast()` drops the
advertising interval to 100 ms, but `st.timer` keeps rebuilding the packet at
`st.interval`, so a sensor value is re-read at the *idle* rate whatever the
radio is doing. It shows up as the one curve that does not flatten: the Puck's
witness is its advertised illuminance, and its following commands climb to 18 s
at a 10 s interval, where the nice!nano — witnessed on its own console — stays
at 1 s. Nothing is wrong with either number; they measure different things.

Worth deciding later, not now: whether `goFast()` should also rebuild faster.
It would make an advertised actuator effect visible within the fast window, at
the cost of re-reading sensors more often exactly when the radio is already
costing more.

**Failure rate, stated rather than averaged away.** Seven of 49 commands to the
Puck through Home Assistant produced no effect, against two of 56 to the
nice!nano. Every one was logged on the entity ("the command did not reach the
device … Failed to connect"), so none was silent — which is what D-042 asked of
this integration.

**Method notes, because two of them cost an hour.**

- A witness must require a *transition*. The first version accepted the state
  the lamp already had, timing a command at nothing whenever it was sent where
  it already was, and drifting out of step after any failure.
- The bench host must be timed from *catching an advertisement*, not from
  `BleakClient(address)`: connecting by address alone answers "device not found"
  the moment WinRT's cache has gone cold, which at a 10 s interval is every
  time.
- The host's Bluetooth stack stopped opening connections part-way through, and
  cycling the radio through the Windows `Radio` API fixed it — no administrator
  rights needed. An earlier reading of "the host has gone deaf" was wrong: both
  devices were at a 10 s interval, so one packet in 25 s was correct. Judge the
  host by whether a connection opens, not by the packet count.
- The Puck stopped refreshing its advertising at one point — same payload, same
  packet id, minutes on end — and Home Assistant could then no longer reach it.
  `bw.setAdvertisingInterval()` restarted it. Nothing outside the device says
  this has happened except that it goes quiet, which is worth remembering before
  blaming a receiver.

## D-051 — A write now republishes at once, and that is worth about ten seconds  [T1.1]

2026-09-18, prompted by the owner asking whether an advertisement could be
forced rather than waited for. It could, and the module was not doing it.

**What was wrong.** `handleWrite` called `goFast()`, which dropped the
advertising interval to 100 ms and rebuilt the packet — but only when the rate
actually changed. The first write after a quiet period therefore republished at
once, and every write after it, with the device already fast, did not: fast
advertising repeats the packet the device already holds, so a sensor measuring
what the write did was not re-read until the next scheduled rebuild, which runs
at the idle interval. D-050 measured the consequence without naming the cause:
the Puck's advertised effect trailed its own write by up to 18 s at a 10 s
interval, while the nice!nano — watched on its console rather than on the air —
stayed at one second.

**The change.** `goFast()` now always rebuilds, and `handleWrite` reports a
refused packet through `onError` rather than letting it escape into `onWrite`.
One extra packet rebuild per write, at the moment someone is waiting for it.

**Measured on the Puck at a 10 s idle interval, on air, with a host scanner:**

| Write | Effect advertised after |
|---|---|
| first, device idle | 0.31 s |
| second, device already fast | 0.41 s |
| third | 0.42 s |

Before the change the second and third would have waited for the rebuild timer.
Home Assistant, on the same device with the link already open, showed the change
0.3–0.7 s after the write — so device and receiver together account for about a
second, and what remains in D-050's through-Home-Assistant figures is Home
Assistant establishing a connection, not the device answering.

**For the specification, not decided here (CLAUDE.md rule 2).** §7 lists what a
device must do and says nothing about when it must republish. A line such as
"a device SHOULD publish a fresh advertisement as soon as it has applied a
write, rather than at its next scheduled rebuild" would make this behaviour
part of the contract instead of a quality of this module. Worth putting to
Gordon, since it costs a device one packet rebuild per write and buys a receiver
the difference measured above.

## D-052 — The sweep, done properly: ten samples, a shorter ladder, medians  [VERIFY]

2026-09-18, at the owner's request: more samples, and stop at 4 s. Seven
intervals — 100, 200, 400, 700, 1200, 2000, 4000 ms, each about 1.8x the one
below — ten first commands and eight following ones per interval per device.
250 measurements. Tables and figure: `docs/measurements.md` §1.

**What the earlier three-sample runs could not say.** These distributions are
skewed: a connection attempt that misses its advertising window waits out
another interval, so every interval carries a few samples far above the rest.
On the nice!nano at 2 s the median first command is 1.90 s and the mean 4.30 s.
Three samples could not separate those, and `docs/measurements.md` now leads
with the median and prints the mean beside it.

**The owner's prediction, tested.** One to two advertising intervals for a first
command. Measured, the connect phase behaves as *a fixed cost plus about half an
interval*: on the nice!nano, 0.31, 0.40, 0.46, 0.56, 0.43, 1.86, 6.46 s across
the ladder — a floor near 0.3 s that has nothing to do with advertising, with
the wait for an advertising event taking over past about 1 s. As a multiple of
the interval that reads 3.1x, 2.0x, 1.15x, 0.80x, 0.35x, 0.93x, 1.61x: a small
multiple, never a constant, because which term dominates changes along the way.

**Following commands are flat** at 1–3 s everywhere, as `fastTimeout` intends.

**The Puck is not the nice!nano, and the difference is not the protocol.** Its
median connect time is three to five times longer at the same interval, and
**13 of its 125 writes stalled past 5 s inside `write_gatt_char`**, several
within milliseconds of 16.1 s — a timeout and a retry, not a slow device. The
nice!nano: 0 of 124. Same module, same proxy, same Home Assistant; what differs
is the hardware, a coin cell against USB, and the position in the room.
**Unresolved**, and a reason not to quote the Puck's figures as the protocol's.

**Three commands of 249 were never delivered**, all at 4 s, each logged on its
entity.

### Two tools came out of this

- `bw.setFastTimeout(ms)` on the module, the counterpart of
  `setAdvertisingInterval`. Every first-command sample has to wait out the fast
  window, so the 30 s default turned each interval into eight minutes of
  waiting; at 3 s the campaign went from two hours to forty-five minutes. The
  sweep sets it and restores 30 s afterwards. It does not touch what is
  measured — only how long it takes the device to return to its idle interval.
- `tools/summarise_latency.py`, which prints the tables from the raw samples,
  so a number in the document can be traced to the run that produced it.

## D-053 — The Puck's stalled writes were its LED, not the protocol  [VERIFY]

2026-09-18, on the owner's hypothesis: a coin cell has a high internal
resistance, an LED draws a few milliamps, and the radio transmits from the same
rail — so the stalls of D-052 might be the battery sagging rather than anything
in the link.

Tested with `espruino/examples/light-loop-no-led.js`, identical to `light-loop.js`
in everything a receiver can see — same entries, same intervals, same writable
light on 2FAA0001 — except that applying a write drives no pin. Same sweep, same
ladder, same receiver, immediately afterwards.

| Same Puck, same sweep | LED driven | LED not driven |
|---|---|---|
| Write, median | 141 ms | **36 ms** |
| Write, 90th percentile | 6636 ms | **37 ms** |
| Write, worst | 16153 ms | 4061 ms |
| Writes stalled past 5 s | 13 of 125 | **0 of 126** |
| Connect, median | 2.56 s | **0.39 s** |
| Commands never delivered | 1 | **0** |

The 90th percentile is the number that matters: with the LED, one write in ten
took more than 6.6 s; without it, 37 ms. That is a failure mode disappearing,
not a mean shifting. The several stalls within milliseconds of 16.1 s look like
a supervision timeout and a retry — consistent with the link dropping while the
rail sagged, not with a device that is merely slow.

**First commands without the LED**, 100 ms to 4 s: 0.34, 0.41, 0.53, 0.74, 0.42,
0.40, 0.43 s. The Puck is now faster than the mains-powered nice!nano, and the
figures stop climbing with the interval.

**What this changes.**

- D-052's Puck column measured a power supply, not a protocol. It stays in
  `docs/measurements.md` as the cautionary case, relabelled, with this run beside
  it. The nice!nano's figures are unaffected.
- A measurement of write latency on a device that actuates anything from a coin
  cell is measuring the cell. Any future latency work uses a device that drives
  no load, or one on mains.
- It also says something for the specification's readers rather than its text: a
  battery device that switches a real load should expect its own writes to be the
  least reliable moment in its life, and a receiver that reports failures plainly
  (D-042) matters more on such a device than on a powered one.

**Left unexplained:** at 1.2 s and above, the no-LED connect medians fall to 0.32
and then 0.10 of an interval — faster than the half-interval a fresh connection
should average. The proxy is probably reusing a recent connection. It does not
affect the comparison above, both runs having the same receiver, but it does
limit what the long-interval rows can say about the cost of catching an
advertisement.

## D-054 — The sweep, with the proxy out of the way and the phase sampled  [VERIFY]

2026-09-18, at the owner's request: measure without the ESP32 proxy, check that
nothing else is advertising faster, and add a random delay before each command
so the measurement cannot lock onto the advertising phase. All three changed the
result, and the third changed it most.

**What was wrong with the earlier runs.**

- *The proxy reused connections.* Some first commands opened a link in less than
  half an interval — faster than catching an advertisement allows. Disabling the
  ESPHome proxy (both its own entry and its Bluetooth entry) leaves Home
  Assistant on the Raspberry Pi's adapter, which hears the Puck at −56 dBm and
  the nice!nano at −63 dBm: weaker than the proxy's −38, and enough.
- *Every sample was taken at the same phase.* The idle wait was a fixed 5 s, so
  ten samples at one interval all landed at the same point of the device's
  advertising cycle — and that point is what decides how long the receiver
  waits. Each first command now waits the idle period plus a uniform random
  fraction of one interval; bursts get a smaller random gap so they cannot fall
  into lockstep with the receiver's write debounce.
- *The advertising was assumed rather than checked.* Verified on the air before
  starting: one BTHome train per device, nothing faster, observed gaps at
  0.98–1.01× the configured interval. A first check read 0.14× on the Puck and
  was wrong — it was taken inside the fast-advertising window, which the sweep
  shortens to 3 s and waits out before every sample.

**The result, 252 commands, no failures, no stalls.** Median connect time, in
seconds, across 100 ms → 4 s:

| | 100 ms | 200 ms | 400 ms | 700 ms | 1.2 s | 2 s | 4 s |
|---|---|---|---|---|---|---|---|
| Puck.js | 0.33 | 0.51 | 0.65 | 1.40 | 1.86 | 4.38 | 9.30 |
| nice!nano | 0.26 | 0.78 | 0.73 | 1.79 | 2.70 | 3.68 | 14.56 |

As a multiple of the interval both devices sit between **1.5× and 3.9×** with no
systematic trend — two firmwares, two payload types, agreeing within the spread.
That is the honest answer to "how long does a first command take": one or two
advertising events plus the connection's own handshake.

**A receiver-side finding.** Following commands are flat at about 1.9 s on both
devices, and the split says why: 1.4–1.6 s of it is this integration holding the
second command behind the first (`WRITE_DEBOUNCE`, D-020). The radio part is a
few hundred milliseconds. The warm path is bounded by the receiver, not by the
device or the interval — worth knowing before anyone tunes a device to improve
it.

Superseded runs are kept under `docs/data/archive/`: with the proxy, with three
samples, and with the LED driven (D-053).

## D-055 — The low-frequency clocks, and why they are not the story  [VERIFY]

2026-09-20, on the owner's hypothesis that the nice!nano connects less well
because its crystal is not properly tuned. Measured rather than argued.

**Drift against the host clock, over four minutes** (`getTime()` on the device
compared with `perf_counter()` on the bench host, through the serial console for
the nice!nano and the BLE console for the Puck):

| Device | Drift |
|---|---|
| Puck.js, nRF52832 | **+23 ppm** |
| nice!nano, nRF52840 | **−62 ppm** |

The nice!nano is three times further from nominal, which is the shape of the
owner's hypothesis. It is also far too small to matter here: 62 ppm of a 4 s
advertising interval is 250 µs, against scan windows measured in milliseconds
and a BLE sleep-clock requirement of ±500 ppm. It is three to four orders of
magnitude below the seconds the sweep measures.

**And the devices do not actually differ in connection cost.** Connect time as a
multiple of the interval, median per interval, from D-054:

| | 100 ms | 200 ms | 400 ms | 700 ms | 1.2 s | 2 s | 4 s |
|---|---|---|---|---|---|---|---|
| Puck.js | 3.35 | 2.54 | 1.62 | 2.00 | 1.55 | 2.19 | 2.33 |
| nice!nano | 2.56 | 3.92 | 1.81 | 2.56 | 2.25 | 1.84 | 3.64 |

Mean 2.23× against 2.65×, paired difference +0.43 with a standard deviation of
0.81 over seven intervals, and the sign changes twice. Not distinguishable from
zero on this data.

### Is it the nRF52832 versus the nRF52840?

No — the difference is in the board's clock configuration, not the chip family.
Read from the devices themselves (`peek32`, stable across repeated samples):

| Register | Puck.js | nice!nano |
|---|---|---|
| `FICR.INFO.PART` | `52832` | `52840` |
| `FICR.INFO.VARIANT` | `AAE0` | `AAD0` |
| `CLOCK.LFCLKSRC` | 0 = RC | 1 = crystal |
| `CLOCK.LFCLKSTAT` | `0x10000` = running, source RC | `0x10000` = running, source RC |

Both parts offer the same low-frequency options — an internal RC oscillator,
calibrated by the SoftDevice against the high-frequency clock, or an external
32.768 kHz crystal. The Puck.js asks for the RC, which is right for a board that
fits no crystal. **The nice!nano asks for the crystal and appears to be running
on the RC anyway**, which is what "not properly tuned" would look like at its
worst: an LFXO that never starts, and a silent fall back.

Two cautions on that reading. The CLOCK peripheral belongs to the SoftDevice, so
a register read from the application is indicative rather than authoritative;
and the way to settle it — driving LFXO by hand — is not worth doing on a device
that is part of a working bench. What is settled is the part that matters: both
clocks are within ±62 ppm, which is fine for BLE, and neither explains a
connection time measured in seconds.

**Where it will cost something** is power, not latency: a peripheral with a less
certain sleep clock must widen its receive windows around each connection event.
That is a battery question, and this project has not measured battery.

## D-056 — Signal level does change the first command, and by a lot  [VERIFY]

2026-09-20, on the owner's question of whether RSSI explains the difference
between the two devices. Unlike the clock (D-055), this one has a mechanism that
operates at the right scale: a central cannot connect until it catches an
advertising event, and an advertisement lost to a weak link costs a whole
advertising interval.

**The experiment.** One device, one position, one advertising interval (1.2 s),
ten first commands per setting, and the only thing that changes is the device's
transmit power. `tools/tx_power_experiment.py`.

| Transmit power | Heard at | First command, median | worst | Lost |
|---|---|---|---|---|
| +4 dBm | −44 dBm | **0.38 s** | 3.52 s | 0 |
| −8 dBm | −51 dBm | **0.67 s** | 5.29 s | 0 |
| −20 dBm | −66 dBm | **1.87 s** | 7.11 s | 0 |

**Twenty-two decibels multiply the median by five**, at a constant advertising
interval, and nothing is lost: this is not a link that fails, it is a link that
misses advertisements and waits out another interval each time. Roughly +0.3 s
per 7 dB at this interval, which is a quarter of an interval per 7 dB.

**And the two bench devices are far apart.** Measured in a single scan from one
receiver, so the comparison is fair: **Puck.js −42 dBm, nice!nano −62 dBm**. The
nice!nano radiates about 20 dB weaker although it sits closer to that receiver —
an antenna or matching property of that board, not of the protocol. At the
Raspberry Pi the gap is smaller, about 7 dB, which by the slope above predicts
the nice!nano being a few tenths of a second slower at a 1.2 s interval. D-054
measured it 0.84 s slower there: same sign, same order, and still inside the
spread of ten samples.

**So the ranking of causes for a slow first command is:** the advertising
interval first, the link budget second, and the device's clock nowhere (D-055).

### Two measurement notes worth keeping

- **Home Assistant's RSSI is not a measurement.** Its diagnostics reported −62
  then −65 dBm while the device's radiated level fell by 24 dB. It is whatever
  the last advertisement happened to carry, and the scanner had not caught up.
  The experiment therefore measures the level itself, with a scan.
- **A background run can outlive its completion notice.** The first attempt at
  this experiment was still driving the device's transmit power while a manual
  check drove it too; both readings were worthless. Killed and re-run. Worth
  remembering before trusting any bench result that overlapped another job.

## D-057 — The band is busy where it matters, and that is as far as the evidence goes

2026-09-20, on the owner's reading of D-056: if a merely 22 dB drop costs a
factor of five, the link margin must be going somewhere, and a noisy 2.4 GHz
band is the obvious candidate. Two measurements, one conclusive and one not.

**The band, surveyed from the bench host.** Five access points in 2.4 GHz, *all
of them on channel 1*, all at full signal, mean channel utilisation 33 %.
WiFi channel 1 spans 2401–2423 MHz. BLE advertises on 2402, 2426 and 2480 MHz,
so **one of the three advertising channels sits under a permanently busy
transmitter**, and the other 11 access points in range are on 5 GHz where they
cost nothing. That is a real, measured impairment of a third of the advertising
surface, and it is consistent with what D-056 found: a link at −66 dBm, which
should be comfortable against a −90 dBm sensitivity, behaving as if it were
marginal.

**The packet loss itself was not isolated.** The attempt: have the nice!nano
scan for the Puck's advertisements at a known 1 s interval, counting what
arrives, with the Puck at +4 and at −20 dBm. Alternating the two settings twice
gave 49 %, 47 %, 78 %, 78 % of the expected events — the same numbers for both
power levels, varying by run rather than by condition. The listener's own scan
duty cycle dominates, and at this distance 24 dB of transmit power changes
nothing it hears. Measuring reception properly needs a receiver whose scan
window can be opened fully, which Espruino's `NRF.setScan` does not expose.

**So:** the environment is demonstrably hostile on advertising channel 37, which
is a good explanation for D-056's steep dependence on level, and it remains an
explanation rather than a demonstration. What is measured stands on its own —
level matters, and by a factor of five over 22 dB — whatever the reason turns
out to be.

Worth noting for anyone reading the latency figures: they were taken in a
building with five strong access points parked on the one WiFi channel that
overlaps BLE's first advertising channel. A quieter site should do better, and
a site with access points on channels 1, 6 and 11 would do worse.

## D-058 — The size of a write is MTU−3, and fragmentation is out of scope  [DECISION, owner]

2026-09-20, ruled by the owner after asking whether a long text is sent as
several messages. It is not, and now the specification says so rather than
wishing otherwise.

**The rule (§4.4, rewritten).** A write carries one object in one ATT Write
Request, so at most `ATT_MTU - 3` bytes: the opcode and the attribute handle take
the other three. For a length-prefixed object two more are its own framing, so
text carries `ATT_MTU - 5` characters. A device may accept less, its
characteristic declaring a maximum of its own; the effective ceiling is the
smaller of the two.

**What changed.** Draft.1 said devices SHOULD support queued (long) writes "so
that text is not limited by the MTU". That was aspirational: D-017 measured a
payload above `MTU - 3` being refused outright by the stack, with no attempt at a
prepared write, and no implementation has ever done otherwise. The specification
now states the limit as a limit, requires a receiver not to attempt long writes,
and forbids silent truncation — a value that does not fit is a command that
fails, visibly, like any other.

**Fragmentation stays out of scope.** Splitting a value across several writes
would need sequence numbers, an assembly rule, and a statement about what a
device displays between the pieces. None of that exists, and inventing it here
would be inventing a data format, which this extension exists not to do. It also
would not be free: each piece is a separate command, and a command costs a
connection — about two seconds on this bench (D-054), so a 300-character message
would take six.

Consequences recorded elsewhere: `PLATFORMS.md` states the ceiling for the text
platform, and an over-long write fails rather than being truncated.

**Corrected 2026-09-23.** This said the integration refuses such a write in
`_check_mtu`. It does not: `_check_mtu` reads the negotiated MTU, logs at debug
and returns. The refusal comes from `bleak`, which raises rather than splitting
the write. The outcome satisfies §4.4 and nothing in the integration decides it
— which is worth knowing before anyone relies on the message a user sees.

The specification moves to **2.0-draft.2**. Worth mentioning to Gordon as a
tightening rather than a change of mechanism: it says what every implementation
already does.


## D-059 — One connection carries one command  [DECISION, owner]

**Status:** decided by the owner 2026-09-20, implemented the same day.

> *"Ne considérons pas de commandes multiples. On reste sur un mécanisme simple :
> on ouvre la connexion, on envoie la commande unique, dès qu'on a la
> confirmation GATT on ferme la connexion. On reste simple, pour maximiser la
> fiabilité de notre Release à venir."*

**The rule.** Connect, write one object, wait for the device to acknowledge it,
disconnect. Nothing is bundled. Commands that happen to be queued together are
delivered one connection each, in order.

**What it replaces.** The coordinator used to drain its queue as a *batch*: one
connection carried every command waiting for the device, then paused 250 ms
(`WRITE_DEBOUNCE`) to let anything that arrived meanwhile ride the next
connection. The constant is gone, and so is the pause; a following command now
reconnects as soon as the one before it is acknowledged.

**Why simplicity wins here.** A batch has a failure mode a single command does
not: the link can drop part-way, so some commands are delivered and some are
not, and the receiver has to work out which, report both outcomes, and decide
whether it may retry any of them. That bookkeeping (`written`, partial
reporting) existed only to serve batching. With one command per connection a
failure is unambiguous — that command failed, nothing else is in doubt — which
is what a release is easier to trust for.

**What it costs.** A burst pays a connection per command instead of one
connection for the burst. On this bench that is about two seconds each (D-054)
rather than two seconds plus a few tens of milliseconds. The cost is real and
accepted: bursts are the rare case, and the common case — one click — is
unaffected, since a single command never benefited from batching.

**Coalescing stays**, and is now the only guard against an unbounded queue. A
source faster than the link — a slider dragged, an automation re-asserting state
— would otherwise queue a connection per change forever. Per entry, last value
wins, still *behind* the write in flight rather than in front of it (D-020), so
the first change goes out immediately. Events (`coalesce=False`) are exempt: two
presses stay two presses.

**Revisited 2026-09-22, and deferred.** An independent review pointed out that
this decision's argument covers *batching* -- several objects behind one
acknowledgement, ambiguous when the link drops mid-batch -- and not *link reuse*,
where the queue drains over one connection with a separate response per write.
That has no ambiguity, and `async_read_all` already does it on the read path.

Worth about 2.5 s to 0.6 s for a scene of eight entries on one device, since a
repeated command is 0.31 s of which 14 ms is the write. It would also make a
ramp possible: coalescing currently collapses the steps, and at 36 ms rather
than 310 ms per write far fewer would be.

**The owner deferred it to a future release.** Not rejected on its merits: the
gain serves multi-entry scenes, which are not yet the common case, and holding
the link makes the device unreachable to other centrals for as long as the queue
takes (D-043), which would need a cap. Nothing here blocks it later -- the write
path takes one command at a time and would gain an outer loop, not a rewrite.

**Measurement note.** D-054's *following command* figures were taken with the
batching and its 250 ms pause in place, and its "of which queued" column is
mostly that pause. The *first command* figures — the subject of that campaign —
never waited on it and stand unchanged. `docs/measurements.md` now says so;
re-running the following-command half before release would be worth the hour.


## D-060 — The sweep re-run on one command per connection  [VERIFY]

**Status:** measured 2026-09-20, at the owner's request, after D-059. Both
devices, 100 ms to 5 s in seven steps, 252 commands. Raw samples in
`docs/data/write-puck-switch.json` and `write-nano-text.json`; the pre-D-059
campaign is kept beside them in `data/archive/write-*-batched.json`.

**The instruction included a methodological one:** make sure `fastTimeout` does
not contaminate two measurements on the same node. It is the right thing to
worry about — a first command and a following command are the two sides of the
fast window, so a sample on the wrong side measures the other case under this
one's label, which is worse than a lost sample because it looks like data.

**How it is now guaranteed rather than assumed.** The sweep stamps every
connection to the device, including the ones that set the interval, and records
with each sample how long the device had been left alone *when the command was
issued*. A first command counts only if that exceeds `fastTimeout`, a following
one only if it does not; anything else is flagged and dropped from the summary.
The run is refused outright unless the idle wait clears the window by 3 s and
the burst gap falls inside it. Settings: window 8 s, idle 12 s plus a uniform
random fraction of one interval, burst gap 1 s, window restored to 30 s at the
end. **251 delivered commands, none on the wrong side.**

**Median first command, and the link's share of it, in seconds:**

| | 100 ms | 200 ms | 400 ms | 800 ms | 1.6 s | 3.2 s | 5 s |
|---|---|---|---|---|---|---|---|
| Puck.js | 0.31 | 0.59 | 1.01 | 1.99 | 5.09 | 8.70 | 9.26 |
| connect / interval | 2.8× | 2.8× | 2.4× | 2.4× | 3.2× | 2.7× | 1.8× |
| nice!nano | 0.47 | 0.50 | 0.82 | 3.23 | 5.79 | 11.72 | 8.87 |
| connect / interval | 4.2× | 2.0× | 1.9× | 3.9× | 3.5× | 3.6× | 1.8× |

**A first command costs two to three advertising events, not one.** The expected
answer was one to two. The multiple sits at 1.8–3.2× on the Puck and 1.8–4.2× on
the nice!nano, and there is no interval where either device managed one. The
explanation consistent with it: a receiver does not listen continuously, it scans
with a duty cycle and splits its attention across three advertising channels, so
several of a device's events go by before one is caught — and on this bench one
of those three channels sits under a permanently busy WiFi transmitter (D-057).
Neither cause was isolated here, so 2–3× is this bench's figure, not the
protocol's. It is also the only part of the cost the protocol cannot shorten:
30 to 50 ms remain once the connect time is subtracted.

**Following commands collapsed, and that is D-059 showing.** Median **0.34 s on
the Puck and 0.52 s on the nice!nano**, flat at every interval, with **0.00 s**
of queue everywhere. The previous campaign measured 1.9 s, of which 1.4–1.6 s
was the integration holding the second command behind the first. Removing the
batching removed the pause it needed. The warm path is now bounded by the radio
— a connection to a device already advertising at 100 ms — which is exactly what
the two-speed advertising exists to provide, and it means the receiver is no
longer the thing to fix.

**One command of 252 was lost**, on the nice!nano at 5 s: no acknowledgement
inside 60 s. Nothing stalled past 5 s. The weaker link failing once at the
slowest interval is the expected shape; one sample is not a rate.

**A correction, stated because it was nearly invisible.** The sweep first
stamped the idle time *after* each command returned, charging the command's own
duration to it, and flagged a 9.6 s following command on the nice!nano as though
it had been issued outside the fast window — it had been issued 1.9 s after the
previous one. The tool now reads the idle time at issue, and both datasets carry
the corrected annotation, derived exactly as `idle_for_s - total_ms/1000`. The
correction is an upper bound on the true idle time, so it is conservative in the
direction that matters. No timing was touched; recomputing the Puck's data
changed nothing and the nice!nano's changed one boolean.

**What this says about the two-speed advertising (§4.3).** It earns its keep
twice over now. Each command opens its own connection, so every command in a
burst re-enters the fast window, and the flat 0.3–0.5 s above is what that buys.
Without it, D-059 would have made a burst cost one full first command per step.


## D-061 — The tail at slow intervals is the receiver retrying, not the protocol  [VERIFY]

**Status:** measured 2026-09-21, at the owner's request. *"Refais la mesure à 3.2
et 5 secondes, je pense qu'il y a eu une anomalie quelque part."* There was one.

**What looked wrong.** In D-060 the ladder stopped behaving at its last two
paliers: the nice!nano's median first command *fell* from 11.72 s at 3.2 s to
8.87 s at 5 s, and both devices dropped to 1.8× the interval there after sitting
at 2.4–3.9× everywhere else.

**The first thing found was that the numbers were not reproducible.** Re-running
the same two paliers with twenty first commands each moved the median by 30 to
50 %, on both devices, in both directions:

| | 3.2 s, first run | re-run | 5 s, first run | re-run |
|---|---|---|---|---|
| Puck.js | 8.66 s | 5.59 s | 9.22 s | 13.46 s |
| nice!nano | 11.68 s | 8.94 s | 8.83 s | 11.32 s |

Noise around a true value does not move a median that far in both directions on
both devices. Something discrete was being sampled.

**Pooling both runs shows what.** 120 first commands at those two intervals, and
the time to open the link falls into two groups separated by an **eleven-second
hole with nothing in it**:

| | n | range |
|---|---|---|
| opened the link | 103 | 0.1 – **19.4 s** |
| *nothing* | 0 | 19.4 – 30.5 s |
| opened it late | 12 | **30.5** – 49.8 s |

The far group is 10 % of first commands, mean 37.7 s — and it **does not scale
with the advertising interval** while the near group does. A cost identical at
3.2 s and at 5 s is not made of advertising events.

**It is `establish_connection(..., max_attempts=2)`.** An attempt that times out
is followed by a second one, and the pair costs a fixed penalty on top of
whatever the interval was going to cost. The five commands lost across the two
campaigns are the case where the second attempt failed as well, inside the
sweep's 60 s window. With ten samples per palier, catching one retry instead of
three moves the median by seconds, which is exactly the instability observed.

**What it does not change.** Not the protocol, and not the first five rows,
where no sample fell in the far group. Excluding the retried commands, the link
opens in **1.9–2.9× the interval** at 3.2 s and 5 s — the same two to three
advertising events as everywhere else (D-060). The slow end of the ladder is not
where the mechanism degrades; it is where a fixed 20-odd-second penalty becomes
visible against a longer baseline instead of hiding in it.

**What it does change.**

- `docs/measurements.md` quotes those two rows from thirty samples, marked †,
  and carries the two-group table. Every other row is still ten.
- Ten samples is enough where the spread is one interval wide and not enough
  where a second mechanism is mixed in. Any future ladder should run the slow
  paliers longer, or filter the retried commands out and count them separately.
- **Worth deciding before release:** whether `max_attempts=2` is right. It buys
  a command that would otherwise be lost, at the price of a 40-second one. A
  receiver that reported the failure at 20 s and let the user retry would be
  more predictable; a receiver that retried in the background would be less
  visible. This is the owner's call, and nothing here forces it.

The figure plotted the mean, which at these paliers carries the retry group: the
nice!nano's *following* curve rose to 3.6 s at 5 s on the strength of two samples
out of sixteen, the other fourteen sitting between 0.27 and 1.30 s. That point is
re-measured and the figure's statistic is changed in D-062.


## D-062 — A repeated command costs a third of a second, and the figure says so  [VERIFY]

**Status:** measured 2026-09-21, at the owner's request. *"Refais les mesures
pour le NiceNano à 5 secondes, pour le délai des commandes répétées uniquement,
car je veux exprimer ici le comportement typique du mécanisme, non les
particularités du banc d'essai ci-présent."*

**The measurement.** Ten separate bursts of eight repeated commands, each burst
preceded by one command that opens the device's fast-advertising window —
separate bursts rather than one long one, so that a single lucky stretch of air
cannot stand for the rest. **Eighty samples, none lost, none retried:**

| | |
|---|---|
| median | **0.36 s** |
| quartiles | 0.29 / 0.44 s |
| ninth decile | 0.59 s |
| range | 0.21 – 1.94 s |
| mean | 0.43 s |

The distribution is tight and has no far group at all. For comparison, the
sixteen samples this replaces had a median of 0.48 s and a mean of **3.64 s** —
that mean being two samples, one retried connection at 41.0 s and one slow one at
9.6 s, against fourteen between 0.27 and 1.30 s.

**The table's cell pools all ninety-six samples**, nothing discarded, and reads
0.37 s. `docs/data/write-nano-repeat-5s.json` holds the dedicated run on its own.

**The figure now plots the median.** It had been changed to the mean for
legibility, which was right about the whiskers and wrong about the statistic:
the mean follows the retry group, and the retry group is this receiver's
connection policy on this bench (D-061), not what the mechanism does. A figure
asked to show typical behaviour has to use the statistic that describes it. The
mean, the full range and the retry count stay in the tables, per interval, where
a number meant for comparison belongs.

**What it settles about the warm path.** A repeated command costs about a third
of a second on both devices — 0.33 s median on the Puck, 0.40 s on the
nice!nano across every interval — and the advertising interval does not enter
into it, because the device is advertising at 100 ms throughout (§4.3). The
worst of eighty samples was 1.94 s. That is the number to quote for a burst, and
it is bounded by the radio rather than by the receiver for the first time since
D-020.


## D-063 — Encryption works on hardware; the write counter has no way back  [HW] [DECISION, owner]

**Status:** tested 2026-09-21 on the Puck.js running `encrypted-light.js`, the
bindkey from `test-vectors.json`. The last gap in version 2's hardware coverage
is closed, and it found a release blocker.

**What passed.**

| Step | Result |
|---|---|
| Device seals its advertising | `41 1b 07 65 dc …`, device-info `0x41` — encrypted, BTHome v2 |
| Home Assistant recognises it needs a key | discovery raised the `bindkey` step by itself |
| The key decodes the packet | flow accepted it and read the declaration out of the plaintext |
| Entry created, entities offered | `switch.…_light`, assumed state |
| A sealed write reaches the device | acknowledged in 71 ms, `bthome_writable_write` fired, no error |
| A sealed write is *applied* | **no** — see below |
| The same write with the right counter | **yes**: 103 → 599 → 100 lx, LED on and off |
| Advertising decoded off the air here | illuminance read out of the sealed packet with the same key |

The closed loop is therefore proved end to end with nothing in clear: Home
Assistant's own `seal_write` produced the bytes the device accepted, and the
confirmation was a physical measurement read out of sealed advertising.

**What failed, and why it matters more than it looks.** The device persists a
write-counter high-water mark in `.bwctr`; it was at **100135** from earlier
testing. The config entry had just been re-created, so the receiver's counter
restarted at 0 and sent 1. The module refused it — `counter_not_increasing`,
correctly, that is replay protection doing its job — **after** the GATT write had
been acknowledged, because §3 acknowledges before validating.

So from Home Assistant nothing is wrong. The switch toggles. The write reports
success, with a timing event and no error. The device never changes. There is no
message, no log line, no unavailable entity — the one failure mode the whole
design was meant to avoid.

**And there is no way out.** `Coordinator.resynchronise()` exists, does the right
thing, and is called by nothing: no service, no button, no automatic trigger.
`grep` finds one reference, its own log line. §5.3 asks a receiver to offer
resynchronisation and this one does not.

**How a user reaches this state**, none of it exotic: deleting and re-adding the
device; restoring Home Assistant from a backup older than the counter; moving the
device to a second Home Assistant; reinstalling the integration. The device keeps
its mark across all of them because it is in flash.

**Options, for the owner.**

1. **A service** (`bthome_writable.resynchronise_counter`, an entity target).
   Smallest change, matches §5.3, but the user has to know it exists — and the
   symptom gives them nothing to search for.
2. **Detect and resynchronise automatically.** The receiver cannot see the
   rejection, but it can see that nothing changed: for a device with readable
   entries, a read-back that still shows the old value after a write is evidence.
   For a write-only device there is no evidence at all.
3. **Ask the device.** A characteristic exposing the current write counter, read
   once at setup, would remove the failure rather than paper over it — and that
   is a protocol change, so it goes through Gordon (rule 2).
4. **Resynchronise on every fresh entry.** A new entry could start its counter
   from a jump above anything plausible rather than from 0. Cheap, no UI, no
   protocol change; it spends counter space, which is 32 bits and not scarce.

My recommendation is **4 plus 1**: make a newly created entry start high so the
common case never occurs, and offer the service for the rest. But the encrypted
path should not ship until one of these is in, because the failure is silent and
the user has no move.

**Bench note.** The device's mark is now past 100201. Anything testing writes to
this Puck with encryption must start above that, or clear `.bwctr`.


## D-064 — A failed command raises, and a write counter never starts behind  [DECISION, owner]

**Status:** decided by the owner 2026-09-21 after a survey of what Home
Assistant actually does, implemented the same day. Closes the two questions left
open by D-061 and D-063.

### What the ecosystem does, since the answer turned on it

Surveyed in the installed packages and in the published sources of the core
integrations. The convention is a **split across two layers**, and it is the
same on every radio:

| Layer | Behaviour |
|---|---|
| Transport / vendor library | retries silently, `debug` logging only |
| Integration | raises `HomeAssistantError` when the retries are exhausted |

| | attempts | per attempt | worst case |
|---|---|---|---|
| `bleak-retry-connector` 4.7.0 | 4 | 20 s | ~80 s |
| pySwitchbot | 4 command attempts, each up to 4 connections | | far more |
| zigpy (ZHA) | 3 | 5 s, 28 s on sleepy devices | ~84 s |
| Z-Wave JS | 3 | 30 s callback | ~90 s |

Below zigpy there are two further invisible layers — EmberZNet's APS
retransmits up to three times, 802.15.4's MAC up to three more — so one `turn_on`
can be dozens of transmissions. Nothing logs a *successful* retry above `debug`,
nothing raises a repair, and there is **no ADR, no quality-scale rule and no
timeout** on how long an action may block.

**So our 30–50 s is unremarkable and `max_attempts=2` is already conservative**,
below the ecosystem default of 4. The nearest precedent is yalexs-ble, which
uses 2 for a user-initiated write with the comment that such a write *"should
fail fast and report to the user"*. That is this project's case exactly.

### The decision

**`max_attempts` stays at 2.** The earlier instinct — cut to 1 so that a
command fails at 20 s rather than arriving at 40 — was wrong, and the data says
why: all twelve retried connections in D-061 *succeeded*. The retry is not
futile, it is merely invisible. (Contrast node-zwave-js, which removed its
retry-after-ACK precisely because that one could not help.)

**What was genuinely out of line is that the action could not fail.**
`async_apply` queued the write and returned, so the action reported success
whatever happened afterwards. No integration surveyed does that; the closest,
Z-Wave's fire-and-forget to a sleeping node, is deliberate store-and-forward
with the command durably queued in the driver, which this is not — here the
command is merely late.

The action now **waits for its own write** and raises `HomeAssistantError` with
a translated message when it does not land, per the Silver `action-exceptions`
rule (ADR-0022). The logbook entry stays: the exception is for whoever pressed,
the logbook for whoever reads back later.

Three consequences worth stating:

- **An action can now block for seconds.** That is the ecosystem's price too,
  and Z-Wave charges more of it.
- **A superseded command is not a failure.** Coalescing drops a queued value
  when a newer one arrives for the same entry; nothing failed, so that caller is
  told it succeeded. Tested.
- **A stopped queue strands nobody.** Whatever ends the flush loop settles every
  waiting caller with an error rather than leaving it awaiting a write that will
  never happen.

### The write counter (D-063's blocker)

**A counter now starts from the wall clock when the stored mark is behind it**
(`COUNTER_EPOCH_SEED`, `_starting_counter`). Wall time only moves forward, so a
freshly created entry is above every counter any earlier receiver can have sent,
without asking the device anything — the device on the bench sat at 100135,
decades below the clock. It is a forward jump, which §5.3 requires a device to
accept, and it costs counter space there is plenty of: seconds since 1970 leave
about 2.5 billion values inside 32 bits. A running installation keeps its own
place, because the stored mark wins when it is ahead.

That removes every ordinary way in: deleting and re-adding the device, restoring
a backup, moving the device to another Home Assistant, reinstalling.

**And §5.3's resynchronisation is finally offered**, as a config-category button
on keyed devices only — *Resynchronise write counter*. `resynchronise()` had
existed since T2 and was called by nothing. The button covers what the clock
cannot: a device whose own flash was restored, or one deliberately given a high
counter. A plain device is offered no such button, because it would do nothing.

Not chosen, and why: a service would have needed the user to know it exists, and
the symptom gives them nothing to search for; asking the device for its counter
would remove the failure outright but is a protocol change, so it goes through
Gordon (rule 2) rather than in here.

### Verified on hardware, 2026-09-21

Home Assistant restarted onto this build, the Puck.js running
`encrypted-light.js`, its stored mark past 100201.

| | |
|---|---|
| A plain action now blocks until the write lands | 1210 ms, then returns; the LED is on before the call returns |
| The encrypted entry, deleted and re-created | the exact case that failed in D-063 |
| A sealed write through Home Assistant | **114 → 601 → 111 lx**, the Puck's own light sensor read back out of sealed advertising |
| The resynchronisation button | offered on the keyed entry, absent on the plain one |

One incident on the way, worth recording because it is the failure mode D-029
warned about: an interrupted deployment left the sketch stopped, so the device
advertised nothing and could not be connected to in order to be fixed. The OOTY
rail switch recovered it in one power cycle, which is what it is on the bench
for.


## D-065 — A regression guard for reliability and latency  [T4]

**Status:** built and calibrated 2026-09-21, baseline recorded at `c4e3c88`.
`tools/regression.py`, documented in `docs/regression.md`.

**Why, in one line:** every change that moved this project's numbers passed
every test while doing it.

| What moved | By how much | What caught it |
|---|---|---|
| The batching's pause behind a second command | 1.5 s per command | a hardware campaign (D-059, D-060) |
| One connection in ten timed out and was retried | 30–50 s, reported as success | a re-measure the owner asked for (D-061) |
| A re-created entry restarted its write counter at 0 | every encrypted write refused, silently | the first encrypted hardware test (D-063) |

575 unit tests across three suites, and not one of them could have seen any of
those. They are not the kind of fault a unit test is shaped to find: nothing
threw, nothing returned the wrong bytes, and the integration behaved exactly as
written. What changed was how long it took and whether it arrived.

**What it does.** One advertising interval — 1 s, a guard rather than the ladder
of D-060 — eight first commands and sixteen repeated ones per device, about
three minutes each. It compares seven numbers with a recorded baseline and exits
non-zero on a regression, so it can gate a release.

**The baseline, 2026-09-21:**

| | Puck.js | nice!nano |
|---|---|---|
| First command, median | 1.74 s | 2.54 s |
| First command, p90 | 5.58 s | 5.12 s |
| Repeated command, median | 0.31 s | 0.28 s |
| Repeated command, p90 | 0.51 s | 0.58 s |
| The write itself | 36 ms | 43 ms |
| Delivered | 100 % | 100 % |
| Connected without a retry | 100 % | 100 % |

**Calibrated by running it, not by choosing numbers.** A second run against that
baseline passed with the first-command median at 2.25 s against 1.74 (Puck) and
2.98 against 2.54 (nano) — a quarter to a third of run-to-run movement on an
unchanged build, which is the same order as the 30–50 % seen at the slow paliers
(D-061). The thresholds are ×1.6 plus a floor for a median, ×2.0 plus a floor
for a 90th percentile, and ten to twenty points for a fraction. Generous on
purpose: the faults above were factors of five and twenty, and a guard that
fails on weather is a guard someone switches off.

**Three refusals worth naming**, because each is a way this kind of harness
usually rots:

- **A run containing a sample on the wrong side of the fast window is not
  judged at all.** That sample measures the other case under this one's label
  (D-060). It is a broken measurement, not a regression, and the run says so.
- **A suspiciously fast result is flagged rather than celebrated.** Through the
  ESP32 proxy, first commands came back faster than catching an advertisement
  allows, because it reuses a recent link (D-054). A number far below the
  baseline means the bench stopped measuring the same thing.
- **The bench is configured by the harness, not by memory.** `tools/ha_bench.py`
  disables the proxy and the OLED automation and restores exactly what it
  changed. Both were disabled by hand before every campaign so far, which is one
  more way for a run to be quietly incomparable.

**The policy is pure and tested without a radio.** `compare()` and `summarise()`
take dictionaries and return verdicts; ten tests in `tools/tests/test_regression.py`
pin the judgement — what counts as noise, what counts as a regression, what
counts as the bench having changed. Changing a threshold is a reviewable diff
rather than a number buried in a run.

**The one way this becomes worthless** is a baseline quietly re-recorded to make
a run pass. `docs/regression.md` says so, and the baseline carries the date, the
commit and the bench it was taken on so that a re-recording is visible in the
history.

**Not covered, and worth knowing.** One bench, one interval, two devices: this
guards against *this project* getting slower or less reliable, not against a
different radio environment. The encrypted path is not in it either — it needs a
device reflashed with a key, which is a hardware step rather than a command.


## D-066 — A second receiver, and what it says the numbers belong to  [VERIFY]

**Status:** measured 2026-09-21. `tools/second_receiver.py`, raw samples in
`docs/data/second-receiver.json`.

Every latency figure in this project came from one central: Home Assistant on a
Raspberry Pi 3, one `bcm43438`, one BlueZ. *"A first command costs two to three
advertising events"* could have been the protocol's or that stack's, and nothing
measured so far could tell them apart. The bench host is a second central --
Windows, WinRT, `bleak`, a different adapter -- and it was sitting there unused
for this question.

Same boundary, same interval (1 s), same sample plan as the regression guard,
same fast-window guarantee. 48 commands, none lost, none retried.

| | Home Assistant | bench host | ratio |
|---|---|---|---|
| **Puck.js**, first command, median | 1.74 s | 5.42 s | 3.1× |
| first command, p90 | 5.58 s | 19.85 s | 3.6× |
| repeated command, median | 0.31 s | 0.41 s | 1.3× |
| repeated command, p90 | 0.51 s | 1.90 s | 3.7× |
| the write itself | 36 ms | **14.2 ms** | 0.39× |
| **nice!nano**, first command, median | 2.54 s | 3.88 s | 1.5× |
| first command, p90 | 5.12 s | 15.83 s | 3.1× |
| repeated command, median | 0.28 s | 0.46 s | 1.6× |
| the write itself | 43 ms | **14.5 ms** | 0.34× |

**What it settles.** The *shape* is the protocol's and the *size* is the stack's.
Both receivers agree on everything that matters structurally: a first command is
dominated by getting a link open, a repeated command is cheap and flat because
the device is advertising fast, and the write itself is milliseconds. What moves
is the multiplier — the same command, to the same device, at the same interval,
costs **1.5 to 3.6 times more** through a different central.

So the published figures are not flattered by a favourable stack; they are the
**optimistic end**. An implementer should expect a first command to vary by
about a factor of three with the receiver, and should not read "2 to 3
advertising events" as a property of the mechanism.

**What it newly shows.** The write itself takes **14 ms**, not 36 or 43. Those
larger numbers are what Home Assistant's path costs on top of the GATT exchange,
not what the exchange costs — a third of the figure quoted since D-049 belongs
to the receiver. The likeliest cause is the connection interval each stack
negotiates, since a write with response costs one or two of them; that is a
hypothesis, not a measurement, and it is not worth chasing because 14 ms and
43 ms are both negligible beside the seconds spent opening the link.

**A caveat that nearly became the result.** The first attempt produced two
successes and then four straight connection failures. The host could still
*hear* the Puck perfectly — 28 advertisements in 10 s — so it was not the
device, the interval, or the air: the host's own stack had wedged, which it does
(D-047). Cycling its radio fixed it and the re-run lost nothing at all. Had the
run been reported as it stood, this decision would have said the Windows host
loses two commands in three, which is false. The lesson is the same one as D-052:
**a receiver that cannot connect is not evidence about the protocol until the
receiver has been eliminated.**

`tools/host_radio.py` now does that cycling, the host's equivalent of
`tools/ooty.py` for the board. No administrator rights: Windows exposes the
switch through `Windows.Devices.Radios`.

**A flaw in the bench harness, found the same way.** `bench_prepared` restores
what it changed, which is right when another agent deliberately configured the
bench — and wrong after a run that died: the killed first attempt left the proxy
disabled, the second found it already disabled, changed nothing, and faithfully
put it back as found. It now says so in as many words rather than printing
"already as wanted", because the usual reason for nothing to change is an
earlier run that did not finish.

**Still not answered.** Two centrals is better than one and still not a
population. Neither is on someone else's site, and both talk to the same two
devices in the same room, so the radio conditions (D-057) are common to both.


## D-067 — Encryption costs nothing on the path a user feels  [VERIFY]

**Status:** measured 2026-09-21 at the owner's request. Raw samples in
`docs/data/encrypted-vs-plain.json`, report in `docs/measurements.md` §1b.

The regression campaign, unchanged, run on the same Puck.js at the same 1 s
advertising interval: once on `light-loop.js` in clear, once on
`encrypted-light.js` sealed under the published test-vector bindkey.

| | In clear | Encrypted |
|---|---|---|
| First command, median | 1.74 s | 2.32 s |
| Repeated command, median | 0.31 s | 0.36 s |
| The write itself | 36.0 ms | **36.1 ms** |
| Delivered | 24/24 | 24/24 |

**No measurable difference.** Everything sits inside the spread the unencrypted
build shows against itself — that one moved the first-command median from 1.74 s
to 2.25 s on an unchanged device (D-065).

**The narrow claim this supports.** Sealing costs nothing on the path a user
experiences as command latency: catching an advertisement, opening the link,
getting the write acknowledged. On this device that is seconds, and AES-CCM does
not touch it.

**The claim it does not support, and I nearly made it.** §3 has the device
acknowledge a write *before* unsealing it. The device's crypto therefore falls
after the acknowledgement this campaign times — in the window between Home
Assistant believing it is done and the lamp moving. This measurement cannot see
it, by construction of the protocol.

An earlier guess of 71 ms came from a single sample taken during D-063 and was
not representative; it should not be quoted. The bounds that remain are D-028's
31.8 ms and 75 ms per AES-CCM frame, and the 8 service-data bytes a sealed packet
spends on the counter and MIC — the reason the encrypted example carries no
battery reading.

**What would settle it:** time the applied effect rather than the
acknowledgement, with the light loop as the witness. `tools/closed_loop.py`
already does that shape of measurement in clear.


## D-068 — The device-information byte is a bitfield, and the receiver read it as a value  [VERIFY]

**Status:** found by an independent review 2026-09-22, fixed the same day.

`is_encrypted()` compared BTHome's device-information byte with `0x41`. It is a
bitfield (§2.1): bit 0 encryption, bit 1 MAC included, bit 2 trigger-based, bits
5-7 the version. Every consequence followed from that one line:

- **A sleepy encrypted device transmits `0x45`** and was called unencrypted, so
  the receiver parsed ciphertext as an object stream and the config flow never
  asked for a bindkey.
- **The nonce used our own constant** rather than the byte the device
  transmitted, which §5.1 requires and `bthome-ble` does
  (`BTHomeData.get_nounce_uuid`). Nothing a device sealed under any other flag
  combination could authenticate.
- **The MAC-included flag was ignored.** With bit 1 set the objects start seven
  bytes in, not one, and the nonce is built from the MAC inside the packet --
  which differs from the advertised address for a device using a random one.
  `bthome-ble` skips seven; this skipped one, in three places.

**Why no test caught it.** Every fixture and every test vector in the repo is
`0x40` or `0x41`, because the reference firmware sets no other flag. The suites
were green and the integration worked with exactly one device family -- ours --
which undercuts the entire adoption case.

**The fix.** `is_encrypted` tests bit 0; `mac_included`, `objects_at` and
`nonce_address` are new and used by the coordinator, the config flow and
`decrypt_advertising`; the transmitted byte goes into the nonce. Five tests
cover `0x42`, `0x43` and `0x45`, and all four of the new ones fail against the
old code -- checked by reverting it.

`DEVICE_INFO_BYTE_ADVERTISING` stays, with its role narrowed in the comment: it
is what the reference firmware transmits and what the shared vectors are written
against, and nothing may compare a real advertisement with it.

**The lesson, which is the review's and not mine:** a fixture set that only ever
contains what our own firmware emits tests the firmware, not the protocol.


## D-069 — The advertising counter is persisted, and the entity set survives a restart  [VERIFY]

**Status:** two of the three fixes the independent review of 2026-09-22 asked
for, done the same day. The third, link reuse, the owner deferred (D-059).

### Nonce reuse across reboots

`st.advCounter` started at 0 on every boot, and `seal()` uses it for both
advertising and sealed reads. Same key, same nonce, different plaintext: the
keystream is recoverable, across the whole of the two directions the device
*sends*. The write direction was safe only because the device verifies those
itself and its mark lives in `.bwctr`.

The comment justified it by "bthome-ble allows for it" — which is about that
library's replay filter exempting counters below 100, a different concern from
nonce hygiene, and not a licence to repeat one.

**Fixed** with the same high-water-mark discipline as the write counter, one
file holding `{w, a}`, migrating a bare number written by earlier firmware.

Two details that decide whether it works:

- **The stride is 1 000 000, not 64.** An advertisement is sealed on every
  packet rebuild — once a second idle, ten times a second in the fast window.
  At the write stride that is a flash write every six seconds, which destroys
  the flash in a day. At this one it is one every eleven days, and one per
  twenty-eight hours in the worst case. What it spends is counter values, of
  which there are 4.29 billion.
- **The mark is claimed at `setup`, not on the way past it.** A mark written
  only when the counter reaches it would never be written on a device that
  reboots more often than it sends a million packets — which is every device —
  and the counter would restart at 0 exactly as before. This is the version of
  the fix that actually fixes it; the first one did not, and the test caught it.

### Entities that outlive the device being quiet

`add_entities_as_declared` builds entities from `coordinator.declaration`, and
that was only ever populated by parsing an advertisement. A restart while the
device was asleep or out of range therefore left it with **no entities at all**
— and an automation naming one breaks, where an unavailable one merely waits.
Core `bthome` restores its sensor set from the config entry for this reason.

**Fixed:** the declaration is stored in the config entry when its layout or
revision changes, and restored at setup. It is a cache and never authority: the
first advertisement replaces it, and anything malformed is ignored rather than
failing setup.

### The unique id now carries the object ID

`f"{address}-{entry}"` omitted it while the "already built" set was keyed by
`(entry, object_id)`. Firmware that changed entry 1 from a light to something
else therefore built a second entity claiming the first one's identity —
"Platform does not generate unique IDs", and neither control works.

### Tests

Six new, and every one of them fails against the code it replaces — checked by
reverting. The Espruino harness gained a `Storage` fake, which is what let a
reboot be expressed at all.


## D-070 — The prose said things the code did not  [DECISION, ruled]

**Status:** seven corrections made 2026-09-23, one spec question handed over.
Found by the independent review of 2026-09-22, which was asked to check a few
load-bearing claims against the code and found that several did not hold.

| Claim | What is true |
|---|---|
| D-058: "the integration already refuses an over-long write (`_check_mtu`)" | `_check_mtu` reads the MTU, logs at debug and returns. `bleak` raises. The outcome is right; nothing here decides it |
| D-003: `max_connections` is "user-configurable through the integration's options flow" | There is no options flow. The cap is fixed at 2 |
| `measurements.md`: "9.26 s at 5 s on the Puck" | 12.34 s. 9.26 was the pre-D-061 figure, left behind when the table above it was re-measured |
| Dossier: "the boards have not been run with a bindkey since the rewrite" | They have, on 2026-09-21 (D-063, D-064) |
| `README.md`: "protocol version 2.0-draft.1" | 2.0-draft.2 since D-058 |
| `PLATFORMS.md`: 95 objects, including three metadata ones | 92, and `0xF0`–`0xF2` are not in the library at all |
| Dossier: the battery objection, answered with a latency measurement | Not answered. This project has measured no power (D-055) |

**The last one is the one that matters.** BTHome's constituency is coin-cell
sensors, §7 asks for connectable advertising at all times, and the module
advertises at 100 ms for thirty seconds after every disconnect. Answering "it
costs battery" with "the interval does not set latency" answers a different
question, and a maintainer will notice. The dossier now says so, and names the
measurement as the one to run before submitting.

**Handed to the owner rather than changed (rule 2).** §4.4 says *"Receivers
SHOULD negotiate an ATT MTU of at least 64 bytes"*. The reference receiver never
asks: `bleak` exposes no MTU-request API on BlueZ, so on the platform Home
Assistant runs on this SHOULD is not implementable at all — it is whatever the
stack negotiated. Options, none of which I may take unilaterally:

1. Keep it and note that it is advisory where the stack allows it.
2. Drop it, and state the ceiling as the MTU in force rather than one to seek.
3. Keep it as a device-side SHOULD instead, since a peripheral *can* request an
   MTU and Espruino does.

**Ruled: option 2** (D-073, agreed with Gordon). §4.4 no longer asks anyone to
negotiate anything; it states the ceiling as the MTU in force. *"The maximum
write size should be whatever MTU was negotiated."* The `[DECISION]` marker in
this entry's own heading outlived the ruling by ten days, which is why
`tools/tests/test_stale_markers.py` now counts them.

**What made this possible.** Every one of these passed review because prose is
not tested. The measurement figures now have `summarise_latency` to regenerate
them and the regression guard to catch drift; the claims about code have
nothing. Worth a cheap check before release: grep the docs for function names
and confirm each does what the sentence says.


## D-071 — Clamping is the device's business, not the protocol's  [DECISION, owner]

**Status:** ruled by the owner 2026-09-25, closing the question the independent
review of 2026-09-22 raised as its runner-up finding.

> *"Oublions la gestion de l'écrêtage, on considère hors scope. On est
> responsable de faire transiter une commande, pas de ce que le device en
> fait."*

**The question.** A `number` entity derives its bounds from the object's
encoding, so a device may be sent a value outside its real range; `PLATFORMS.md`
says it is entitled to clamp or reject. §3.2 forbids it from bumping the
settings revision in response to a write, so the receiver is never told to look
again and goes on showing what it sent.

**The ruling.** Out of scope. This extension carries a command to a device and
reports whether it was delivered. What the device does with the value is the
device's design, and a receiver that tried to verify it would be claiming an
authority the protocol does not give it.

**What that settles, and what it costs.**

- No read-back after a write. It would have cost 15–40 ms on every write — a
  round trip on an already-open link, so cheap — but it races the device: §3
  acknowledges before the value is applied, so a prompt read can return the old
  value and be believed. Paying on every write for a rare case, and being wrong
  sometimes, is worse than not looking.
- It only ever covered devices implementing §3.2's readable characteristics
  anyway. A write-only device has nothing to read.
- The state model stays as designed: what an entity shows is what was last
  written or last read, never an inference.
- A device that cares can still make itself honest -- readable characteristics
  and a revision it bumps for its own reasons. The receiver re-reads on a
  revision change and on first sight, so the divergence corrects itself at the
  next one, and at every restart.

**One wording point for Gordon, not a request.** §3.2's *"A device MUST NOT
change `0x65` in response to a write"* forbids the one thing a device could do
to fix this locally. Under this ruling that is consistent -- we do not ask
devices to report it -- but a permissive *MAY* would let a device that wants to
be honest be so, at no cost to one that does not. Worth a sentence if §3.2 is
reopened for another reason; not worth reopening it for.


## D-072 — The settings revision cannot be declared writable  [DECISION, owner]

**Status:** ruled by the owner 2026-09-29. `PROTOCOL.md` §2.1, spec at
**2.0-draft.3**. Raised by the independent review's object inventory.

`0x65` was declarable. §2.1 forbade `0x00`, `0xFF` and `0xF0`–`0xF2`; `0x65`
classifies as an ordinary numeric object, so a device listing it in its
declaration would have been given a 0–255 slider labelled "settings revision",
and a user could have written it.

**Why it belongs with the others.** `0x65` is how a device announces that its own
state moved (§3.2). A receiver able to write it would be driving the signal that
exists to inform it: write the revision, and the receiver re-reads because it
thinks the device changed something. It is protocol machinery, exactly like the
packet id and the declaration itself.

**Why it was fixed rather than asked about.** Rule 2 sends protocol changes
through Gordon, and it binds the *agent's* initiative, not the owner's. The
owner ruled; the precedent is D-058, where the MTU ceiling was decided here,
written into the spec, and carried to the discussion as a tightening rather than
a question. Gordon is told, not consulted — there is no trade to arbitrate,
only an omission of the same class as five entries already in the list.

**Blast radius: none.** No device declares it, the change only removes an
offering, and a forbidden entry is still *counted*, so no characteristic
renumbers. A receiver that has not adopted the rule keeps offering it, which is
as harmless as it was before.


## D-073 — Gordon's review: a length byte, one declaration, no MTU floor  [SPEC, agreed with Gordon]

**Status:** agreed in espruino#8013 on 2026-09-29, implemented the same day.
`PROTOCOL.md` **2.0-draft.4**.

### The length byte, which was his condition

> *"Yes, absolutely! Sorry, I didn't think that through when I posted my example.
> Yes, it should absolutely have a length on it."* — and then: *"please could you
> put the length after 0xFF, and then I'll roll this out in my actual home"*.

The declaration is now `FF <n> <ids…>`. It was the only BTHome object that did
not delimit itself, so the only one a parser had to *stop* at rather than step
over. One byte buys that back, and 255 entries is a ceiling no advertising
payload approaches.

`0xFF` MUST still be last, but the reason has changed and is now written down as
such: not because the format demands it, but because the reference parser stops
at an ID it does not know (D-005). Once `0xFF` is assigned, the rule can go.

### One declaration per device

Gordon found §2.2's rotation rule over-specified: *"Do we need to request this?
It feels like it doesn't really matter as long as it is broadcast."* His
suggestion was to forbid divergent `0xFF` payloads instead. The owner went
further and simpler: **a device has one declaration**, whatever it rotates.

That drops both the frequency floor and the consistency rule, because neither
has anything left to govern. The cost is that every writable entry must fit in
one advertising payload — accepted: entry numbers are positions in one list, and
a list arriving in pieces has no defined order.

### No MTU floor

> *"I don't feel like we need this… Since we're only changing one value per write
> now, everything apart from text+raw will be 4 bytes or less, so should fit in
> the standard MTU even with encryption?"*

Right, and §4.4 now says so: at the guaranteed MTU of 23 a write carries 20
bytes, the largest fixed-length object is five, encryption adds eight. Only text
and raw are ever constrained. The SHOULD is gone — it helped nothing that fits
anyway, and D-070 had already found the reference receiver cannot honour it.

He also suggested letting the BLE stack split long writes. Not taken yet, and
said so in the reply: D-017 measured the stack refusing an over-long payload
outright rather than preparing a write. Replacing an unimplementable SHOULD with
an untested promise would not be progress. Worth an afternoon of measurement
later.

### What he raised that was already done

- *"I don't think we should rely on the device saving the write counter."* Ours
  does (`.bwctr`), and D-069 extended it to the advertising and read directions
  — where it is not a hardening but a correctness fix, because the device seals
  those itself and a counter restarting at zero reuses a nonce. Replied with
  that distinction rather than agreeing flatly.
- *"What happens when Home Assistant reboots? Do we save the counter value?"*
  Yes (D-064), and a freshly created entry seeds from the wall clock, which was
  the silent blocker D-063 found.

### What is still open with him

His overflow window — *"accept anything from LAST+1 to (LAST+1000)&0xFFFFFFFF"*
— is right about wrap-around and wrong about forward jumps, which it also
bounds. Two of ours land far outside it: the clock seed of D-064 (about 1.7
billion) and the resynchronisation of D-072 (100 000), the second of which §5.3
itself asks receivers to offer. Raised in the reply; needs either a wider window
or resynchronisation defined as something other than a jump. **Not implemented
until he answers** — the device would otherwise refuse its own receiver.

### Also agreed

`PLATFORMS.md`'s open question about how a brightness finds its light is out of
scope: *"dealing with the meaning of the stuff that appears in home assistant is
probably out of scope of the spec anyway."* Consistent with D-071.

And he offered his own bench — a NAS container with ESPHome proxies rather than
the Pi's own adapter — which is the second site every measurement in this repo
has been asking for.


## D-074 — One receiver per device  [DECISION, owner]

**Status:** ruled by the owner 2026-09-30, written into §5.3. Raised while
assessing Gordon's counter window (D-075).

**The case.** Two independent receivers — two Home Assistant installations, or
Home Assistant plus a phone app or a script — each keep their own write counter.
The device keeps one: the highest it has accepted. So the moment one receiver
pulls ahead, the other is permanently behind, because its counter advances by one
per write and never catches up. Every one of its writes is refused, and refused
**silently**, since §4.2 acknowledges before validating.

It is a more plausible failure than the one the counter exists to prevent: a
replay needs 2³¹ writes to go by, this needs two installations.

**The ruling: out of scope.** A device answers to the installation that owns it.
That is already what these devices imply — an Espruino serves one central at a
time — and the alternatives all cost more than the case is worth:

- a readable counter characteristic would fix it, and the re-created-entry case
  with it, but it is a protocol addition and one more thing every device must
  implement;
- making the refusal visible would need the device to answer after validating,
  which is the read-after-write §4.2 deliberately does not have.

**What is written down** is the failure mode, not just the rule, because it is
silent and someone will meet it: §5.3 now says a second receiver may read
advertising freely, and that writing needs the first one to stop.

**Not affected:** a Bluetooth proxy. An ESP32 proxy relays GATT and holds no
key, no counter and no state — the receiver is Home Assistant behind it. Any
number of proxies is fine.


## D-075 — How other protocols resynchronise a counter, and what it says about ours  [VERIFY]

**Status:** researched 2026-09-30, while weighing Gordon's counter window. Not a
decision: the evidence behind one, put to him in espruino#8024 and awaiting his
answer.

**The question.** A receiver loses its write counter — reinstalled, restored from
an old backup, moved, or simply a config entry created afresh — and has no idea
what the device is at. It cannot guess low, and §4.2 acknowledges a write before
validating it, so it never learns that its writes are being dropped. D-063 met
this on hardware; D-064 answered it by seeding from the receiver's clock.

### What everyone else does

| Protocol | Mechanism | How lost state resolves |
|---|---|---|
| **Zigbee R23** §4.6.3.8 | challenge + authenticated answer | Receiver sends an 8-byte random challenge; the peer returns its current frame counter MIC'd under the link key; the receiver **adopts it even if it is lower**. Mandatory since 2023 |
| **Matter 1.4** §4.18 | the same (MCSP) | `MsgCounterSyncReq` carries a challenge, `MsgCounterSyncRsp` returns the current counter, group-key authenticated |
| **KNX Data Secure** | clock seed **and** a handshake | Sequence seeded from the device clock — as D-064 does — with `S-A_Sync_Req/Res` on top |
| **Z-Wave S2** | no counter at all | Nonce Get / Nonce Report; nothing persisted, nothing to catch up |
| **SwitchBot, Nuki, Fast Pair** | read the current value | The device hands out its current IV or nonce before each command |
| **Bluetooth Mesh** | epoch above the counter | IV Index ‖ SEQ; past the +42 recovery window, re-provision |
| **LoRaWAN 1.1** | persist or start a new session | `MAX_FCNT_GAP` was *removed* as unnecessary at 32 bits; recovery is a rejoin |

**The decisive detail, and the answer to "what stops the resync itself being
replayed":** freshness comes from a **random challenge**, not from the counter's
monotonicity. That is why Zigbee can adopt a *lower* value safely — the answer is
MIC'd under the link key and bound to a nonce the receiver generated seconds
earlier.

### Three findings that bear on this project

**1. The counter is not secret anywhere, and two specs publish it deliberately.**
NIST SP 800-38C §5.3 asks a nonce to be non-repeating, not secret or random.
Zigbee R23's `Security_Challenge_rsp` *"SHALL NOT be APS encrypted"* and its whole
payload is the device's current counter. Matter returns it plainly. BTHome
already puts it in the clear in every encrypted advertisement. **Publishing it is
the solution, not the risk** — which retires the instinct that kept D-063 from
choosing this.

**2. "Accept a low counter after a reboot" is the mechanism everyone has publicly
regretted.** LoRaWAN 1.0.x's counter reset is the documented replay hole, removed
in 1.1 (*"ABP device must never reset frame counters"*). Matter's spec warns about
its own trust-first mode in as many words. And `bthome-ble` accepts any counter
below 100 for exactly that reason — the subject of an open *"BTHome is not secure
at all"* issue upstream. Tolerable for uplink sensors; not something a downlink
should inherit.

**3. A wide acceptance window is not how anyone solves lost state.** LoRaWAN
deleted `MAX_FCNT_GAP`; EnOcean deprecates its implicit-RLC window for new
designs and calls it a denial-of-service surface; Mesh and Zigbee have no forward
window at all. The half-space rule survives only where a counter genuinely rolls
over — Matter's *group* counters (§4.6.5.2). Gordon's `LAST+0x80000000` is
therefore right for what it is for, wrap-around, and is not the mainstream answer
to amnesia.

### What it says about D-064

Clock seeding has **one** precedent, KNX — and KNX ships a sync handshake
alongside it. So it is defensible as a default and is not a substitute for
asking. Its own weaknesses stand (D-064's own list): it is a guess, it fails
silently when wrong, and a Raspberry Pi has no RTC, so a config entry created
before NTP lands could seed from a stale clock.

### What was put to Gordon

A readable characteristic carrying the device's current write counter. The
construction is nearly free here: reads are already sealed under the read
direction byte `0xFE`, so the answer cannot be forged by anything without the
bindkey.

**With one correction, posted as a follow-up.** Sealing stops forgery, not
**replay**: nothing checks a read's counter (`open_read` decrypts and returns),
so something impersonating the device could serve an old sealed counter, and a
receiver that has just lost its state cannot tell it is stale. It would seed too
low and be refused in silence — a denial of service rather than a compromise,
and it needs an active impersonator rather than a listener, but it is real.
Hence the proposal follows Zigbee's shape: **the receiver writes a random value
first and the device seals it alongside the counter**, so a replayed response
carries the wrong one.

Note also that the clock seed is immune to that particular attack, having no
interaction at all — an argument for keeping both, the clock as the default and
the read to correct it.

**Implemented behind an option, 2026-09-30, at the owner's request.** Off by
default on both sides, so nothing normative changes and rule 2 is not overturned
— but it can be demonstrated rather than argued about.

- **Device:** `counterReport: true` in `setup()` adds a characteristic at
  `2FAA1000-…` (see D-077). Write 8 random bytes, read
  back `seal(challenge || counter u32 LE)` under the read direction byte. The
  counter reported is the last one the device accepted.
- **Receiver:** `ALLOW_COUNTER_SYNC` in `const.py`. When on and a bindkey is
  set, `async_sync_write_counter()` runs once at setup, before the first write
  rather than after one fails — a refused write is silent (§4.2), so there is
  nothing to react to. It resumes at `reported + 1`.
- **A device that does not offer it loses nothing:** the read finds no
  characteristic, the clock seed of D-064 stands, and the run is unaffected.

Six tests, and the one that matters is `test_a_report_for_another_challenge_is_refused`:
a captured report is *genuine* and stale, and a receiver that has just lost its
state has nothing else to judge it by. Sealing alone would have accepted it.


## D-076 — The write counter is ahead, not merely greater  [SPEC, agreed with Gordon]

**Status:** proposed by Gordon in espruino#8024, accepted 2026-09-30, implemented
the same day. `PROTOCOL.md` §5.3, **2.0-draft.5**.

**The rule.** With `LAST` the last counter the device accepted, a counter `C` is
accepted when `(C - LAST) mod 2³²` lies in `1 … 0x80000000`. Half the space.
Everything else is refused.

**What it replaces.** `counter <= st.writeCounter` — strictly greater, plainly.
That was wrong in both directions:

- **It never wrapped.** At `0xFFFFFFFF` the device would have refused every write
  for ever, because `0` is not greater than `0xFFFFFFFF`. Nobody would have
  reached it, but it was a dead end with no way out.
- **It had no room for a receiver that lost its place**, which §5.3 asks for and
  which this project does twice: resynchronisation jumps 100 000 (D-072), and a
  config entry created afresh seeds from the clock, about 1.8 billion (D-064).
  Gordon's first proposal, a window of 1000, would have refused both — silently,
  which is the shape of the bug D-063 found on hardware. Raising it is what made
  the exception I was asking for unnecessary.

**What it gives up, as a number.** A captured write becomes acceptable again once
the device has passed `C + 2³¹` — 68 years at one write a second. Pinned by a
test rather than left as an assertion.

**A detail worth its comment.** The persisted mark is now kept inside 32 bits, so
what is stored is what goes on the wire. A counter that has just wrapped sits
below its old mark and will not persist until it climbs past it again; harmless,
since the window accepts a wrapped counter on its own, and it takes 2³² writes
to arrive.

**§5.3 also now names the recipe for a receiver with nothing to jump from**:
seed from its own system clock. That is what D-064 does, and Gordon's *"add
0x80000000 and try again"* does not cover it — adding to `LAST` requires knowing
`LAST`, which is exactly what has been lost. The clock needs nothing from the
device, and lands inside the window.

Four tests, all four failing against the old comparison — checked by reverting
it. **Still open with him:** the readable counter of D-075, which would remove
the guess rather than widen the tolerance for it.


## D-077 — Characteristic numbers 1000 and above belong to the protocol  [SPEC, agreed with Gordon]

**Status:** proposed by Gordon in espruino#8024 on 2026-10-01, taken the same
day. `PROTOCOL.md` §4.1, **2.0-draft.6**.

The counter report of D-075 was put at `2FAAFFFF`, on the reasoning that entries
are numbered from 1 so the top of the range is out of their reach for ever.

> *"Sounds good - just make it `2FAA1000-...` or something like that?"*

He is right, and for a reason the original choice missed: **`FFFF` is a dead
end.** A second control characteristic would have had to go at `FFFE`, then
`FFFD`, counting backwards from the ceiling. `1000` opens a block instead.

So §4.1 now splits the second 16-bit group rather than merely moving one number:

| Range | Meaning |
|---|---|
| `0000` | the service |
| `0001`–`0FFF` | entries, and nothing else |
| `1000`+ | the protocol's own characteristics |

A declaration carries at most 255 entries (§2.1, D-073), so the entry range has
sixteen times the room it can ever need, and the next control characteristic has
somewhere obvious to go.

**On his other remark** — *"Shame about the complexity but it's good to properly
fix these niggles"* — worth recording that the complexity is entirely opt-in. Off
by default on both sides: a device that does not want the resynchronisation adds
no characteristic and pays nothing, and a receiver that does not ask is exactly
what it was before. Only the pair that wants the problem solved carries it.


## D-078 — draft.6 on hardware: three passes, three faults, one of them the protocol's  [HW]

**Status:** 2026-10-01, Puck.js and Home Assistant. Ten days of work had been
validated in simulation only; this is what a bench said about it.

### What passed, and was the point of the exercise

| Change | Evidence |
|---|---|
| **The declaration's length byte** (D-073) | On air as `ff 01 1e`; the receiver parsed it, built the entity, and the closed loop ran — 597 lux |
| **`.bwctr` migration** (D-069) | The Puck held the legacy bare number `1790017430`; after the new module it read `{"w":1790017430,"a":1000000}` — the write mark preserved exactly, the advertising mark claimed at setup |
| **The counter window** (D-076) | Sealed writes accepted across a gap of 834 000, and refused when behind |
| **The counter report** (D-075, D-077) | At `2FAA1000`: challenge in, 20-byte sealed report out, counter `1790951593` matching `.bwctr` exactly. **A replay with a different challenge was refused**, which is the whole reason the challenge is there |
| **The encrypted loop end to end** | 112 → 597 → 111 lux through Home Assistant |
| **The resynchronisation button** (D-072) | Pressed, counter moved 1790851530 → 1790951591 |

### Fault 1 — the device walks ahead of the receiver at every reboot

The one that matters, and it is the protocol's, not an implementation slip.

§5.3 tells a device to persist its counter periodically and, on resume, to
*"continue strictly above anything it may have accepted"*. Ours does: it stores
`counter + 64` and resumes from the mark. **So every reboot puts the device up to
64 ahead of the receiver, and nothing tells the receiver.** Every write is then
refused — silently, because §4.2 acknowledges before validating — until the
receiver's own counter has climbed past, which takes up to 64 commands nobody
can see failing.

Caught verbatim from the device:

```
counter_not_increasing | write counter 1790951530 is not ahead of 1790951593
```

This is the thing that broke the encrypted loop three times today and sent me
looking at the wire format, the window and the cache before the device said what
was actually wrong.

**It is also the argument D-075 was waiting for.** The counter report is not a
convenience for the re-created-entry case; it is the answer to an asymmetry the
specification itself creates. With it enabled the receiver asked, adopted
`1790951593 + 1`, and the loop ran. **Recommend turning `ALLOW_COUNTER_SYNC` on
by default** once Gordon has ruled: a device that does not offer the
characteristic is unaffected, and one that does stops silently losing commands
after every reboot.

> **Since ruled on, by the owner rather than by Gordon** — D-080, 2026-10-01.
> Turning it on immediately exposed a fault that had made it do nothing at all:
> the first look is defeated by the receiver's own cached GATT table. Gordon has
> still not said whether the characteristic should be normative.

### Fault 2 — a Bluetooth proxy with a stale table acknowledges writes it never delivers

An hour went into this one. Home Assistant reported a successful write — entry
1, 101 ms, `bthome_writable_write` fired — and the device's `onWrite` never ran.
Written directly from the bench host, the same bytes to the same characteristic
worked every time.

It was the ESP32 proxy. An Espruino rebuilds its GATT table on every upload, and
the proxy was relaying against the table it had cached. Disabling it, the next
write arrived (`SET= false` on the device) and the loop ran.

**Nothing in the stack can see this.** The acknowledgement is genuine — it comes
from the proxy — so the receiver has no failure to report and the user has a
switch that toggles and a lamp that does not. Worth knowing before blaming the
protocol, and worth saying to anyone replicating on a bench where firmware
changes often. D-012 is the same disease one layer down.

### Fault 3 — the unique-id change orphaned every existing entity

Ours, introduced in D-069 and invisible to the tests because a fresh test
registry has nothing to orphan. Adding the object ID to the unique id meant
every row already in the registry was never claimed again: it showed as
unavailable for ever while the live entity took a new `entity_id` with `_2` on
the end — which breaks every automation that names it.

Fixed with `async_migrate_entries`, and two things learned writing it:

- **The old shapes are ambiguous.** `<mac>-1-1e` (entry 1 of a light) and
  `<mac>-1-01` (value 1 of entry 1) are indistinguishable. The first attempt
  guessed, rewrote the live entity onto a stale one's identity, and failed the
  whole config entry. The migration now reads the *domain*: only the button
  platform ever carried a value.
- **The identities now say what they are** — `<mac>-e<entry>-<objid>` and
  `<mac>-e<entry>-<objid>-v<code>` — so nothing has to guess again.

A leftover row whose target identity is already taken is left alone rather than
migrated, because a collision fails the config entry and the user loses every
control instead of one stale row.

**And the second device found the rest of it.** The nice!nano orphaned its text
entity anyway, because the migration read the declaration from the config entry
and that entry -- created before D-069 -- had none stored: it returned early,
every time, for exactly the devices that needed it. The layout is in fact
available during setup, from the last advertisement the Bluetooth stack already
holds, so the migration now runs after that seed and takes the declaration from
the coordinator. The Puck passed only because it had been re-added recently
enough to have stored one -- a migration tested on the device that does not need
it proves nothing.

### Fault 4 — the counter report's buffer and its timing

Two device-side slips, both found by reading back the raw characteristic:

- `maxLen` was sized to the **question** (8 bytes) rather than the answer (20),
  so the sealed report did not fit.
- Espruino stores what a central wrote into the characteristic's own value
  **after** `onWrite` returns, so the answer written there was overwritten by
  the question. Deferred by one turn of the event loop, and guarded with a
  try/catch so an exception cannot leave the characteristic holding a challenge
  that reads back as a report nobody can authenticate.

### What this says about the method

Nothing here was visible in 601 unit tests. Two of the four faults are only
expressible against real flash and a real radio — a storage migration and a
proxy's cache — and the one that matters is a consequence of the specification
being right about the device and silent about the receiver.

## D-079 -- the key and the device can disagree, and only one direction said so  [HW]

**Status:** 2026-10-01. Found by running the bench back to a working state after
a latency campaign, which is the ordinary way into it rather than a contrived one.

### What happened

The latency campaign deploys an unencrypted build, because the measurement is
about the radio and not about AES. Afterwards the Puck was reflashed with
`encrypted-light.js` and the sealed closed loop was run again. It reported
success on every write and the lamp never moved:

```
turn_on  (Home Assistant seals the write) ...
illuminance before 97.18 lx
illuminance lit    97.66 lx
```

An hour went into the counter before the config entry was read:

```
Puck.js f7b9 -> {'declaration': {'layout': [30], 'settings_revision': None}}
```

**No bindkey at all.** The entry had been created while the device advertised in
clear, so Home Assistant was writing plaintext to a device that requires
sealing, and §4.2 acknowledges before validating. There is no symptom by
construction.

### Two faults, both ours

**The guard existed in one direction only.** D-042 made *key configured, device
in clear* refuse loudly. The mirror -- *device sealed, no key here* -- fell
through and wrote in clear. It is now the same loud refusal, and the message
names the remedy.

**There was no way to give a configured device a key.** The flow asks for one
only at discovery; after that the advice in D-042's own error message was to
delete the device and add it again, which discards every entity id and so every
automation naming one -- the same damage D-078 fault 3 was about. A device can
gain or lose encryption at any time: reflashed firmware, a key turned on, a
measurement campaign. `async_step_reconfigure` now sets or clears the key in
place, proving it against a live advertisement first and refusing to clear it
while the device is still sealed. It is also what the HA quality scale expects
at Silver, so the gap was two gaps.

### And the contract had drifted

Looking for a sealed fixture to test the new step against turned up something
else: `tools/gen_test_vectors.py` still emitted the declaration **without its
length byte** (`ff1e`), two commits after D-073 put it in §2.1, while the file
it wrote claimed `spec_version: 2.0-draft.6`. The advertising fixtures had been
updated; these had not. Every test that opened them passed, because they all
checked the crypto and none parsed what came out -- so §8's sealed worked
examples disagreed with §2.1 and nothing noticed. Rule 7 makes that a spec bug,
not a tooling slip.

Regenerated, and the HA suite now parses the declaration out of every sealed
vector it opens. The reconfigure tests read their sealed payload from the
vectors file rather than copying it, since copying it was wrong within the hour.

### And the proxy did it again, on the same afternoon

Putting the bench back took three firmware deployments to the Puck, and after
the last one Home Assistant's writes stopped having an effect while the same
write from the bench host worked every time -- D-078 fault 2 exactly. Measured
rather than assumed this time:

```
after reload:    96.85 -> 98.48 lx   FAIL   (HA's own cache was not the problem)
proxy disabled: 100.24 -> 598.68 lx  PASS
```

**And the stale table survives a reconnect.** Disabling and re-enabling the
proxy's config entry did not clear it: the cache is the ESP32's, not Home
Assistant's, so only the proxy rebooting fixes it. This one has no restart
button, no web server and is not on the switchable rail, so it cannot be
rebooted from here at all.

The bench is therefore left with the proxy **disabled**, which is what every
measurement campaign here already does for the duration of a run. On a bench
where firmware changes several times an hour a proxy that acknowledges writes it
discards is worse than no proxy. Re-enable it after rebooting the ESP32, never
before.

### What this says about the method

Both faults are failures of **symmetry**, and both were invisible for the same
reason: the test wrote the state it then checked. Nothing created a receiver
that disagreed with its device, because no test had a reason to -- it took
putting the bench back the way a user would. §4.2's acknowledge-before-validate
is the multiplier on all of it: every mismatch in this family is silent, so it
has to be caught at the receiver or not at all.

### Verified on hardware, after the restart that loaded it

| Step | Evidence |
|---|---|
| The reconfigure step, on a real device | `flow start: form reconfigure` then `abort reconfigure_successful`; the key was proved by decrypting a live advertisement, not merely accepted |
| The entry kept its identity | same `entry_id`, and `switch.bureau_mobilesensf7b9_light` kept its name -- no `_2`, so no automation broke |
| The key reached the receiver | the entry now reads `{'bindkey': <set>, 'declaration': ...}` |
| D-072's button appeared with it | `button.bureau_mobilesensf7b9_resynchronise_write_counter`, created because a key now exists |
| The sealed loop, end to end | 101 -> 597 -> 101 lx through Home Assistant, sealed both ways, confirmed by the device's own light sensor |
| The whole chain | the Puck's sealed advertising decoded by core BTHome, its illuminance carried by an automation to the nice!nano's screen: `text.espruino_b216_text = 'Lux 97.87'` against `sensor...illuminance = 97.87` |

**And D-078 fault 1 reproduced on the way**, from nothing more exotic than a
reflash: the first sealed loop failed silently (100.8 -> 99.5 lx), one press of
the resynchronise button fixed it (101.2 -> 596.5 lx). The device walks ahead at
every reboot and the receiver is never told. A button the user must find, after a
failure they cannot see, is a workaround for a question the device could answer
-- which is the argument for `ALLOW_COUNTER_SYNC`, still the owner's to make.

## D-080 -- ask the device for its counter, by default  [DECISION, ruled]

**Status:** 2026-10-01, ruled by the owner: *"Active ALLOW_COUNTER_SYNC par
defaut"*. `ALLOW_COUNTER_SYNC` is now `True`.

### Why the default moved

It was off because it was a protocol addition nobody had ruled on (rule 1, and
rule 2 is not the agent's to overturn). What changed is the evidence, not the
argument: the case it answers is **not** the unusual one it was written for.

§5.3 has a device resume strictly above anything it may have accepted. A device
that obeys it -- ours stores `counter + 64` and resumes from the mark -- is
therefore up to 64 ahead of its receiver after **every reboot**, and nothing in
the protocol tells the receiver. Every write is refused until the receiver
climbs past, and refused in silence, because §4.2 acknowledges before
validating. It was reproduced twice from nothing more exotic than a reflash
(D-078 fault 1, then again in D-079, where one press of the resynchronise button
turned 100.8 -> 99.5 lx into 101.2 -> 596.5 lx).

The two alternatives are both worse. A button the user has to find, after a
failure they cannot see, is not a remedy. Persisting the counter on every write
is one flash erase-write per command on a coin cell.

### What it costs a device that does not offer it

Nothing it can notice: the read finds no characteristic, the cached GATT table
is dropped in case that is what was hiding it (D-012), and the clock seed of
D-064 stands. The price is one short connection per configured encrypted device
per Home Assistant restart. Plain devices are never asked at all.

### What was missing, and is no longer

The parsing of a report had five tests; **the coordinator's own path had none**,
because the fake GATT client only understood a characteristic object and that
path passes a UUID string. Turning a code path on by default without a test
through it is how D-078 happened. Now covered: the counter is adopted strictly
above what the device reports and the mark persisted; a device without the
characteristic is left exactly as it was; a plain device spends no connection
finding out; and a replayed report leaves the counter alone rather than walking
it backwards, which is the one direction §5.3 forbids.

`espruino/examples/encrypted-light.js` now sets `counterReport: true`, so the
bench's sealed example offers what the receiver asks for.

### Validated on hardware, and it took two goes

First attempt, with the flag on and the device offering the report: **the sealed
loop still failed** (100.0 -> 100.0 lx). The cause was ours and is the same
disease as D-012: a device that has just gained the characteristic is exactly a
device whose GATT table changed, so the cached copy Home Assistant held did not
have it. The code dropped the cache and returned -- meaning the one connection
the receiver spends was always the one that could not succeed, and on a device
whose firmware changes, that is every time. **The feature did nothing at all the
first time it was ever needed.** It now looks again behind a freshly dropped
table, and that second look is the useful one.

With the retry, the acceptance test is unambiguous. Device reflashed (so it
resumes ahead) and Home Assistant restarted (so its table is stale), then the
sealed loop with **no button pressed and no reload**:

```
illuminance before  95.29 lx
illuminance lit    598.70 lx
illuminance after   98.29 lx     PASS
```

### What it does not close, measured rather than assumed

Asking happens at setup. **A device that restarts while Home Assistant keeps
running is still not noticed**, and the failure is still silent:

```
(reflash the device; Home Assistant NOT restarted)
FAIL: 99 -> 100 -> 97 lx
```

A reload fixed it (103 -> 598 -> 102 lx), as does the button. So D-080 closes the
restart case and leaves the live-reboot case open.

**It is not obvious that a receiver can close it.** Every signal available today
is unreliable: a reflash takes seconds, so Home Assistant never marks the device
unavailable; the packet id is one byte and wraps constantly; and the advertising
counter's forward jump on resume is the size of whatever stride that particular
firmware chose. A refused write cannot be seen at all, because §4.2 acknowledges
before validating. Which means the honest answers are protocol-shaped -- a reboot
indicator in the advertising, or a receiver that asks once per write session --
and rule 2 puts both with the owner and Gordon rather than here. Raised in the
draft for Gordon; **nothing invented in the code.**

While it is open, the remedy is the button of D-072, and the user has to be told
it exists -- `docs/home-assistant-install.md` now says so, and no longer claims
an automatic resynchronisation after two failures. There never was one:
`resynchronise()` has exactly one caller, and it is the button.

## D-081 -- a status survey, and the five things it found  [DECISION, ruled]

**Status:** 2026-10-03. An independent survey was asked where the project
actually stands against §7's phases. The useful part was not the status; it was
that reading the two implementations side by side found a defect neither
suite could see.

### Fault -- `0x3B command` was offered by the receiver and impossible on the device

`PLATFORMS.md` said *"`0x3B command` **is offered**, which version 1 could not
do"*, and the receiver does offer it: five buttons, encoding a bare opcode as
`<0><opcode>` and a stepped one as `<1><opcode><step>`.

The device could accept **neither**. Its framing is
`<argument length, low 5 bits><opcode><arguments>`, which is neither a fixed
width nor BTHome's ordinary length byte, and the module had only those two
shapes. Measured before the fix:

```
{id:0x3B, variable:true} + [3B 01 03 01] -> trailing_bytes
{id:0x3B, variable:true} + [3B 00 01]    -> trailing_bytes
{id:0x3B, length:2}      + [3B 01 03 01] -> trailing_bytes
```

So **no declaration existed** that made a command writable: `variable` refused
everything, and a fixed length refused whichever shape it was not. The module
now knows the framing from the object ID alone -- `{id:0x3B, set:...}`, no
length, because the length is the specification's to decide -- and reads only
the low five bits, BTHome reserving the upper three.

**Why neither suite saw it.** Each tested its own side against its own
expectations: the receiver's five buttons encode correctly, and the device
parses correctly everything it was asked about. Nothing made them meet, because
the shared fixtures had no command in them. There is one now
(`writable-command`, two writes of different lengths through one entry), and
the JS fixture test no longer derives a command's length from the write it is
about to parse -- doing that handed the parser the answer.

### Drift -- the signed-object table was three ids behind

`SIGNED_IDS` in the module is a hand-kept copy of `bthome-ble`'s, and `0x59`,
`0x5A`, `0x5B` had been added upstream without it: every negative value of
those types would decode as a large positive one. Invisible because the
upstream `BTHome` module has no type name reaching them, so only a device
declaring one by raw id would have met it.

Completed, and `tools/tests/test_signed_ids.py` now reads the table out of the
JavaScript and compares it with the library both ways. The Python side avoids
this class of bug by never copying the table; the JavaScript cannot import it,
so the next best thing is a test that fails when the copy falls behind.

### Documentation -- a correction that was wrong twice

`PLATFORMS.md` carried *"Corrected 2026-09-23"*, attributing its object counts
to `bthome-ble` 3.9.2 and stating that the metadata objects `0xF0`-`0xF2` *"are
not in the library"*. Recounted:

| library | objects | `0xF0`-`0xF2` |
|---|---|---|
| 3.22.1 (integration) | 92 | absent |
| 3.24.0 (tools) | 95 | **present** |

The counts were right for 3.22.1, not 3.9.2; and the ids were added later
rather than never present, so the earlier total of 95 had been right for a
library newer than the one it named. This is the third instance of D-070's
disease -- prose is not tested -- and the second where the *correction* was the
error.

### Stale markers

A `[DECISION]` marker claims someone still has to choose. Found claiming it
falsely: D-070's own heading, ten days after §4.4 was settled by D-073;
`PLATFORMS.md` heading a question `Open:` that Gordon had ruled out of scope;
and five in the working document for mechanisms version 2 deleted. All now
carry their disposition, and `tools/tests/test_stale_markers.py` requires every
marker outside this archive to say what became of it or be listed as genuinely
open -- which is two: the plaintext-downgrade policy, and the markers' own
definition.

**And the working document itself.** `CLAUDE.md` names it the source of truth
while its §3 and §7 describe version 1 -- same-packet rule, write-all, no-op
conventions, confirmation by advertising, all deleted. Rewriting it is the
owner's; until then it opens with a warning naming `PROTOCOL.md` instead, and a
test keeps the warning there.

### Ruled: battery is out of scope

The dossier had carried *"the experiment to run before submitting"* since
D-055. The owner's ruling: *"laisse tomber la mesure de consommation, ce n'est
pas le role de ce module"*.

And on reflection that is the stronger answer, not a concession. A BTHome
sensor already chooses its advertising interval; a writable one chooses the
same way, and the downlink neither raises it nor needs it raised, because the
idle interval does not set command latency (D-024, D-060). What the module adds
is bounded, configurable and only after someone connected: 100 ms for 30 s. A
figure for one coin cell would describe that board's advertising budget. The
objection is now answered in the dossier by argument, and says so rather than
implying a measurement exists.

### What the survey did not change

`raw` `0x54` is reported `offered` by the receiver and built by no platform, so
a device declaring it gets no entity and no diagnostic. **Left alone by the
owner's ruling**, and recorded here rather than silently: it is a cosmetic
inconsistency in one method's return value, not a path anything takes.

### And the CI gained the two checks the receiving ends run

`hassfest` and `hacs/action`, so a submission fails here rather than on
someone else's pull request. Adding hassfest immediately found the manifest's
keys unsorted -- `bluetooth` after `name` instead of first -- which is what
that check exists for. Neither could be run locally; the first CI run is the
proof, not this entry.

## D-082 -- align the secure mode on core `bthome`, line by line  [DECISION, ruled]

**Status:** 2026-10-05. The owner's instruction: *"vois ce que tu peux faire
pour t'aligner au maximum sur bthome actuel sans casser de mecanismes lies a
bthome-writable. Notre objectif etant l'acceptation de notre modification par
les reviewer bthome."* Prompted by a real incident, below.

### The incident that started it

The owner noticed the Puck's illuminance no longer moved in Home Assistant
while the LED plainly lit. Neither the sensor nor our integration was at
fault: core `bthome`'s own config entry for that device held **no bindkey**,
because the entry predated the device being reflashed encrypted. Its sensor
was frozen on its last plaintext reading -- `97.87` -- and stayed *available*,
because availability follows advertising presence and the device was still
advertising.

Core `bthome` had done the right thing: a reauthentication flow was waiting,
`bthome get_encryption_key reauth`. **Ours would not have raised one.** That is
what the comparison then turned up systematically.

### Identical before this, and verified so

| | `bthome_ble.parser` | us |
|---|---|---|
| nonce | `mac[6] || D2FC || device-info[1] || counter u32 LE` | identical |
| device-info byte | as transmitted (`_get_adv_info`) | as transmitted (D-068) |
| nonce MAC | the packet's when the flag says so (`get_mac_readable`) | `nonce_address()` ~~same rule~~ **this was false when written: the MAC was read as transmitted and theirs is reversed. Fixed in D-083, and now pinned against `BTHomeData.get_nonce()` rather than asserted** |
| framing | `ciphertext || counter || MIC[4]` | identical |
| key | 16 bytes, 32 hex characters | identical |

Our writes and reads reuse that construction with a different device-info
value in the nonce (`0xFF`, `0xFE`), which is the extension itself and touches
nothing on BTHome's advertising path.

### Four things adopted

**1. A reauthentication flow.** The gap, and the one a reviewer would have
found first, because `reauth` is the convention for a credential that stopped
working. Core raises it after **two** failures -- *"we only ask for
reautentification after the decryption has failed twice"* -- and so do we, for
their reason: one failure is a stray packet, and a flow raised for one teaches
the user to dismiss them. We previously logged a warning and went quiet, which
is this session's recurring failure shape (D-078, D-079, D-080) in a fourth
place.

The flow carries the advertisement that would not open, as core carries its
whole `DeviceData` and reads `last_service_info` off it. Without that the first
implementation aborted on `not_on_the_air`, because a notification answered an
hour later finds the device quiet -- caught by the test, not by reasoning.

**2. The advertising replay check**, copied rather than invented, thresholds
included: refuse a counter that has not increased, *unless* the key has never
opened anything (nothing to compare against) or the new value is below 100 (a
wrap, or a battery change). We had no check at all. The impact was small -- a
replayed advertisement reasserts a declaration, not a command -- but a packet
this integration acts on should be one core `bthome` would have shown the user.

**3. `sleepy_device`**, their key name and their rule: `sleepy_device or
super().available`. A trigger-based device is not absent between its events,
and it is persisted in the config entry so its controls are available straight
after a restart rather than hours later. Same literal string, so a device
configured in both integrations reads the same in both.

**4. Their vocabulary.** The key step is `get_encryption_key`, not `bindkey`;
the errors are `expected_32_characters` and `decryption_failed`, in core's own
wording, and they sit on the `bindkey` field rather than on `base`; the field
is `vol.All(str, vol.Strip)`. None of it changes behaviour. All of it means a
reviewer reads their own code.

### Kept, and why

`async_step_reconfigure` (D-079) has no counterpart in core. It stays: reauth
answers *the key stopped working*, reconfigure answers *I want to change or
remove the key*, and only the second can clear a key from a device that went
back to advertising in clear. It is a superset, not a divergence.

Our config flow also scans with `connectable=True` where core passes `False`.
Deliberate: core only listens, we have to connect.

### Still divergent, and not ours to close

**Two integrations, two copies of one key, with nothing linking them** -- which
is exactly what bit the owner. No amount of alignment fixes it from here; a
merge into core `bthome` does. It belongs in the dossier as an argument *for*
the merge rather than as a defect.

**We are not a `PassiveBluetoothProcessorCoordinator`.** Core builds on that
helper; we hold our own coordinator because we also connect, write, read back
and queue. Converting is a structural change with no behavioural gain, and it
would be better done as part of a merge than before one. Recorded, not
attempted (and it is D-070's open note, still open).

### Verified on hardware, and it took a detour

The reproduction is the incident itself: reflash the Puck with a **different**
bindkey, leave the receiver's alone.

```
FLOW step='get_encryption_key' source='reauth' entry=01M3VJN3PG6BYYD8KB0WDWSZWZ
wrong key  -> form get_encryption_key {'bindkey': 'decryption_failed'}
right key  -> abort reauth_successful
sealed loop -> PASS: 108 -> 602 -> 111 lx
```

Exercised twice, because putting the original key back on the device raises it
again from the other side. The replay check appeared on hardware unprompted:
four duplicate packets skipped, *"the new encryption counter (12000229) is not
larger than the previous value (12000229)"* -- the local adapter delivering the
same advertisement twice, which is exactly what it is for.

### Two things the detour taught

**`/api/error_log` returns 404 on this installation, and nothing writes a log
file to `/config`.** Every *"no errors in the log"* in this session's earlier
entries rested on a 404 and was worth nothing. The log is reachable at the
`system_log/list` WebSocket command, which also carries tracebacks. The first
attempt at this validation failed and explained nothing because of it.

**And the first failure was the bench, not the code.** `system_log` showed the
Pi's adapter wedged -- *"Failed to connect after 10 attempt(s)"*,
*"bluetooth_auto_recovery: Could not reset the power state of hci0"*, *"last
advertisement 65s ago"* -- so no advertisement reached the coordinator during
the window, and nothing could have been counted. Core `bthome`'s flow, which I
took as proof the packets were arriving, was a leftover from the owner's own
incident an hour earlier. Reading a stale flow as live evidence cost most of
the detour.

### And a real defect, found by the crash it caused

`system_log` carried an unretrieved task exception:

```
File "/config/custom_components/bthome_writable/coordinator.py", line 778,
  in async_sync_write_counter
...  in split_sealed
    raise ProtocolError(f"{len(payload)} bytes is shorter than the framing...")
```

`open_counter_report` promises *"or None if the report is not this one's"*, and
every caller treats None as *"could not be opened"*. A payload **shorter than
the framing** did not return None: `split_sealed` raised, through two openers,
and killed the background task D-080 had just made run by default. A device can
answer anything, so that is wire data rather than a programming error, and
`_open` now returns None for it. Four occurrences before the fix, none after.

### Where the number came from

Everything above was read out of
`homeassistant/components/bthome/{__init__,config_flow,coordinator,const,strings}`
and `bthome_ble/parser.py` as installed in this repo's own test environment,
rather than from memory of them.

## D-083 -- an independent audit, and the reversed MAC it found  [DECISION, ruled]

**Status:** 2026-10-05. The owner asked for an analysis of bthome-writable by
a neutral agent: bugs, and consistency with official BTHome. It was given the
installed `bthome-ble` and the installed core `bthome` to read, told to verify
before asserting, and told explicitly to treat **this file** as a claim to
check rather than as evidence. It found something ten days of our own work,
two earlier reviews and 648 passing tests had not.

### Fault 1 -- the nonce was built from the MAC backwards  [fixed]

The in-packet MAC of a BTHome v2 advertisement travels **least-significant
byte first**. `bthome_ble.parser.BTHomeData._get_mac` does
`to_mac(bthome_mac_reversed[::-1])`. `nonce_address()` returned `payload[1:7]`
as transmitted. Verified here before the finding was accepted:

```
bthome-ble reads the MAC : A4:C1:38:8E:1F:2B
we read the MAC          : 2B:1F:8E:38:C1:A4
nonce bthome-ble : a4c1388e1f2bd2fc430b000000
nonce ours       : 2b1f8e38c1a4d2fc430b000000
```

Any device setting the MAC-included flag -- legal, and readable by core
`bthome` throughout -- was **unusable**, and since D-082 it also raised a
reauthentication flow telling the user their correct key was wrong. The
reference firmware clears the flag, which is why no bench caught it.

**Three places were wrong, not one.** The code; a test that asserted the
mistake, so the suite defended it; and this file, where D-082's comparison
table said *"same rule"*. A test written from the same misunderstanding as the
code it tests is worth less than no test: it turns a bug into a requirement.

**So the guard is now an oracle rather than an expectation.**
`test_our_nonce_is_the_nonce_bthome_ble_builds` compares our nonce with
`BTHomeData.get_nonce()` for both states of the flag and for a device whose
advertised address differs from the one it transmits; a second test does the
same for the other two things read out of that byte. An encrypted device is
readable exactly when the receiver agrees with that library, so the library is
the only thing worth asserting against. Everything hand-written here was
hand-written by whoever misunderstood the format.

### Fault 2 -- a read that did not authenticate counted as a success  [fixed]

`async_read_all` returned `True` as soon as the *connection* succeeded, however
many entries then failed to authenticate or decode. `_read_loop` took that as
permission to mark the settings revision read, so a refused entry stayed stale
until the revision moved again -- for a setpoint nobody touches twice, for
ever. §3.2 exists to prevent exactly that, defeated by its own success check.
And `_revision_read`'s docstring claimed the opposite: *"Moves only when a read
succeeds."*

It now returns `not failed`, a partially-read device keeps the entries that did
answer, and two tests pin both directions so the fix cannot become *always*
return False.

### Fault 3 -- §5.6 did not exist  [fixed, and needs the owner's eye]

Both implementations ship the counter report, D-080 made the receiver ask for
it **by default**, and `PROTOCOL.md` contained no mention of it: zero hits for
`2FAA1000`, "counter report" or "challenge". For a project whose ask is an ID
reservation, the normative document did not describe the protocol the code
speaks. The mechanism was agreed with Gordon in D-075/D-077; the text was
simply never written.

Written now as §5.6, optional throughout, with the exchange, the reason the
challenge is there, and five MUST/SHOULD requirements. The document is bumped
to **2.0-draft.7** and both generators with it. §9 says plainly that Gordon has
ruled on its characteristic number and not on whether it belongs in the
document. **The owner should read §5.6 before it goes to him.**

### Fault 4 -- the dependency pins are mutually unsatisfiable  [partly fixed]

Measured, not argued:

```
HA 2025.1.4 : core bthome requires bthome-ble==3.9.1
us          : bthome-ble>=3.22.1
hacs.json   : homeassistant 2025.1.0
```

Two integrations with incompatible pins on one instance reinstall each other's
library on every restart, and whichever module is on disk first is what both
then run against. Our floor is load-bearing: without `0x65` in `MEAS_TYPES` the
object walk stops at the settings revision and the declaration behind it
disappears (D-005).

The declared minimum was therefore a false promise, and is now **2026.7.0** --
the version where the two have actually been measured coexisting, on this
bench. `docs/home-assistant-install.md` says why, and
`tools/tests/test_library_floor.py` plus a companion in the HA suite now pin
the reason, which until today was two steps removed from the number and so
read like caution.

**Still open, and the owner's.** The oldest Home Assistant that works is
probably older than 2026.7 and nobody has established which. Two other routes
exist and both are packaging policy rather than correctness: carry our own
`0x65` length so the floor can drop to core's pin, or declare no `bthome-ble`
requirement at all and use whatever core `bthome` installed. Note also that
the test environment pins 2025.1.4, so the suites no longer run against the
version we claim to support -- they still prove the logic, they just do not
prove the floor.

### Fault 5 -- a control outlived its layout and still wrote  [fixed]

New firmware turns entry 1 from a light into a text. Nothing removes the
entities built for the old layout, so the stale switch stayed operable: it
handed its value to the **new** entry's encoder and produced `53 01`, a text
object claiming one character and carrying none. §4.2 acknowledged it before
the device refused it, so Home Assistant reported success and showed the switch
as on.

`still_declared(number, object_id)` is the device's own desync guard, on the
receiving side. Such a control is unavailable -- already enough for the
ordinary path, since Home Assistant drops a service call aimed at an
unavailable entity -- and the write path refuses as well, for any caller that
does not go through entity extraction. Both layers are tested.

The existing layout-change test only ever changed the *number* of entries,
which is why this went unseen. There is now one that changes a **type**.

### Recorded, not fixed

Kept so none of it is lost. Nothing below was in the owner's list.

| # | Finding | Note |
|---|---|---|
| 6 | The read and flush tasks use `hass.async_create_task` rather than `entry.async_create_background_task`, so they outlive an unload -- a reload can have two coordinators connecting to a one-central device. Home Assistant's lingering-task assertion would catch it, but `ha/tests/conftest.py` overrides `verify_cleanup` to a bare `yield` | Real, and the overridden fixture is why the suite is silent |
| 7 | `_check_mtu` does none of what its docstring claims (*"refused outright rather than split"*): it logs once below 64, a floor §4.4 deliberately dropped, and a 40-character text write goes out unchecked while the entity advertises `native_max = 255` | Prose contradicting code, the D-070 disease again |
| 8 | `raw` `0x54` is reported `offered` and no platform builds it: the confirm step would promise one writable object and setup create nothing | Left alone by the owner's ruling (D-081) |
| 9 | `CONF_MAX_CONNECTIONS` is read from options no options flow can set, and `connection_semaphore()` keys by limit *value*, so two entries with different limits get two semaphores -- not the process-wide cap the comment claims | Two defects in one knob |
| 10 | Numbers carry a unit and no `device_class`, so no conversion for a Fahrenheit user; entity names are hardcoded English with no `entity:` section in `strings.json` | Core review would block on this |
| 11 | `async_sync_write_counter` sets `self._counter = reported + 1` unconditionally. A command issued during the setup window is sealed with the clock seed (~1.76e9); the sync then drops the counter to ~1 and every later write is behind what the device just accepted. `max(self._counter, reported + 1)` closes it | **Fixed 2026-10-06**: the adoption is skipped when `reported + 1` is not ahead of the counter we hold, which is the only direction §5.3 allows. In the case it exists for -- a receiver behind a device that restarted ahead -- `reported + 1` is larger and wins, so the guard costs nothing where it is needed. Guarded by `test_asking_never_moves_the_counter_backwards` |
| 12 | Clock seeding leaves the device's acceptance window after 2038-01-19: once `time.time() > 2**31` a seeded receiver is *behind* in circular terms and every write is refused, with the resync button unable to help | Suspected |
| 13 | The Espruino advertising fallback publishes `[info, 0x00, pid]` -- for a keyed device `info` is `0x41`, "encrypted", over an unsealed body | **Fixed 2026-10-07** (D-088): sealed when a key is set, and the harness can now refuse a packet so the fallback is actually executed |
| 14 | The connect and disconnect handlers are registered on every `setup()` with no removal; `goFast()` is the connect handler and can throw `advertising_rejected` into it unguarded, where `handleWrite` guards the same case | **Fixed 2026-10-07** (D-088): subscribed once per module load, both handlers guarded, and the harness now counts subscriptions |
| 15 | The receiver never checks the BTHome version bits (5-7); `bthome-ble` refuses anything that is not version 2, so a future-version packet is parsed here and dropped there. And `0x50` (timestamp) classifies as numeric, so it would be offered as a 0-4294967295 number box | Suspected |

### On consistency with BTHome, which was the other half of the question

The verdict was that the protocol work is idiomatic and well argued -- `0xFF`
last, values as BTHome objects byte for byte, `0x65` used for what it was made
for, the direction byte in the nonce *"a genuinely elegant divergence that is
stated and justified"* -- and that the pushback would be elsewhere:

**We re-implement what `bthome-ble` owns.** Advertising decryption, the replay
check, the device-info flags, the object walk. Only the `0xFF` offset genuinely
needs local code. That is contrary to **our own rule 3**, and it is the direct
cause of fault 1.

Which is the lesson of this entry. D-082 aligned the *vocabulary* and the
*policies* a day earlier and left in place the duplication that produces the
bugs: the alignment done then was the visible one, not the deep one.
`BTHomeData` has a public surface -- `get_nonce`, `get_encrypted_payload`,
`get_mic`, `get_associated_data`, `get_mac_readable`, `is_sleepy_device` -- so
delegating the whole advertising path and keeping only the declaration walk is
available without touching a private method. **Not done here**: it is a
restructuring with no behavioural gain now that the oracle guards exist, and it
belongs with a merge rather than before one. Recorded as the shape of the real
fix.

### What this says about the method

Three independent reviews have each found something the previous two missed,
and this one found the worst by reading the *library* rather than the code. The
pattern across D-078, D-079, D-080, D-081 and this entry is one failure shape:
**§4.2 acknowledges before validating, so every disagreement in this protocol is
silent.** Faults 1, 2 and 5 are all that shape. A guard worth having compares
us with something outside the project -- the library, the device, a light
sensor -- because a test written from our own understanding shares our
misunderstandings, and fault 1 is what that costs.

## D-084 -- the documentation audit: the spec contradicted itself  [DECISION, ruled]

**Status:** 2026-10-05. The owner asked for the whole repository's
documentation to be brought up to date. A second neutral agent checked every
factual claim in every document against the code, under the same rules as
D-083: verify, do not trust; report, do not repair.

### The one that matters -- §2.1 was contradicted by every illustration of it

D-073 put a count byte in the declaration, agreed with Gordon. The normative
rule was updated. **Every illustration of it was not**: all four worked
examples of §8, the inline example in §2.2, one more in prose in §2.3, the
size arithmetic in §2.4, the hardware-test procedure a tester compares real
bytes against, and the figure offered for the Espruino discussion.

```
was:  40 00 09 01 61 FF 1E            is:  40 00 09 01 61 FF 01 1E
was:  40 00 09 FF 1E 1E 53            is:  40 00 09 FF 03 1E 1E 53
was:  the declaration costs 1 + n     is:  2 + n
```

So the document that asks BTHome to reserve an object ID taught its format
wrongly in six places for twelve days, while `spec/advertising-fixtures.json`
-- generated from the implementations, and normative by rule 7 -- carried the
count byte the whole time. 648 tests passed throughout, because no test read
the specification.

**`tools/tests/test_spec_examples.py` now reads it.** Each §8 example is
compared with the fixture it illustrates, byte for byte, and a second check
walks the whole document for any declaration whose count does not match the
object IDs after it. Written as a function rather than inline so the checker
itself is exercised against the strings the document used to contain -- the
first draft of it missed `... FF 1E` at the end of a line, which is exactly
the shape of the historical mistake, and a guard that does not catch the bug
it was written for is worse than none. It then found a sixth instance nobody
had reported, `FF 57` in §2.3.

### Two documents still taught version 1, one of them to agents

**`CLAUDE.md`** named `SPEC-WORKING-DOCUMENT.md` as the source of truth and
told every session to start by re-reading its §3 -- the abandoned protocol.
Its own one-line description of the project was version 1 too: *"writes new
values ... to a single GATT characteristic ... the refreshed advertising is
the confirmation"*. Both of those are the opposite of version 2. An agent
following those instructions would have implemented the wrong protocol, and
the only reason none did is that the working document's banner (added in
D-081) contradicted the file pointing at it.

**`docs/discussion-status-2026-09-16.md`** described the bitmask, the
write-all payload and advertising-as-confirmation as current, with no banner.
It has one now, like `docs/first-use-case.md`.

### A SHOULD the reference receiver deliberately disobeys

§4.2 said *"Several writes to one device SHOULD share a connection."* D-059 is
the owner's ruling that it must not, and D-060 measured why: a second command
sat behind the first for 1.5 s. The spec kept the old SHOULD for six weeks
after the ruling that reversed it. It now states one command per connection,
and says what the earlier draft asked.

### Commands that do not run, and figures that disagree

| Where | What was wrong |
|---|---|
| `docs/walkthrough.md` | `tools.bthome_write --payload 1e01` -- no `python -m`, and `--address` is required |
| `docs/first-use-case.md` | `python -m tools.reject_matrix` without the required `--address` |
| `espruino/HARDWARE-TEST.md` | `reject_matrix` after a setup that installs `single-light.js`, whose state is `light`, while the tool defaults to `lamp.on` -- it would report a failure on a correct device |
| `README.md` | POSIX venv paths in a Windows checkout, and a pip line naming `bthome-ble` again after the paragraph above it warns that doing so causes the version clash |
| `docs/shared-bench.md` and others | **no document mentioned `HA_URL` or `HA_TOKEN`**, which four tools require and fail without |
| `docs/measurements.md` | *"Every tool above takes `--address`"* -- two of them take `--device` |
| `docs/espruino-quickstart.md` | the encrypted bundle called *self-contained* still `require`s `AESCCM`, a repo-local module the Web IDE cannot fetch: pasting it gives a device that advertises and throws on its first seal |

Numbers that disagreed with their own evidence: the connect-time multiples
(1.8× against tables whose minima are 2.0× and 1.9×), the first-command
latency in the walkthrough (five to seven seconds against a baseline median of
1.7 s -- the ninth decile quoted as the typical case), the three-light
declaration (4 bytes, in the figure and in the measurements, against the 5 the
same paragraph derives), `PLATFORMS.md`'s object counts still attributed to
the library version the file itself says was the wrong answer, and the object
budget stated as 7-22 when D-049 had measured 5.

### Test counts: removed rather than guarded

`docs/regression.md` and `ha/HARDWARE-TEST.md` both stated exact suite sizes
and all four numbers were wrong. They are gone. A count in prose drifts on
every test added, and the only cheap guard would have to collect from two
virtualenvs that cannot import each other. **A number nothing checks is a
number that is wrong**, so the claim was deleted instead of corrected -- what
mattered in that sentence was never the count.

### Undocumented, now documented

- **`counterReport`** was absent from the module's own Options list and from
  the quickstart, while D-080 made Home Assistant ask for it by default. A
  reader following the quickstart built a device that could not answer.
- **The reauthentication flow** (D-082) was not mentioned: the install guide
  described Reconfigure but never said Home Assistant asks on its own.
- Two of the eight examples appeared in no document.

### And one more claim the code made and did not honour

`MIN_MTU = 64`, logged as *"the protocol asks for 64"*, twelve days after
§4.4 dropped that floor (D-073) -- and `_check_mtu`'s docstring said a large
write *"is refused outright"* when the function only writes a debug line.
Renamed `COMFORTABLE_MTU`, with both the message and the docstring saying what
it actually is: the size above which anything this protocol sends certainly
fits, and a note in the log rather than a refusal.

### What this says about the method

Every fault here is the same one as D-083's, moved one layer out: **prose is
not tested, so it drifts in the direction nobody looks.** The pattern is
sharpest in the declaration count byte -- the code was changed, the generated
contract was regenerated, three test suites went on passing, and the document
that teaches the format stayed wrong, because nothing in the project read it.

The guards that work are the ones that compare a claim with something outside
the claim: the §8 examples against the fixtures, `SIGNED_IDS` against the
library (D-081), the nonce against `BTHomeData.get_nonce()` (D-083). The
guards that do not exist are for prose that describes behaviour, and that is
still most of `docs/`. Three audits have each found a documentation fault the
previous two missed; the only durable answer is fewer unverifiable claims,
which is why the test counts were deleted rather than fixed.

## D-085 -- the two HACS checks this repository cannot pass yet  [DECISION, ruled]

**Status:** 2026-10-06. The validation job added in D-081 went red on its
first run and stayed red, which is what it was for. `hassfest` passed --
including the manifest key order it had just been given -- and the HACS action
reported two things, neither of them in the code:

- **`brands`**: the domain is not registered in `home-assistant/brands`.
  Nothing inside this repository can satisfy that; it is a pull request there,
  task T4.3.
- **`topics`**: the GitHub repository has no topics. A settings field, not a
  file.

Both are release work rather than defects. The owner's ruling: ignore both for
now -- *"ignore la en attendant, mais assure-toi qu'on ne va pas l'oublier sur
le long terme"*.

### Why an ignore needed more than a comment

A permanently red tick teaches people to stop reading ticks, so leaving it was
worse than ignoring it. But an ignore with a comment beside it is exactly the
shape of thing this project keeps finding rotted: D-084 found five `[DECISION]`
markers outliving their rulings, a `SHOULD` outliving the decision that
reversed it, and four test counts nobody rechecked. A note that says *"remove
this when the brands PR lands"* is a note that will be read once, by whoever
wrote it.

### So the exemption checks whether it is still deserved

A step in the same job asks, on every run, whether either ignored check could
now pass, and **fails the build when one could**, naming the word to delete:

- the repository's topics, from the GitHub API with the run's own token;
- `custom_integrations/<domain>/icon.png` in `home-assistant/brands`, with the
  domain read out of `manifest.json` so it cannot drift from the thing being
  registered.

It never fails for being unable to answer -- a rate-limited API or a network
blip prints a notice and passes. The only red it can produce is the one worth
acting on, which is the test every guard in this project has to meet: a guard
that cries wolf gets disabled, and a guard nobody can act on is noise.

Verified before pushing, by running each branch of the shell against fabricated
answers: `topics=0, brands=404` (today) exits 0; any state where an exemption
has become unnecessary exits 1; an unreadable answer exits 0.

The same two items are now in the dossier's pre-submission list, because a
mechanism that lives only in CI is invisible to whoever is deciding whether to
submit.

### And a claim corrected in passing

The comment above that job said the HACS action was pinned. It is not: the tag
selects a wrapper that runs a Docker image tagged `main`, and `hassfest`
publishes only `master`. Both deliberately track what the receiving end
currently requires -- which is the point of running them, and also means either
can go red without this repository having changed.

## D-086 -- a refused write will say so  [DECISION, agreed with Gordon]

**Status:** 2026-10-06, agreed in espruino#8024. Gordon raised seven points on
the counter report; the reply addressed each and he assented to all of it. A
thumbs-up rather than a line-by-line review, so this records the direction
agreed, not a detailed specification review.

### What was agreed

**Espruino will be able to fail a write with an ATT error.** His words: that
Espruino does not allow it today is not a reason for a write with acknowledgement
not to fail when the counter is wrong.

**This needs nothing new from the protocol.** §4.2 has said since draft.1 that a
device SHOULD reject a write with an ATT error where its platform allows it, and
names Espruino as the exception. Lifting the limitation makes an existing SHOULD
start being honoured. The receiver needs no change either: a failed GATT write
already raises through `bleak` and reaches the user as an error (D-064).

**And then a refused write triggers the counter report**, which was Gordon's own
suggestion: a wrong counter means a restarted device, so ask it on the next
write. That is the answer to D-080's open question -- better than either option
put to him, because it needs no new bit in the advertising and no new SHOULD
about when to ask.

### What was declined, and why

He offered `0xFF` inside the declaration's own list as an error marker. Declined:
**the list is positional.** Entries are numbered from 1 in the order they appear
and that order is the mapping to characteristic numbers (§4.1), so a marker that
is not an entry breaks it.

`0x26` (BTHome's `problem` binary sensor, one byte -- a real object, checked
against `bthome-ble`) is kept as a documented fallback for platforms that cannot
fail a write, not as the primary signal: it is device-wide rather than bound to
the write that failed, it costs advertising bytes, and a receiver can miss the
packet.

`Receiver` stays as the word for the central, with a line in §1 saying so -- it
is BTHome's own term and renaming it would make this document disagree with the
one it extends. The counter persistence MUST stays, because the counter report
is optional and a device may not offer it.

### Nothing to implement yet, and that is deliberate

The work is Espruino's first. Until a write can fail, a failed write means an
unreachable device or a connection slot taken, and asking for the counter in
those cases spends a connection for nothing. So:

- **Espruino**, Gordon: let a write characteristic reject with an ATT error.
- **This module**, then: return that error from the counter check and the desync
  guard, which both currently throw after the stack has already answered.
- **The receiver**, then: re-ask the counter on a refused write rather than once
  at set-up, which also makes `ALLOW_COUNTER_SYNC` (D-080) a cheaper default.
- **§4.2**, then: drop the parenthetical naming Espruino as unable.

An open question nobody has raised yet: a receiver has to tell *this write was
refused for its counter* from *this write was refused for its contents*, or it
will re-ask the counter after every malformed write. Whether that is a distinct
ATT error code or a convention is for when the firmware exists.

### Why this one matters more than its size

§4.2 acknowledging before validating is the single cause behind D-078, D-079,
D-080 and two of D-083's three faults: every disagreement in this protocol is
currently silent, so each one had to be found by a bench rather than reported by
a device. This closes the class, not an instance.

## D-087 -- the first outside tester, and the bug only they could see  [HW]

**Status:** 2026-10-06. @enaon ran it on their own installation and posted
what happened. This is the second site the dossier has been asking for since
D-055, and it took one afternoon to find something three independent reviews,
648 tests and a month of bench work had not.

Their setup, and none of it is ours: an RPi4b running OpenWrt, Home Assistant
in podman, **six ESPHome proxies** and the local BlueZ adapter. It worked --
*"seems to be working fine, both using local BT and the proxies"* -- with two
observations.

### What they saw

> every so often, I can see that once I call changed(), the HA connects more
> than once, 2 or 3 times, it gets the reading on the first try, but connects
> again

Exactly right, and two separate faults underneath it.

**One: the re-read loop continued on the wrong condition.** `_read_loop`
looped while a `_read_again` flag was set, and *any* advertisement arriving
during the read set it. A device advertises every second or so and a read
takes a connection, so an ordinary read almost always had an advertisement
land inside it. The condition that actually means "there is newer state to
fetch" is the settings revision having moved past the one just read, and that
is what the loop tests now.

**Two, and the one that explains "2 or 3": the guard was re-entrant.**

```python
if self._read_task is not None and not self._read_task.done():
    return
self._read_task = self.hass.async_create_task(self._read_loop())
```

`async_create_task` starts the coroutine **eagerly**, so `_read_loop` is
already running while `self._read_task` still refers to the previous,
finished task. An advertisement handled in that window -- and these arrive
from a callback, synchronously -- found no read in progress and started
another one. Instrumented rather than reasoned about: three consecutive
`running=False` with the revision already advertised and not yet read.

The guard is now a plain flag set *before* the task is created, cleared in a
`finally`. Six proxies make the symptom worse because they make
advertisements arrive more often, which is why this site saw it and ours did
not.

### Why no test caught it

`test_the_same_settings_revision_does_not_read_again` pushes its
advertisement **after** the read has settled. The whole fault lives in the
window *during* the read, and nothing exercised that window. The new test
pushes from inside `read_gatt_char`, so the timing is the device's rather than
one the test arranged, and asserts one connection per revision.

### The other observation, which is the design

> The BTH writable extension does not get the battery advertized, I have to
> use the normal BTH extension to get it

Working as intended, and a documentation failure rather than a protocol one.
This integration adds **controls only**; sensors keep coming from core
`bthome`, and both are meant to be set up on the same device. Reimplementing
the sensor side here would be a second answer to a question Home Assistant has
already answered (rule 3).

`docs/home-assistant-install.md` said the entities *land on the same card as
the sensors core BTHome created*, which assumes the reader already knows both
are needed. It now says so first, in a sentence -- together with the seam that
follows from it: an encrypted device needs its bindkey typed into both
integrations, with nothing linking them (D-082), which is an argument for
merging rather than a defect to fix from outside.

### What this says about the method

Both faults are timing, and timing is what a second site buys. The bench here
has one adapter and one proxy; theirs has seven radios hearing the same device,
so the window between creating a read task and assigning it gets hit instead of
being missed. Everything else in this file was found by measuring harder on the
same bench. This was found by someone else plugging it in.

## D-088 -- two faults worth fixing before the module is published  [DECISION, ruled]

**Status:** 2026-10-07. Gordon tested `bthome-writable` on his own Puck.js --
*"works great"*, connections brief, no missed writes, unencrypted -- and asked
for the standalone modules in EspruinoDocs *"as soon as you're happy"*. That
is the third site, and the first from the person who would host the module.

The owner's ruling: fix these two first. They are both in the file he would
host, both harmless on a bench where `setup()` runs once and the radio accepts
the packet, and both stop being harmless the moment the module is copied,
edited and re-run by people whose board and object count nobody knows.

### The safety net told receivers a lie

`refreshAdvertising` checks nothing it can avoid checking, but a radio can
still refuse a packet. When it does, the module publishes a minimal one
instead -- because a device that is not advertising cannot be connected to,
and so cannot be repaired over the air (D-022, D-029). Better a poor packet
than a silent device.

That packet kept the device-information byte, including its **encrypted**
bit, while carrying plaintext. Every receiver therefore tried to decrypt
something that had never been encrypted, failed, and concluded the key was
wrong. Since D-082 a receiver reacts to repeated failures by asking the user
to re-enter a key that was never at fault -- so a packet published to keep the
device reachable produced an accusation against its owner.

Now sealed when a key is set. Eleven bytes, and the fallback already turns the
local name off, so it fits anywhere the unsealed three did.

### Subscriptions to the Bluetooth stack accumulated

The module asks the stack to tell it about connections, so it can advertise
faster while a receiver is about. It asked again on **every** `setup()` and
never cancelled the previous ask, so a second run reacted twice to every
connection and a third three times. The flag preventing that cannot live in
`st`, which `setup()` rebuilds wholesale; it is module-level now.

Mostly wasted work -- except that each reaction rebuilds the advertising, and
that can throw. The throw landed inside the stack's own callback, where
nothing is prepared to catch it, while `handleWrite` has guarded the same case
since D-078. Both handlers are wrapped now, and a failure goes to the
device's `onError`, which is where its own code can hear it.

A device being developed on is a device whose `setup()` runs again and again,
which is exactly the population EspruinoDocs would hand it to.

### The test harness could not see either one

Both faults were listed as *suspected* in D-083 and stayed suspected because
nothing could exercise them. The fake `NRF.on` kept only the latest handler,
so a module stacking a second looked identical to one that did not, and the
fake `setAdvertising` never refused anything, so the fallback had never once
been executed. The harness now counts subscriptions and can be told to refuse
a packet by size.

Four tests followed, and the fourth caught a mistake of mine: refusing *every*
packet makes the fallback fail too, and what reaches `onError` is then the
radio's own error rather than ours. The case the net exists for is a large
packet refused and a small one accepted, which is what the test does now.

### On publishing

Recommended, and soon. Publishing makes `require("BTHomeWritable")` resolve
from espruino.com, which removes the standalone-bundle workaround from the
quickstart, the `AESCCM` caveat beside it, and most of the reason
`tools/build_espruino_bundle.py` exists.

Two things stay true and are worth saying rather than hiding. Gordon and
@enaon both tested **unencrypted**, so the sealed path still has one bench.
And D-086 will change this module again once Espruino can refuse a write --
which is an argument for publishing now rather than waiting, since EspruinoDocs
updates by pull request and the module is useful today.

## D-089 -- four things Gordon noticed while testing  [DECISION, ruled]

**Status:** 2026-10-07. Two fixed here, one is a task already tracked, one is
his to decide.

### The examples encoded illuminance by hand, and said why in a comment that
### was no longer true

> The examples hard-code `illuminance` but the BTHome module now supports it

Correct. Upstream has `illuminance : e => b24(5, e, 100)` -- object `0x05`,
24-bit, hundredths of a lux, which is exactly what three of our examples were
packing themselves and pushing through the `raw` escape hatch.

**The comment beside it is the real finding.** It said *"The published BTHome
module has no `illuminance` type yet"*. False, and nobody here could see it:
`.module-cache/BTHome.js` had frozen a 90-line copy from before the type
existed, so every local build, every test and every reading of the code
agreed with the stale comment. A cache made the documentation lie.

`fetch_module` now prints the cache's age when it passes thirty days. It does
not refetch on its own -- a deployment should not need the network up -- but
a number on screen costs nothing and is what was missing.

The bytes on the air are unchanged (`05 a8 61 00`); only who packs them is.
The test that pinned the escape hatch now pins the opposite, and the fake
`BTHome` in the harness -- which had the same gap for the same reason -- was
taught the type.

### Both integrations were fighting over the device's name

> BTHome adds the MAC digits to the name ... bthome-writable doesn't

Real. Both contribute to one device, and both asserted `name`, so the card's
title was whichever integration wrote last: *"Puck.js c1c3 C1C3"* from core
BTHome, *"Puck.js c1c3"* from us.

Fixed with `default_name` instead of `name`, which Home Assistant applies
only when the device has no name yet. Core BTHome's name survives, and ours
still covers the one case core BTHome cannot name: a device that declares
writable entries and advertises no sensors at all. Matching their string
ourselves would have been the other option and is worse -- it is a copy of a
convention we do not own, and D-081 is a whole entry about what copies do.

### The icon is the brands submission

> does bthome-writable have an icon?

No, and that is `home-assistant/brands`: a pull request there, already
tracked as the reason the HACS `brands` check is ignored (D-085). His question
is the answer to ours -- it is worth filing.

### The module's name: recommend keeping it

He asked for *"a recommendation for a great(er) module name"*. The
recommendation is to keep `BTHomeWritable`, and the reason is not taste.

The name is load-bearing in places a rename would have to follow: the Home
Assistant domain `bthome_writable`, which is also what would be registered in
`home-assistant/brands` and what every existing config entry stores; the
repository and its published URLs; the specification; the dossier; the
discussion title; and two testers' running installations. Renaming is
cross-cutting rather than cosmetic, and the cost belongs in his hands rather
than being hidden from him.

If the length is what bothers him, `BTHomeWrite` costs least -- it keeps the
prefix that makes it sort beside `BTHome` in the module list, which is
probably the property that matters most for discovery.

## D-090 -- plaintext from a keyed device: examined, left to BTHome  [DECISION, ruled]

**Status:** 2026-10-07. @enaon, running twenty encrypted writable lights,
asked whether BTHome's own warning about encryption applies to this extension
too. The warning is that a receiver sees encrypted and unencrypted messages
alike, so full safety depends on the receiver checking what it is given --
counters against replay, and the mix itself.

A fair question, and the answer is **half yes**.

### What this receiver already does

The counter half is covered (D-082). A sealed advertisement whose counter has
not increased is skipped, with `bthome-ble`'s own thresholds including the
exemption below 100 for a device that has just restarted. That is the check
the warning asks for, borrowed rather than invented.

### What it does not do

`_plaintext` reads the device-information byte, and when the encrypted bit is
clear it parses the packet in the clear **even when a bindkey is configured**.
So an unencrypted packet spoofing the device's address is accepted.

What that buys an attacker, honestly:

- `advertises_encrypted` flips to false, and D-042 then refuses every write
  loudly -- one packet disables the device's controls until a real one
  arrives;
- the declaration is replaced, so entities change or vanish, and it is
  persisted;
- the settings revision can be moved at will, which makes this receiver open
  connections: link occupancy and battery.

What it does not buy: **a forged command.** The write path is sealed and
counter-protected independently of any of this, and that is the property an
actuator protocol exists to defend. Everything above is denial of service,
and radio proximity already offers cheaper ones -- jamming, or holding the
single connection slot these devices serve (D-043).

### Why it is not fixed here

The fix is three lines: with a key configured, ignore unencrypted advertising
from that device. It was written out and then not taken, for two reasons.

**It is not this layer's.** Core `bthome` behaves identically -- a plaintext
packet never reaches `_check_bind_key`, because that lives in the decrypt
path. The behaviour belongs in `bthome-ble`, where every BTHome device gains
it, rather than bolted onto one extension. Doing it here would also mean this
receiver rejecting packets a BTHome receiver accepts, in a project whose
argument is that it does what BTHome does (D-082 is an entry about aligning,
not diverging).

**And it has a cost.** A device whose key is legitimately removed would go
quiet with no explanation. That is answerable -- `async_step_reconfigure`
already clears a key and already refuses to while the device still advertises
encrypted, so the escape hatch exists -- but it needs the condition surfaced,
which means a repair issue rather than a log line if it is not to become the
silent failure this session has spent itself removing.

A toggle entity was considered and rejected outright: it would put the
defence behind a control any automation can flip, next to the lamp it
protects. An encryption key is configuration, not state.

### What is owed instead

Saying so. The dossier now carries it as a known limitation with its
reasoning, and @enaon has the same answer in the discussion. The distinction
worth preserving is between *examined and left upstream* and *nobody thought
of it* -- they look identical in code and are not the same thing.

If BTHome adopts the check, this receiver inherits it for free, because the
object table and the parsing it depends on already come from there.

## D-091 -- the prior art has not moved, and the submission cannot be written by an agent  [DECISION, ruled]

**Status:** 2026-10-07. The dossier's prior-art section was stamped
2026-09-17 and "re-run the search" was on the pre-submission list. Re-run
across `bthome-ble`, `home-assistant/bthome.io`, `home-assistant/core`,
`esphome`, GitHub-wide issue and repository search, the live format page and
the community forums.

### The answer is still no, and that is the useful part

**Nobody has proposed a downlink.** Everything new since September is
uplink or housekeeping: four requested sensor types (`bthome.io` #80), an
ESPHome button codec, a Renovate config, dependabot. `0xFF` is still
unassigned -- the highest assigned object ID anywhere is `0xF2`, and
`src/format.html` has not changed since 2026-04-30.

The two standing requests have not moved either: `bthome-ble` #146 (two-way
communication) last had a comment in March 2025, #287 (Shelly BLU control)
in October 2025. Ernst79's *"we will welcome contributions from others if
they want to add this somehow"* is still the last word.

One uncovered surface, stated rather than glossed: GitHub **code** search
needs authentication and could not be run. An implementation living only in
code, with nothing in any issue or repository description, would not have
been seen.

### A request we should have been citing

`bthome-ble` [#257](https://github.com/Bluetooth-Devices/bthome-ble/issues/257),
*"BTHome should define an Object Id for supported events"* (axa88,
2025-08-13, open, no comments): a device should be able to declare which
events it supports, rather than every receiver assuming all of them.

That is **our declaration, asked for independently and a year earlier**, for
a narrower case. It belongs in the dossier: it turns the proposal from *here
is a concept we invented* into *here is a general answer to something you
have already been asked for*. Added to section 1.

### The finding that changes how we submit

The Open Home Foundation **AI policy** has been in the specification
repository since 2026-07-20 and is nowhere in this project. Verbatim:

> We do not allow autonomous agents to be used for contributing to our
> projects. We will close any pull requests or issues that we believe were
> created autonomously, and may mark automated comments as spam.

> Do not use AI to generate answers to questions from maintainers. You
> should understand and be able to explain your own work.

Pull requests that look like unreviewed AI output are closed without review;
AI-derived context must be quoted, labelled and accompanied by the
contributor's own explanation, and long snippets are not welcome.

**It governs everything this project is aiming at on that side**: the `0xFF`
issue on `bthome.io`, the `home-assistant/brands` pull request, and any
eventual merge into core `bthome`. It does not govern the Espruino
discussion, which is Gordon's project under its own rules.

So the division of labour changes, and the honest version is worth stating:
**the owner writes the submission and answers the maintainers, in his own
words.** An agent can measure, verify a claim, find a contradiction and
prepare material to be read and understood -- it must not draft the issue,
the pull request, or the replies. Pasting long extracts of this file into a
submission is a closure risk by their own wording, and the dossier was
already *"not the submission itself"* for different reasons; now it is that
for this one too.

Recorded in `CLAUDE.md` as a rule rather than only here, because it binds
every future session and a decision entry is not read before acting.

### And a note on pace

`bthome.io` #80 has sat with no maintainer comment for over two weeks, and
#72 since March. An ID assignment is unlikely to be quick, which is an
argument for filing early rather than for waiting until everything else is
perfect.

## D-092 -- a second outside bench: a reboot kills the link, a proxy cries wolf, and a characteristic lies  [HW]

**Status:** 2026-10-08. @enaon, twenty encrypted writable lights on an RPi4b
with OpenWrt, Home Assistant in podman, six ESPHome proxies and local BlueZ.
The first external report of the *sealed* path -- the gap named in
espruino#8024 two days earlier, since every test until then had been
unencrypted.

Three faults, one of them already written down as a known limitation and
left unfixed, which is the uncomfortable part.

### Fault 1 -- the reboot that silences a device, and the cure that never ran

Verbatim: *"I then do an E.reboot() on espruino and call setup. This
results in a state where HA cannot connect anymore. I need to erase .bwctr
after E.reboot() and then call setup, then HA will connect again."*

This is **D-078 fault 1**, which §5.6 exists to answer. The arithmetic,
unchanged since: `noteWriteCounter()` persists `counter + CTR_STRIDE` and
`setup()` resumes *from the mark*, so a restart puts the device up to 64
counters ahead of the receiver; every write is then refused in silence,
because §4.2 acknowledges before validating. Erasing `.bwctr` works because
it drops the device to 0, far below a clock-seeded receiver (D-064).

**The cure was built and then wired to the wrong event.**
`async_sync_write_counter()` was only ever started from `async_setup_entry`,
so it ran when the *receiver* started -- never when the *device* restarted,
which is the case D-078 was about. `home-assistant-install.md` even said so:
*"a device that restarts while Home Assistant keeps running is not noticed"*,
with pressing the resynchronise button as the remedy. A limitation written
down in the troubleshooting section is still a limitation; it took someone
else's twenty lights to make that obvious.

**Fixed with the signal the device already sends.** `setup()` picks a random
settings revision at startup -- deliberately, so that a device whose values
went back to their defaults is re-read (§3.2). So a revision that *moves*
while we are watching is the restart signal, and it costs nothing new on the
air. On a change we arm a flag; the next write spends it, asking §5.6 before
drawing a counter. Chosen over the alternatives:

- **asking on every revision change, at once** -- a connection per
  `changed()` on a device nobody is commanding;
- **asking before every write** -- a connection per command, which doubles
  the cost of the thing the project measures itself on (1.7 s, D-050);
- **watching the advertising counter jump** -- a device resuming its
  advertising mark jumps by `ADV_STRIDE`, which would cover a write-only
  device too, but the threshold is a magic number and a receiver out of range
  for twenty minutes produces the same jump honestly.

`changed()` moves the revision as well, so it arms a resynchronisation
nothing needed: one connection before the next command, and the adoption
refuses to move the counter backwards (D-083 item 11), so a needless one
changes nothing. A device that does not offer §5.6 is remembered as such,
once, or every revision change would buy two connections and a dropped GATT
cache for ever.

**What is still open, named rather than glossed:** a sealed device with *no*
readable entry advertises no settings revision, so it has no restart signal
at all and still needs the button or a reload. That is the write-only sealed
device, which neither bench runs.

### Fault 2 -- sixteen warnings in a day, on a device doing nothing wrong

> `xxx: the new encryption counter (10060) is not larger than the previous
> value (10060). The data might be compromised. BLE advertisement will be
> skipped`

Equal, not smaller: **the same advertisement arriving twice.** Six ESPHome
proxies deliver one packet six times, and every repeat was announced as
possibly compromised data.

The check was copied from `bthome-ble` in D-082 and was faithful to the copy
that was read. **The rule has since moved upstream**: 3.22.1 -- the version
Home Assistant pins -- refuses a counter that is `<=` the last one; 3.24.0
refuses only one that is `<`. Nothing in the changelog says so, which is how
it was missed; the venvs on this bench hold both versions, and the guard now
reads the installed one.

We follow the newer reading. The invariant the test holds, whichever version
is installed, is that **this receiver never refuses a packet the library
would have shown the user** -- being stricter than core `bthome` is the one
thing a receiver arguing for BTHome compatibility cannot afford.

Accepting a duplicate is only safe because handling one twice is idempotent,
which is now asserted rather than assumed: same declaration, same revision,
no read, no value moved. Writing that test found the one place it is not
free -- a duplicate now reaches `_notice_revision`, which re-asks for a read
until one succeeds. Two existing guards already hold it (the `_reading` flag
from D-087 and the `READ_RETRY` backoff), and the test states the condition
they depend on.

### Fault 3 -- a characteristic holding the write instead of the value

Found while verifying his third complaint, not reported by him.

`handleWrite()` published the entry's new value from inside `onWrite`. **That
value is destroyed**: Espruino stores the bytes a central wrote into the
characteristic's own value *after* the handler returns. The hazard was known
-- `counterCharacteristic()` is built around it, with a `setTimeout` and a
comment naming it, after it cost a hardware session (D-077). The entry
characteristics were never given the same treatment.

So after any write, a readable entry held the write itself: on a sealed
device a write-direction ciphertext sitting where §4.3 promises the entry's
current value, and on any device the value the receiver asked for rather than
the one the device kept. It is invisible in plaintext whenever the two are
the same bytes, which is the usual case and is why nothing caught it.

**And the test fake could not have caught it**, which is the finding worth
keeping. `updateServices()` was `() => {}`: nothing the module published for
a central to read was ever looked at by any test. The fake now applies it,
and models a write the way the stack really does it -- handler first, written
bytes into the value afterwards. The regression test writes 90 to an entry
whose device clamps at 50 and reads the characteristic back: `[0x01, 90]`
before the fix, `[0x01, 50]` after.

### What was reported and is not a fault

*"the state changes in the UI, regardless of the errors"* -- when the device
silently refuses a write, the acknowledgement is all the receiver gets, and
§4.2 is the whole of the answer. The value is adopted because the write
succeeded as far as anything can tell. **Fault 1 removes the cause** rather
than detecting the effect, which is the only move available: reading the
characteristic back to check was ruled out in D-071, and §4.3 forbids it
normatively. The rest of the class stays with D-086, in the firmware, where
a write can be refused at the ATT layer.

The ON -> OFF -> ON flicker he also describes is not reproducible here: the
entity publishes the requested value while the write is in flight. His
checkout predates D-087 and D-088, which is worth confirming before looking
further.

### The pattern, since this is the fourth time

D-078, D-079, D-080, D-083 and now this: **a mechanism that is built,
tested, and wired to an event that never fires.** The counter report was
verified on hardware (D-078), turned on by default (D-080), guarded against
moving backwards (D-083 item 11) -- and started from the one event that is
not the device restarting. Every test it had asked it the question directly.

What would have caught it is a test that *does not name the mechanism*: a
device restarts, a command follows, the device must accept it. The three new
tests are written that way round.

## D-093 -- T4.2: the documented path did not work on the reference board  [HW]

**Status:** 2026-10-09, run by the owner on a Puck.js (2v27, CR2032) and the
bench Home Assistant. The acceptance test for the documentation, and the last
item on the pre-submission list. Full table in `docs/walkthrough.md`.

The bench was cleaned for it the evening before: the Puck's Storage emptied,
the two Home Assistant entries deleted with their stale entities, the pending
discoveries dismissed. The run was conducted as a stranger would -- the
owner's own words afterwards: *"j'ai joue a l'ignorant... Je n'ai pris aucun
raccourci."*

### The finding that matters: nothing a reader is told to paste fits a Puck.js

Step 1 of the quickstart says to paste `single-light-standalone.js` into the
Web IDE. It cannot work on this board, either way round:

| Where it goes | What happens |
|---|---|
| Flash (`Save on Send: direct to flash`) | `Compacting...` then `Uncaught Error: Unable to find or create file` -- 41 848 bytes written into 40 960 of Storage |
| RAM (the default, and what the document intends) | `OUT OF MEMORY at getAdvertisement`, then `New interpreter error: LOW_MEMORY,MEMORY`; `setup()` dies half-built and `bw.plan()` is null |

**And it is the whole shelf, not one file.** Every readable bundle is 40-42 kB
and every minified one 18-19 kB. `docs/try-it.md` -- the ten-minute
replication published on espruino#8024 for Gordon and @enaon -- offered
`light-loop-standalone.js` as its fallback, so the trap was live in the
document this project has been handing to other people.

**Why a year of hardware work never hit it.** Every path the bench exercises
avoids the one that is documented: `tools.espruino_upload` is driven with
`.min.js`, and `tools.espruino_deploy` puts the modules in Storage and sends a
small application. Pasting the readable bundle is something only a reader does.

Fixed in both documents, which now name the minified bundle and say why, and
say where the Web IDE's *Save on Send* setting lives. Guarded by
`tools/tests/test_pasteable_bundles.py`, which reads the documents rather than
the shelf: it extracts every bundle a reader is told to paste and fails if one
is larger than 32 kB -- a line drawn between a measured failure and a measured
success. It fails on both documents as they stood this morning.

### Two places the documents simply said nothing

**"Where will I see unavailable?"** Asked out loud at step 8. The documents
say an entity goes unavailable and never say where that is visible. Two
sentences now: greyed out on the device page, `unavailable` in developer
tools.

**How long that takes.** The step says *"power the board off, wait"*. It took
**8 minutes 35 seconds** from the last packet. Worth stating because it is
long enough to look like a fault -- and worth stating correctly: the recorder
shows our switch and core `bthome`'s battery sensor for the same board
flipping to unavailable **in the same second**, which settles whose timing it
is. This integration delegates to `bluetooth.async_track_unavailable`; every
Bluetooth integration waits exactly as long, and there is nothing here to
make quicker. Coming back took under a second.

### What passed, and is now evidence rather than assertion

- **Discovery and configuration.** The board was offered without being asked
  for (`source=bluetooth`), configured in one step, no bindkey asked -- notable
  because Home Assistant was holding a *stale encrypted* advertisement for that
  address, and the fresh plaintext one superseded it.
- **One card.** `switch...light` from this integration and
  `sensor...battery` from core `bthome`, on one device.
- **The closed loop from the interface**, both ways, at a delay the owner
  called *"conforme"* -- which is the question that row asks, not whether it
  works.
- **Step 2 by the independent path**: nRF Connect on a phone, `1E01` -> LED on,
  `1E00` -> off. No tool of ours in the loop. That is the strongest form of
  this step and it had never been run that way.
- **A power cycle costs the user no reconfiguration.**

### What the run could not test, stated for the dossier

**Installing through HACS.** It was already installed, and no document tells a
reader in that position what to do. So the install path has still never been
walked by anyone who did not write it. This is the honest gap to carry into
the submission -- and a good thing to ask of someone on the discussion rather
than to paper over.

**That a sketch is gone after a power cycle.** The run put the code in flash
after step 1 failed, so it survived by design. The documented claim -- it runs
from RAM, a power cut undoes it -- remains unverified by a third party.

### Two things the recorder gave for free

- **A toggle at 13:41:41 reads `off`, then `on` in the same second, then `off`
  three seconds later.** That is the shape @enaon reported and this bench could
  not reproduce (D-092). It is now in our own recorder, with current code, and
  is worth chasing on its own.
- **The battery reads 81 % during a write and 100 % again after.** The LED
  draws, the coin cell sags. Not a fault; a good illustration of what a command
  costs on a CR2032.

### The shape of it

Three defects, and not one of them is in the protocol or the code. They are a
file name, a missing sentence and a missing number -- the three things an
author cannot see, which is exactly why T4.2 was written to be run by someone
else and why it should not have waited this long.

## D-094 -- the switch that put an old value back, and the wrong explanation it got first  [HW]

**Status:** 2026-10-09. @enaon reported it on 2026-10-08:

> I can see the state going back and forth sometimes when everything is
> working ok, like: I toggle 'ON', it toggles back to 'OFF' by itself, then
> connects and toggles back to 'ON'.

D-092 could not reproduce it and said so, with a guess attached: his
checkout predates D-087 and D-088. **That guess was wrong**, and the
recorder on this bench had the proof the same day -- four clean instances of
it during the T4.2 run, which nobody had looked at.

### Caught live

Subscribed to `state_changed` and to this integration's own write event, and
asked the owner to press twice:

```
16:20:45.587  SERVICE turn_on     ->  STATE off -> on
16:20:52.359  SERVICE turn_off    ->  STATE on -> off
16:20:53.097  WRITE  entry 1  connect_ms 4891  write_ms 27  total 4919
16:20:53.098  STATE  off -> on                     <- the first write, landing
16:20:56.074  WRITE  entry 1  connect_ms 933  total 1677
16:20:56.075  STATE  on -> off
```

The first command took **4.9 seconds** to catch the device. The user pressed
off while it was still out there. When it finally landed, the entity treated
that completion as its own: it released the value it was showing and fell
back on what the coordinator held -- which that very write had just set to
`on`. Three seconds of a wrong state, corrected only when the second
command arrived.

### The fault, in one sentence

`_write_finished` fires **per entry, not per write**. An entity with a
command in flight cannot tell its own completion from an older one's, and
released the shown value on whichever arrived first.

Fixed by counting: `_writes_in_flight` goes up when a command is issued and
down when that `await` returns, and the shown value is dropped only at zero.
`_write_finished` keeps the half that was always right -- saying in the log
and the logbook that a command failed -- and no longer touches what is on
screen.

### What the test had to be changed to catch

The first version of the regression test asserted the state *after* both
commands and passed with the bug still in place: in a fake, both writes
finish in microseconds, so the wrong value is shown for no time at all. On
hardware it lasted three seconds because the second write needed a real
connection.

**So the test records every state the entity passes through** and asserts
that `on` never appears after the off press. With the fault restored it
reports `['on', 'off']`, which is the bench trace in miniature. A test that
looks only at where things end up cannot see a transient, and a transient is
exactly what a user reports.

### Worth keeping

This is the second time an external report was answered with a plausible
guess rather than a reproduction (the first: D-083's reversed MAC, where the
claim that we followed `bthome-ble` was simply not checked). Both times the
evidence was already on this bench. @enaon is owed the correction, and the
4891 ms connect in that trace is worth its own look -- the measured figure
for a first command is 1.7 s.

## D-095 -- AESCCM takes the firmware's own CCM where there is one  [HW]

**Status:** 2026-10-09, from @enaon's issue #1, opened 2026-10-07 and not
noticed here until today -- after we had told him issues on this repository
were welcome. Two of his were sitting unanswered.

### The case the module did not allow for

`AESCCM.js` said of itself: *"This gives the same thing on any build that has
AES at all."* It assumed two populations -- a firmware with the generic
`AES.encrypt`, which our construction needs, or one with `AES.ccmEncrypt`,
which needs nothing from us.

**His nice!nano is the third:** `AES.ccmEncrypt` present, `AES.encrypt`
absent. There the file cannot run at all, and it is the board he tests
encryption on. He had already written the replacement and attached it.

### What was done

One module, two paths: the firmware's CCM when `AES.ccmEncrypt` and
`AES.ccmDecrypt` are both there, the construction here otherwise. Asked per
call rather than once at load, because a module can be required before the
sketch that sets anything up and two `typeof` checks cost nothing beside an
AES. `exports.usingNative()` lets a device say which path it took rather
than be guessed about.

**It also answers a question that was open for Gordon.** The pending item
was whether to publish two modules to EspruinoDocs or ask Espruino for
`USE_AES_CCM` more widely. Neither: one module that prefers the native path
covers both kinds of board, and is far quicker on the boards that have it --
our own AES calls cost about 75 ms each (D-028).

### What could be tested here, and what could not

No board on this bench has `USE_AES_CCM`, so **the firmware's actual return
shape cannot be verified here**. @enaon's patch reads `{data, tag}`, written
with an assistant rather than from a board's documentation. So:

- both spellings are accepted, `tag` and `mic`;
- anything else throws with **what actually arrived** in the message, because
  the person who meets it has the board and we do not;
- OpenSSL's AES-CCM stands in for the firmware in the tests.

That last one pays for itself twice. It exercises the adapter, and it checks
`test-vectors.json` against a **second, independent CCM implementation** --
until now every vector was only ever confirmed by the construction that
produced it. One test asserts the two paths agree byte for byte on every
vector, since a device may run either and the air must not be able to tell.

**Still owed: a run on his board.** The contract exists already -- the shared
vectors -- and that is what to ask for rather than a yes.

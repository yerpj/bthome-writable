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

**Status:** decided by the owner, 2026-09-08. **Default 2, user-configurable**
through the integration's options flow.

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
platform, and the integration already refuses an over-long write rather than
truncating it (`_check_mtu`).

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

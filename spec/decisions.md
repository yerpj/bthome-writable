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
CCM frame     31.8 ms
of which AES   4.5 ms
```

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

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

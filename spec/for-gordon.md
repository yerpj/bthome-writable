# Points to raise with Gordon

Working list for espruino#8013. Everything came out of implementing the design.
Ordered by how much it needs an answer. Last checked 2026-09-16.

---

## 1. Master builds advertise service data with no UUID

Not a BTHome question, and the most urgent thing here. On a `2v29.242` build,
`NRF.setAdvertising` emits the service-data AD structure **without its 16-bit
UUID**. The changelog entry is in the unreleased section:

> BLE: switch to our own code for creating advertisement packets (shared across
> all platforms).

A standard UUID with nothing to do with this project makes the point:

```
NRF.getAdvertisingData({0x180F:[1,2,3]}, {showName:false})
  got       02 01 06 04 16 01 02 03
  expected  02 01 06 06 16 0f 18 01 02 03
```

Every key spelling behaves the same — `0xFCD2`, `"FCD2"`, `64722`, `0x180F`. On
the air, a nice!nano's BTHome payload begins where `d2 fc` should be, so
receivers file it under UUID `0x0040` and no BTHome install will ever match it.
A Puck.js on a release build is unaffected.

The raw AD-structure form still works, and is our workaround if this is
intended:

```
NRF.setAdvertising([2,1,6, 13,0x16,0xd2,0xfc, ...payload], {showName:false})
  ->  02 01 06 0d 16 d2 fc 40 00 77 02 f0 0a 53 00 ff 04
```

Same builds also stopped shortening the local name to make a packet fit — they
refuse the packet instead. Nothing found in the issues, discussions or forum, so
this looks unreported. Full measurements in `decisions.md` D-046.

---

## 2. The `BTHome` module fixes are not published

You fixed both on 2026-09-10 and EspruinoDocs master has them:

```js
illuminance : e => b24(5, e, 100),
humidity    : e => [0x2E, Math.round(e.v)],
```

`https://www.espruino.com/modules/BTHome.js` still serves the old file — no
`illuminance`, and `humidity : e => [0x2E, e, 1]`, which pushes the entry object
where it means to push the value. That URL is what the Web IDE and every
deployment tool fetch from, so devices still get the broken one and this repo's
example still goes through `raw`.

---

## 3. Write-only, for fixed-length objects — needs your agreement

Settled on the device side: an entry with `set` and no `get` is write-only, and
the module advertises it back at zero length (D-009).

Open for **fixed-length** objects, where "advertise it with an empty value" has
no representation — an object ID with no value bytes is not something a BTHome
parser can walk. A light that is off advertises `1E 00`, byte-identical to a
placeholder, so a receiver cannot tell a stateless trigger from an actuator that
happens to be off. Guessing wrong means either exposing a real switch as
stateless, or waiting forever for a confirmation that will never come.

**Proposed wording:** a write-only object is a *variable-length* object
advertising length 0, or an *event-class* object advertising its "none" value.
Nothing is lost — write-only exists for displays, buzzers and triggers, which
are exactly those classes. Implemented this way on both sides; the spec text is
what needs agreeing.

---

## 4. `0x3B command` has no no-op — needs a decision

§4.3 says a write leaves an event object alone by sending its "none" value,
`0x00`. True for two of the three event objects:

| object | `0x00` means |
|---|---|
| `0x3A` button | none |
| `0x3C` dimmer | none |
| **`0x3B` command** | **`off`** |

`bthome-ble`'s `COMMAND_EVENTS` starts at `0x00: "off"` with no "none" anywhere.
Since a write carries *every* writable object (§4.2), a device declaring a
writable command alongside anything else cannot have that other thing written
without also commanding it — and today that command is `off`. A user toggling a
light would silently switch something off, and the protocol would call the write
correct.

Three ways out, none ours to pick: forbid declaring `0x3B` writable; give it a
no-op value outside the vocabulary; or let §4.3 admit some objects have no no-op
and require such an object to be a device's only writable one. Until then this
project offers no control for `0x3B` at all.

---

## 5. §2.3's budget is wrong, and now has measurements

The working document said the usable budget was 23 bytes. Every radio measured
takes less, and two terms were never counted: Espruino's always-present `0x0590`
manufacturer data, and the local name.

| board / firmware | with name | without |
|---|---|---|
| Puck.js 2v27 | 17 | 20 |
| nice!nano 2v29.242 | 7 | 22 |

On the nice!nano the arithmetic that holds is 31 less 3 flags, 4 manufacturer
data, 4 service-data header, and `2 + len(name)` — and that firmware refuses
rather than shortening the name, so a thirteen-character default costs 15 bytes.
The Puck gives back only 3 when the name is dropped, so older builds evidently
do shorten it.

Eight writable one-byte objects plus the declaration come to 18, so the limit is
still workable — but "31" is misleading and the spec now says so. `showName:
false` is the first thing to try when a packet is refused. (D-030, D-046.)

---

## 6. `AES.encrypt` in CTR mode ignores its `iv` — a security bug

Puck.js 2v27. Two IVs with no byte in common give the same answer, and it is
`E(0…0)`: the counter block is always zero.

```
iv 000102030405060708090a0b0c0d0e0f  ->  1838858c73da85d4885458a8e5dbda4f
iv ffeeddccbbaa99887766554433221100  ->  1838858c73da85d4885458a8e5dbda4f
AES-ECB of an all-zero block         =   1838858c73da85d4885458a8e5dbda4f
```

CBC and ECB are correct, byte for byte against a reference. `OFB` returns
`undefined`, possibly the same root cause.

Worth more than a bug report because it looks like it works: CTR over a nonce is
the obvious way to build a stream cipher, and this one uses one keystream for
every message under a key, so two ciphertexts XOR to the two plaintexts XORed.
Anyone who reached for it has no confidentiality between messages and nothing
told them. It costs us only an extra loop — we take the keystream from ECB
instead — so no hurry on our account. Reproduce with
`python -m tools.ccm_bench --address <mac>`.

---

## 7. `AES.encrypt` returns `undefined` when it cannot allocate

It allocates its result as one contiguous run of heap. With no run that long it
prints `ERROR: Not enough memory for result` and returns `undefined`, so the
caller's `new Uint8Array(...)` throws `Unsupported first argument of type
undefined` at a line that has nothing wrong with it.

`process.memory().free` does not predict it — it counts free blocks, not
consecutive ones. In one session a 48-byte AES call failed while a REPL
`new Uint8Array(256)` succeeded. Throwing rather than returning `undefined`, and
saying *contiguous* rather than "not enough memory" with 24 kB free, would save
the next person the afternoon.

---

## 8. Settled, for the record

- **UUIDs.** One randomly assigned 128-bit base, second 16-bit group varying per
  characteristic: `2FAA0001-…` service, `2FAA0002-…` write. Adopted (D-001),
  frozen at first release.
- **Encrypted write field order** is `[ciphertext][counter u32 LE][MIC 4]`,
  matching BTHome's own encrypted advertising rather than the working document's
  original order (D-008).
- **The packet-id object shifts every bitmask bit.** Your worked example omitted
  it and got `FF 02`; a device using `getAdvertisement` emits it and gets
  `FF 04`. Now normative in §2.2 with the same device shown both ways.
- **`bthome-ble` tolerates the declaration**: unknown object IDs are skipped
  with a DEBUG log, no error — so it lives in the BTHome service data and the
  manufacturer-data fallback is not needed. Objects *after* the declaration are
  silently dropped, which is why "declaration last" is a MUST (D-005). It also
  already names duplicates `light_1`, `light_2`… by packet order, so its naming
  and our positional addressing agree by construction.
- **CCM is affordable and needs no JavaScript AES**: all vectors reproduce on a
  Puck.js 2v27 at 75 ms per frame, under 5 ms of it cipher. One ask remains —
  `USE_AES_CCM` is not set in the Puck.js build, and enabling it would remove
  our framing entirely.

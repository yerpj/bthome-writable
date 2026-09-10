# Points to raise with Gordon

Working list for the espruino#8013 discussion. Everything here came out of
actually implementing the design; nothing here is a re-opening of a settled
question. Ordered by how much it needs an answer.

---

## 1. A bug in the upstream `BTHome` module — FIXED

Fixed in EspruinoDocs master on 2026-09-10 as
`humidity : e => [0x2E, Math.round(e.v)]`. Not yet on espruino.com/modules,
which is where the tooling fetches from, so devices still get the old one.

`humidity` in `getAdvertisement`'s encoding table pushes the entry object where
it means to push the value:

```js
humidity : e => [0x2E, e, 1],          // current
humidity : e => [0x2E, Math.round(e.v)],   // presumably intended
```

Every neighbouring entry uses `e.v`, and the trailing `1` looks like a factor
left over from the `b16` helper's signature. A device advertising `humidity`
would emit an object rather than a byte. Unrelated to this project — found while
reading the module to wrap it — but worth fixing.

Source: https://www.espruino.com/modules/BTHome.js

---

## 2. Write-only objects: §3 says something undetectable — PARTLY ANSWERED

**Answered on the device side, 2026-09-10:** an entry with `set` and no `get` is
write-only, and the module advertises it back at zero length without the sketch
having to declare it. Implemented; `writeOnly: true` survives for the other
case, a value the device *could* report but would rather not.

**Still open on the receiver side.** "Advertise it back with zero length" has no
representation for a *fixed-length* object — an object ID with no value bytes is
not something a BTHome parser can walk — so the ambiguity below is unchanged for
that class, and the proposed wording still needs your agreement.

The working document declares a write-only object by advertising it "with an
empty/zero value".

For a variable-length object that is unambiguous — a length byte of 0 cannot
arise any other way. For a **fixed-length** object it cannot be detected at all:
a light that is off advertises `1E 00`, byte-identical to a "zero value"
placeholder. A receiver cannot tell a write-only trigger from an actuator that
happens to be off, and guessing wrong means either exposing a real switch as a
stateless entity, or waiting forever for a confirmation that will never come.

**Proposed wording:** a write-only object is a *variable-length* object
advertising length 0, or an *event-class* object advertising its "none" value.
Nothing is lost: write-only exists for actuators with no meaningful uplink — a
display, a buzzer, a trigger — which are exactly those classes. A write-only
boolean is close to meaningless, and a device wanting one can use an event
object.

Implemented that way on both sides already (decisions.md D-009); the spec text
is what needs your agreement.

---

## 3. Encrypted write payload: field order corrected

**Already changed, flagging for the record.** §3.4 of the working document put
the counter *before* the ciphertext:

```
[counter u32 LE][ciphertext][MIC 4]      working document
[ciphertext][counter u32 LE][MIC 4]      PROTOCOL.md, as shipped
```

BTHome's own encrypted advertising uses the second order. Keeping the write
different means neither side can share its framing code between the two
directions — concretely awkward on Espruino, which must both build encrypted
advertising and parse encrypted writes on a constrained target — and it is a
gratuitous divergence in a specification whose case to the BTHome maintainers
rests on reusing BTHome's own formats. My guess is the original order was
written in passing rather than chosen.

Test vectors are generated in the new order (decisions.md D-008).

---

## 4. The packet-id object shifts every bitmask bit

**No decision needed, but it will trip implementers.** Your worked example
(`40 0161 1E01 FF02`) omits BTHome's packet-id object, so the battery is at
position 0 and the light at position 1. The Espruino module emits the packet id
— your own `getAdvertisement` always does — which puts it at position 0 and
makes the same device advertise `FF 04`, not `FF 02`.

Correct under the same rule, but it caught me while writing the module. The spec
now says so normatively (§2.2) and shows the same device both ways (§8.3).

---

## 5. The capacity limit needed arithmetic, not a round number

"Everything must fit in a 31-byte advertising payload" is true but not
actionable: the Flags AD structure (3 bytes) and the Service Data header (4)
come out first, and then the device-information byte. The usable budget is **23
bytes for objects, declaration included**. Spelled out in §2.3 and enforced at
`setup()` on the device side.

Eight writable one-byte objects plus the declaration come to 18 bytes, so the
limit is comfortable — but it is much tighter than "31" suggests, and a device
that also advertises a complete local name has considerably less.

---

## 6. Provisional UUIDs, if you have a convention — ANSWERED

```
Service                2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2
Write characteristic   2FAA0002-3B0B-4B1A-9E2A-B4C2952E62F2   (write, write-no-response)
```

Answered on 2026-09-10: one randomly assigned 128-bit base, varying only the
second 16-bit group per characteristic, rather than two independent UUIDs — the
ordinary Bluetooth convention, and one base to store instead of two. Adopted
(D-001). Still frozen only at the first release.

---

## 7. Verified, for the thread

`bthome-ble` skips an unknown object ID with a DEBUG log and stops parsing
there; it does not error. So the declaration can live in the BTHome service data
itself and the manufacturer-data fallback is not needed. The catch: objects
placed *after* the declaration are silently dropped for every existing BTHome
install, so "declaration last" had to become a MUST rather than a SHOULD.

Checked on both `bthome-ble` 3.24.0 and 3.22.1 (the version Home Assistant
2025.1 pins). Method and full findings in `decisions.md` D-005; the check is a
test in CI, so a regression on a future release surfaces on the next dependency
bump.

Pleasant side effect: `bthome-ble` already names duplicate objects `light_1`,
`light_2`, … by their order in the packet — the same positional model as the
bitmask, so upstream entity naming and our addressing agree by construction.

---

## 8. The `BTHome` module has no `illuminance` type — FIXED

Added in EspruinoDocs master on 2026-09-10 as
`illuminance : e => b24(5, e, 100)`, which is exactly the encoding needed.
Not yet published to espruino.com/modules, so this repo's example still
goes through `raw` for now.

BTHome object `0x05` (illuminance, uint24, 0.01 lux) is not in
`getAdvertisement`'s table. It is a common enough sensor that its absence is
noticeable — the light-loop example in this repo wanted it and had to go
through the `raw` escape hatch instead:

```js
{ type: "raw", get: () => [0x05, v & 255, (v >> 8) & 255, (v >> 16) & 255] }
```

That works, and `raw` is clearly there for exactly this, but it puts the object
ID and the byte order in the sketch rather than in the table where every other
object's encoding lives. A one-line addition alongside `pressure`, which is
already a `b24`:

```js
illuminance : e => b24(5, e, 100),      // lux, floating point
```

A related note for anyone reading that table: `raw` means "emit these bytes
verbatim", which is *not* BTHome's raw object `0x54` (length-prefixed). Two
different things sharing a name; worth a comment in the module, and something a
wrapper has to be careful about — this repo's module briefly treated `raw` as
length-prefixed and would have mis-parsed writes to one.

---

## 9. `AES.encrypt` in CTR mode ignores its `iv` — a security bug

Found on Puck.js 2v27 while working out whether BTHome's AES-CCM is affordable
on an nRF52. Two IVs with no byte in common give the same answer, and it is
`E(0…0)`: the counter block is always zero.

```
iv 000102030405060708090a0b0c0d0e0f  ->  1838858c73da85d4885458a8e5dbda4f
iv ffeeddccbbaa99887766554433221100  ->  1838858c73da85d4885458a8e5dbda4f
AES-ECB of an all-zero block         =   1838858c73da85d4885458a8e5dbda4f
```

CBC and ECB are correct — both match a reference implementation byte for byte,
which is how the vectors below pass. `OFB` returns `undefined` rather than a
result, which may be the same root cause.

**Why it is worth more than a bug report.** CTR over a nonce is the obvious way
to build a stream cipher, and this one silently uses one keystream for every
message under a key: two ciphertexts XOR to the two plaintexts XORed. It looks
like it works. Anyone who reached for it has no confidentiality between
messages, and nothing told them.

It costs this project only an extra loop — the CCM keystream comes from one ECB
call over the concatenated counter blocks instead — so there is no hurry on our
account.

Reproduce with `python -m tools.ccm_bench --address <mac>`.

---

## 10. CCM is affordable, and needs no JavaScript AES

For the record, since it was an open question: BTHome's AES-CCM composes out of
Espruino's native CBC and ECB. All sixteen test vectors reproduce byte for byte
on a Puck.js 2v27, in **75 ms per frame** -- of which under 5 ms is the cipher.
(A first version did it in two large calls at 31.8 ms, and broke on the point
below; asking for 32 bytes at a time is what costs the difference.)

`AES.ccmEncrypt` would be better still, but `USE_AES_CCM` is not set in the
Puck.js build — if it is cheap to enable there, it would remove the framing
entirely.

The remaining 27 ms is interpreted JavaScript, and the profile is worth knowing
generally: **touching one typed-array element from JS costs about 0.7 ms on this
board**, so an 8-byte XOR loop outweighs all of the AES.

---

---

## 11. `AES.encrypt` returns `undefined` when it cannot allocate its result

Related to the above, and the more annoying of the two to debug.

`AES.encrypt` allocates its result as one contiguous run of the heap. When there
is no run that long it prints `ERROR: Not enough memory for result` and returns
`undefined` -- so the caller's `new Uint8Array(...)` then throws
`Unsupported first argument of type undefined`, pointing at a line that has
nothing wrong with it.

The threshold moves with how full the heap is, which made it look like a size
limit at first:

```
                        free blocks   16   32   48   64   128
sketch running                 1494    ok   ok   ok  FAIL  FAIL
fresh interpreter              2567    ok   ok   ok    ok    ok
```

`process.memory().free` does not predict it -- it counts free blocks, not
consecutive ones. In the same session where a 48-byte AES call failed, a REPL
`new Uint8Array(256)` succeeded.

Two things would help anyone hitting this: throwing rather than returning
`undefined`, and a message that says contiguous rather than "not enough memory"
when there are 24 kB free. Working around it is easy once understood -- ask for
32 bytes at a time, chain CBC through its IV -- but it costs about twice the
time, and the way it presents gives no clue what to try.

---

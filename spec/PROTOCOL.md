# BTHome Writable — protocol specification

**Version:** 1.0-draft.1 · **Status:** DRAFT, nothing frozen · **License:** MIT

BTHome standardizes a BLE **uplink**: a device broadcasts its state in
advertising, a receiver parses it. It has no **downlink**. This document
specifies a minimal extension by which a device declares, inside its ordinary
BTHome advertising, that some of the objects it advertises may be *written*, and
by which a receiver writes new values to them over a short GATT connection.

The extension deliberately introduces **no new data format**: written values are
encoded exactly as BTHome encodes them in advertising, and encrypted exactly as
BTHome encrypts advertising.

Designed publicly with Gordon Williams (Espruino) in
[espruino#8013](https://github.com/orgs/espruino/discussions/8013). Object IDs
used here are **not yet reserved** by the BTHome project; see §9.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted
as in RFC 2119.

---

## 1. Terminology

| Term | Meaning |
|---|---|
| **Device** | The BLE peripheral advertising BTHome service data. |
| **Receiver** | The central parsing that advertising and issuing writes (Home Assistant, in the reference implementation). |
| **Object** | One BTHome measurement element: an object ID byte followed by its value bytes. |
| **Declaration** | The object introduced by this spec that marks which objects of the same packet are writable (§2). |
| **Declaration packet** | The single advertising payload containing the declaration and every writable object (§2.1). |
| **Position** | The 0-based index of an object within the declaration packet, counting objects, not bytes, and excluding the device-information byte. |
| **Write** | One GATT write to the characteristic of §4, carrying new values for every writable object. |

This specification targets **BTHome v2** and its 16-bit service data UUID
`0xFCD2`. BTHome v1 is out of scope.

---

## 2. Writability declaration

### 2.1 The same-packet rule

> A device MUST place the declaration and **every** object it declares writable
> inside **one** advertising payload — the declaration packet.

Devices that rotate several advertising payloads MAY do so freely for their
non-writable sensors, but the declaration packet MUST always be complete in
itself.

This single rule resolves two problems at once:

- **Rotation.** A receiver never has to correlate objects seen across different
  payloads to know what is writable.
- **Multiple instances of the same object type.** A device with ten lights
  advertises ten `0x1E` objects; the declaration and the write order (§4.2) both
  address them by *position* within the packet, so instances are unambiguous
  without inventing per-instance identifiers.

Position, not object ID, is therefore the addressing primitive throughout this
specification.

### 2.2 Format and placement

The declaration is one BTHome object:

```
0xFF <bitmask u8>
```

- Object ID `0xFF` (unassigned in BTHome as of `bthome-ble` 3.24.0, whose highest
  assigned ID is `0xF2`).
- Bit *n* of the bitmask set to 1 means the object at **position *n*** of this
  same packet is writable. **Bit 0 is the first object.**
- A bitmask of `0x00` is legal and means "nothing writable"; a device SHOULD then
  omit the declaration entirely.

> **Positions count every object in the packet, including BTHome's own.** A
> device that emits the packet-id object (`0x00`) — as most do, and as the
> Espruino BTHome module always does — puts it at **position 0**, so its first
> sensor is at position 1 and every bitmask bit shifts by one. This is
> well-defined but easy to get wrong when reading the worked examples of §8,
> which omit the packet id for brevity. §8.4 shows the same device both ways.

**The declaration MUST be the last element of the BTHome service data.** This is
normative, not stylistic: the reference BTHome parser stops at the first object
ID it does not recognise, so any object placed *after* the declaration is
silently dropped for every existing BTHome installation. Placing it last also
satisfies BTHome's ascending-object-ID convention for free, since `0xFF` is above
every assigned ID. Measured behaviour and method are recorded in
[`decisions.md` D-005](decisions.md).

### 2.3 Capacity

The declaration and all writable objects MUST fit, together with the rest of the
declaration packet, in a single legacy BLE advertising payload. Devices MUST
enforce this at configuration time and fail loudly rather than truncate.

A legacy advertising payload is 31 bytes, but BTHome objects do not get all of
them. The usable budget is:

```
31   advertising payload
 -3  Flags AD structure (02 01 06), for connectable undirected advertising
 -4  Service Data AD header: length byte, type 0x16, 16-bit UUID 0xFCD2
 --
 24  BTHome service data
 -1  device-information byte
 --
 23  bytes available for objects, declaration included
```

Devices advertising anything else in the same payload — a complete local name,
for instance — have correspondingly less. Implementations SHOULD put such
elements in the scan response rather than spend the declaration packet on them.

This is not a practical restriction: writable objects are actuators, and devices
have few of them. Eight writable one-byte objects plus the declaration come to
18 bytes. It is stated explicitly so implementations agree on the limit, and the
arithmetic is spelled out because "31 bytes" alone is not actionable.

### 2.4 Extension headroom

Version 1 of this specification uses a one-byte bitmask and therefore supports at
most **8 writable objects** per device. A future version MAY extend the bitmask
by adding bytes; a receiver determines the bitmask width from the declaration's
length, so the extension is backward-compatible by construction.

### 2.5 Container fallback (contingency, not in use)

Should a future BTHome parser reject unknown object IDs rather than skip them,
the identical `<tag> <bitmask>` payload can be carried in a manufacturer-data AD
element instead of the service data. Implementations SHOULD keep declaration
parsing behind a single function per codebase so that the container can change at
the cost of that one function.

This path is **not currently needed** (D-005) and its details — company ID and
tag byte — remain unspecified.

---

## 3. Write-only objects

Some actuators have no meaningful state to report back: a text display whose
content exceeds the advertising budget, a buzzer, a trigger.

A device declares such an object by advertising it with an **empty or zero
value** — for a variable-length object, a length of 0 — and setting its
writability bit as usual.

- The device MUST NOT advertise the value that was written to a write-only
  object. The advertised value stays empty for the device's lifetime.
- Receivers MUST expose write-only objects as **stateless** entities and MUST NOT
  apply the confirm/revert model of §6 to them.

A zero-length object is skipped by the reference BTHome parser without error and
produces no sensor entity, so the placeholder costs nothing to existing BTHome
receivers (D-005).

---

## 4. The write characteristic

### 4.1 GATT

One primary service with one characteristic:

```
Service                2FAA47BC-3B0B-4B1A-9E2A-B4C2952E62F2
  Write characteristic 639333F3-F21F-4558-9D85-06FCAC3436C2   (write, write-no-response)
```

> **Provisional.** These UUIDs are randomly generated and freeze permanently at
> the first public release. Until then they may still change (D-001).

The device MUST advertise connectably at all times, and MUST expose this service
whether or not encryption is in use.

There is no acknowledgement characteristic, no notification, and no readable
state: the device's refreshed advertising is the sole confirmation channel (§6).

### 4.2 Write-all in packet order

A write is the concatenation of `<object ID> <value>` for **every** writable
object of the declaration packet, in **the same order** as those objects appear
in that packet:

```
<objectID_0> <value_0> <objectID_1> <value_1> ... <objectID_k> <value_k>
```

Values are encoded exactly as BTHome encodes them in advertising, including the
length byte of variable-length objects.

The object IDs are redundant — position already determines which object is
addressed — but they are transmitted anyway for two reasons: the payload stays in
pure BTHome format, and they act as a desync guard.

> The device MUST verify each object ID against the one it expects at that
> position, and MUST reject the **entire** write on any mismatch.

This catches the case where the device has been reflashed with a different
object layout while the receiver still holds the old one.

The device MUST also reject a write that is shorter than expected, or that
carries trailing bytes beyond the last expected object. Unlike advertising
parsing, which is permissive by design, writes are a closed format: strictness
here is a safety property, not pedantry.

A write MUST be applied atomically: either every value is accepted and applied,
or none is.

### 4.3 No-op values

Because a write always carries every writable object, a receiver that wants to
change one object needs a way of saying "leave this one alone" for the others.
For read-write objects the answer is simply to resend the last advertised value.
Write-only objects have no such value, so this specification defines:

| Object class | No-op encoding |
|---|---|
| Variable-length (text, raw) | Length byte `0x00` — "do not modify". |
| Event / trigger-like | BTHome's existing "none" event value, `0x00`. |

Both reuse BTHome's own semantics rather than inventing a sentinel.

### 4.4 MTU and long writes

Receivers SHOULD negotiate an ATT MTU of at least 64 bytes. Devices SHOULD
support queued (long) writes so that text payloads are not limited by the MTU.

At the default MTU of 23 a single write carries 20 payload bytes. A device that
supports neither a larger MTU nor long writes is therefore limited to writable
objects totalling 20 bytes, which excludes most text objects. Implementations
MUST document this limit rather than silently truncate.

---

## 5. Encryption

Writes reuse BTHome v2's AES-CCM unchanged: same bindkey, same 4-byte MIC, same
13-byte nonce construction, with two deltas.

### 5.1 Direction separation via the device-information byte

The BTHome nonce already contains the device-information byte:

```
nonce = MAC (6 bytes, natural order) || 0xD2 0xFC || <device-info byte> || <counter u32 LE>
```

Advertising uses the device-information byte it transmits (`0x41` for encrypted
BTHome v2). **Writes MUST use `0xFF` as the device-information byte of their
nonce.**

A captured encrypted advertisement therefore can never validate as a write, and a
captured write can never validate as an advertisement — cryptographically, with
zero additional fields on the wire. The value `0xFF` is not transmitted in a
write; it is implicit in the direction.

> **Naming caution for implementers.** The `0xFF` of this section is a
> *device-information byte value*; the `0xFF` of §2.2 is an *object ID*. Two
> different fields that happen to share a numeric value. There is no technical
> conflict, but keep the names distinct in code and prose.

Note that direction separation alone is what makes cross-direction replay
impossible. The intuition that "a replayed advertisement would not parse as a
write because it contains the `0xFF` declaration" is **not** a defense: a
permissive write parser would skip the unknown object and apply the rest. §4.2's
strictness and this section's nonce split are the actual mitigations, and both
are required.

### 5.2 Independent counters per direction

The device-information split closes *cross*-direction replay. Replaying an old
**write** as a write is closed separately, by a counter:

- The device MUST track the highest write counter it has accepted, independently
  of its own advertising counter, and MUST reject any write whose counter is less
  than or equal to it.
- The device MUST accept forward jumps, so that a receiver which lost its state
  (reinstall, restore from backup) can resume without a factory reset.
- The device SHOULD persist the counter to non-volatile storage periodically
  rather than on every write, and on resume MUST continue from a value strictly
  greater than any it may have accepted before the last persist.
- The receiver MUST persist its write counter across restarts and SHOULD offer a
  resynchronisation step when writes start failing authentication.

### 5.3 Encrypted write payload

```
<ciphertext> <counter u32 LE> <MIC 4>
```

where the ciphertext is the AES-CCM encryption of the plaintext of §4.2.

This is byte-for-byte the layout BTHome uses for encrypted advertising, minus
the device-information byte (which for writes is implicit, §5.1). Both
directions therefore share the same framing code on both sides — which matters
on a constrained device that must both build encrypted advertising and parse
encrypted writes (D-008).

Unencrypted devices remain permitted, consistent with BTHome policy. A receiver
SHOULD warn the user when a device exposes actuator-class writable objects
without encryption.

### 5.4 Test vectors

`test-vectors/test-vectors.json` is the normative contract between
implementations: bindkey, MAC, device-information byte, counter, plaintext,
ciphertext and MIC for both directions, including cross-direction replay negative
cases. Both reference implementations consume it. A change to that file is a
change to this specification.

---

## 6. Confirmation model

1. The receiver writes, then disconnects.
2. The device applies the values and MUST refresh its advertising data
   **immediately**, without waiting for the next scheduled advertising interval
   boundary where the radio stack allows it.
3. The receiver reads the new state from the next advertisement. That
   advertisement is the confirmation; there is no acknowledgement.
4. Until confirmation arrives, the receiver MAY display the written value
   optimistically. If no confirming advertisement arrives within its confirmation
   window, the receiver MUST revert its state to the last advertised value and
   SHOULD surface a warning.
5. Write-only objects (§3) are excluded from steps 3–5.

Advertising is the single source of truth for state. A receiver MUST NOT treat a
successful GATT write as evidence that the value was applied.

The reference receiver derives its confirmation window from the device's observed
advertising interval — `max(5 s, 2 × interval)` — rather than using a fixed value,
so that slowly advertising devices do not produce spurious reverts (D-007). The
window is an implementation choice, not a normative constant.

---

## 7. Device requirements

- **Static BLE address.** A resolvable private address breaks receiver-side
  device identity and merging. Devices implementing this specification MUST use a
  static address.
- **Connectable advertising** at all times (§4.1).
- **Immediate advertising refresh** after applying a write (§6.2).
- **Capacity enforcement** at configuration time (§2.3).
- **Strict write validation**: object IDs, length, no trailing bytes (§4.2).

---

## 8. Worked examples

### 8.1 One battery-powered light

Advertising service data for `0xFCD2` (BTHome v2, unencrypted):

```
40 01 61 1E 01 FF 02
|  |     |     |
|  |     |     +-- declaration: bitmask 0b00000010 -> position 1 is writable
|  |     +-------- position 1: 0x1E light = on
|  +-------------- position 0: 0x01 battery = 97 %
+----------------- device-information byte, BTHome v2, unencrypted
```

To switch the light off, the receiver writes:

```
1E 00
```

Battery is not writable, so it does not appear in the write. The device applies
it, re-advertises `40 01 61 1E 00 FF 02`, and the receiver confirms.

### 8.2 Three lights and a display

```
40 01 61 1E 01 1E 00 1E 01 53 00 FF 1E
         |     |     |     |     |
         |     |     |     |     +-- bitmask 0b00011110 -> positions 1,2,3,4
         |     |     |     +-------- position 4: 0x53 text, length 0 (write-only)
         +-----+-----+-------------- positions 1-3: three light instances
```

Turning off only the second light, leaving the display untouched:

```
1E 01 1E 00 1E 01 53 00
|     |     |     |
|     |     |     +-- text, length 0 = no-op (§4.3)
|     |     +-------- unchanged, resent from the last advertisement
|     +-------------- the change
+-------------------- unchanged, resent from the last advertisement
```

### 8.3 The same device with a packet-id object

What §8.1's device actually broadcasts once it emits BTHome's packet-id object,
which is what the Espruino reference implementation does:

```
40 00 09 01 61 1E 01 FF 04
|  |     |     |     |
|  |     |     |     +-- declaration: bitmask 0b00000100 -> position 2
|  |     |     +-------- position 2: 0x1E light = on
|  |     +-------------- position 1: 0x01 battery = 97 %
|  +-------------------- position 0: 0x00 packet id = 9
+----------------------- device-information byte
```

Same device, same writable object, different bitmask — `0x04` rather than
`0x02` — because the packet id occupies position 0. The write itself is
unchanged (`1E 00`): §4.2 carries only the writable objects.

### 8.4 Rotation

A weather station advertising temperature and humidity in one payload and
pressure and illuminance in another MAY rotate them freely, provided the payload
carrying its writable heater relay also carries the declaration and is broadcast
on its own rotation slot. Non-writable sensors in other payloads are unaffected.

---

## 9. Status and open items

Nothing in this document is frozen. At the first public release, the following
freeze permanently and must never change afterwards: the service and
characteristic UUIDs, the declaration object ID and bitmask format, the write
payload layout, and the no-op conventions.

Open items:

1. **`0xFF` is not reserved.** The BTHome project has not assigned this object
   ID. Reserving it — ideally merging this specification — is the goal of the
   standardization step, to be pursued once a working proof of concept exists.
2. **UUIDs are provisional** pending review in espruino#8013 (D-001).
3. **Manufacturer-data fallback** details remain unspecified (§2.5), pending a
   need that does not currently exist.

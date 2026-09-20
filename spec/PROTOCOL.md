# BTHome Writable — protocol specification

**Version:** 2.0-draft.2 · **Status:** DRAFT, nothing frozen · **License:** MIT

BTHome standardizes a BLE **uplink**: a device broadcasts its state in
advertising, a receiver parses it. It has no **downlink**. This document
specifies a minimal extension by which a device lists, inside its ordinary
BTHome advertising, the BTHome object types it accepts writes for, and by which a
receiver writes values to them over a short GATT connection — one characteristic
per writable entry.

The extension deliberately introduces **no new data format**: written values are
BTHome objects encoded exactly as BTHome encodes them in advertising, and
encrypted exactly as BTHome encrypts advertising. It asks BTHome for a single
object ID.

Designed publicly with Gordon Williams (Espruino) in
[espruino#8013](https://github.com/orgs/espruino/discussions/8013). Version 2
replaces version 1's positional bitmask, write-all payload and advertising-based
confirmation; the reasons are in [`decisions.md` D-048](decisions.md).

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be interpreted
as in RFC 2119.

---

## 1. Terminology

| Term | Meaning |
|---|---|
| **Device** | The BLE peripheral advertising BTHome service data. |
| **Receiver** | The central parsing that advertising and issuing writes (Home Assistant, in the reference implementation). |
| **Object** | One BTHome element: an object ID byte followed by its value bytes. |
| **Declaration** | The object introduced by this specification, listing the writable object types (§2). |
| **Entry** | One object ID in the declaration. Entries are numbered from 1 in the order they appear. |
| **Writable characteristic** | The GATT characteristic of an entry (§4). |
| **Write** | One GATT write to one writable characteristic, carrying one object. |

This specification targets **BTHome v2** and its 16-bit service data UUID
`0xFCD2`. BTHome v1 is out of scope.

---

## 2. Declaration

### 2.1 Format

The declaration is one element of the BTHome service data:

```
0xFF <objectID_1> <objectID_2> ... <objectID_n>
```

- `0xFF` is the declaration's object ID. It is **not yet assigned** by BTHome
  (§9); `bthome-ble`'s highest assigned ID is `0xF2`.
- Each following byte is a **BTHome object ID**. Entry *k* says: "this device
  accepts writes of this object type on writable characteristic *k*" (§4.1).
- The entry's object ID alone determines the value's format, length, unit and
  meaning, from BTHome's own object table. Nothing else is declared.
- The same object ID MAY appear several times: `FF 1E 1E` is a device with two
  writable lights. Instances are distinguished by entry number, which is also how
  a receiver numbers them in its user interface.
- A declaration with no entries is legal and means "nothing writable"; a device
  SHOULD then omit it.

Entries MUST NOT be `0x00` (packet id), `0xFF`, or the device-information objects
(`0xF0`–`0xF2`). A receiver MUST NOT offer an entry whose object ID it does not
know, but MUST still count it, so that later entries keep their characteristic
numbers.

### 2.2 Placement

**The declaration MUST be the last element of the BTHome service data**, and its
entries run to the end of that data. This is normative, not stylistic: the
reference BTHome parser stops at the first object ID it does not recognise, so
anything placed after the declaration would be silently dropped for every
existing BTHome installation (`decisions.md` D-005). For encrypted advertising,
"end of the service data" means end of the plaintext, before counter and MIC.

A device that rotates several advertising payloads MUST include the declaration
in each of them, or in a payload it broadcasts at least as often as any other.

### 2.3 Writable values are not advertised

A device MUST NOT advertise the current value of an entry. The declaration says
what can be written; it carries no state.

An object in the same packet with the same ID as an entry is an ordinary sensor
and unrelated to it. A thermostat advertising `02 C4 09` (temperature 25.00 °C)
and declaring `FF 57` (a writable temperature) reports a measured temperature and
accepts a target; the two are never confused, because the target is never in the
packet.

State, where a device has any worth reporting, is read over GATT (§3).

### 2.4 Capacity

The declaration costs `1 + n` bytes for `n` entries. It MUST fit, with the rest
of the service data, in a single legacy advertising payload; devices MUST check
this at configuration time and fail loudly rather than truncate.

The 31 bytes of a legacy payload are not all available to BTHome objects. Flags
(3 bytes), the service data header (4) and the device-information byte (1) always
come out, and in practice so do other elements: Espruino always advertises its
manufacturer ID (4 bytes), and a local name costs `2 +` its length. Measured on
real devices, between 7 and 22 bytes remain for objects (`decisions.md` D-030,
D-046). Implementations SHOULD move the local name to the scan response when
space is short.

### 2.5 Container fallback (contingency, not in use)

Should a future BTHome parser reject unknown object IDs rather than skip them,
the identical entry list could be carried in a manufacturer-data element instead.
Implementations SHOULD keep declaration parsing behind one function per codebase.
This path is not needed today (D-005) and remains unspecified.

---

## 3. State and settings revision

Writable values are not advertised (§2.3), so a receiver does not observe state
by listening. How it learns state depends on the device.

### 3.1 Devices whose writable values change only when written

A relay or a display that only ever changes because a receiver wrote to it needs
nothing more. The receiver knows what it wrote; that is the state.

Receivers SHOULD present such entries as **assumed state** — shown as last set,
with the controls for every value always available, as for infrared or RF
devices.

### 3.2 Devices whose writable values can change by themselves

A thermostat with a local knob, a switch with a physical button, a schedule, a
safety cutoff, a reboot to defaults: the value changes without a write, and the
receiver cannot know.

Such a device MUST:

1. make each writable characteristic **readable** (§4.3), and
2. advertise BTHome's **settings revision** object (`0x65`, uint8), and change its
   value whenever any writable value changes other than by a write.

`0x65` exists in BTHome for exactly this: a device notifying observers that its
configuration changed, so they re-read it out of band over GATT. It does not say
what changed.

A receiver that sees `0x65` take a value different from the last one it saw
SHOULD connect and read every writable characteristic of the device. It SHOULD
also read them the first time it sees the device, and after it restarts, so that
it starts from the real state. A device's own restart typically changes its
settings revision too, which triggers the same re-read.

A device MUST NOT change `0x65` in response to a write it received: the receiver
already knows that value.

---

## 4. GATT

### 4.1 Service and characteristics

```
Service                      2FAA0000-3B0B-4B1A-9E2A-B4C2952E62F2
  Writable characteristic 1  2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2
  Writable characteristic 2  2FAA0002-3B0B-4B1A-9E2A-B4C2952E62F2
  ...
  Writable characteristic k  2FAAkkkk-3B0B-4B1A-9E2A-B4C2952E62F2
```

One randomly generated 128-bit base; the second 16-bit group is `0000` for the
service and the entry number *k*, in hexadecimal, for entry *k*. There is exactly
one writable characteristic per entry, and none for anything else.

> **Provisional.** These UUIDs freeze permanently at the first public release.
> Until then they may still change (D-001).

The device MUST advertise connectably at all times, and MUST expose this service
whether or not encryption is in use.

**The service UUID MUST NOT be advertised.** A 128-bit UUID would cost 18 bytes of
a 31-byte payload and buys nothing: a receiver finds the device by its BTHome
service data, connects by address, and discovers the service over GATT.

### 4.2 Writes

A write to writable characteristic *k* carries **one BTHome object**:

```
<objectID> <value>
```

encoded exactly as BTHome encodes it in advertising, including the length byte of
variable-length objects (text `0x53`, raw `0x54`, command `0x3B`).

- **Write with response.** Receivers MUST write with response, and devices MUST
  support it. The response is the receiver's evidence that the write was
  delivered; applying it is the device's responsibility.
- **Desync guard.** The device MUST reject a write whose object ID differs from
  entry *k*'s, or whose length does not match what that object ID requires. This
  catches a receiver still holding the layout of firmware the device no longer
  runs.
- **No trailing bytes.** A write carries exactly one object; anything after it is
  an error.
- **Events are writable.** A button (`0x3A`), dimmer (`0x3C`) or command (`0x3B`)
  write means "perform this now". Because only the entry written is touched, a
  write never triggers an event on another entry.
- **No automatic resend.** A receiver MUST NOT resend a write that was
  acknowledged. Values such as toggle or step are not idempotent.

A device SHOULD reject a write with an ATT error when its platform allows it.
Some do not (Espruino acknowledges before application code runs); a rejected write
is then silent, which is why §3 exists for devices whose state matters.

### 4.3 Reads

A readable writable characteristic returns the entry's **current value**, as one
BTHome object in exactly the format of a write: `<objectID> <value>`.

Readability is required by §3.2 and optional otherwise. A receiver MUST NOT read a
characteristic after writing it merely to confirm the write; the write response
already does that.

### 4.4 Size of a write

**A write MUST fit in one ATT Write Request, and therefore carries at most
`ATT_MTU - 3` bytes** — the opcode and the attribute handle take the other three.
That is the protocol's ceiling on how much can be sent to a device at once.

For an object that is length-prefixed, two of those bytes are its own framing:
text (`0x53`) carries at most `ATT_MTU - 5` characters. A device MAY accept less
than the MTU allows, since its characteristic declares a maximum length of its
own; the effective ceiling is the smaller of the two, and a receiver discovers it
only by being refused.

**Fragmentation is out of scope.** This specification defines no way to split a
value across several writes: no sequence numbers, no assembly rule, and no
statement about what a device shows between the pieces. A receiver MUST NOT
attempt a queued (long) write, and MUST NOT silently truncate a value that does
not fit: it refuses the command and says so, as it would for any other write that
cannot be delivered (§6).

Receivers SHOULD negotiate an ATT MTU of at least 64 bytes, which raises the
ceiling; at BLE's guaranteed 23 a write carries 20 bytes, enough for every
fixed-length object and for 18 characters of text. Implementations MUST document
the limit they end up with rather than leave a user to discover it.

---

## 5. Encryption

Writes and reads reuse BTHome v2's AES-CCM unchanged: same bindkey, same 4-byte
MIC, same 13-byte nonce construction, with one delta — the direction.

### 5.1 Direction in the nonce

```
nonce = MAC (6 bytes, natural order) || 0xD2 0xFC || <device-info byte> || <counter u32 LE>
```

| Direction | Device-information byte in the nonce |
|---|---|
| Advertising | as transmitted (`0x41` for encrypted BTHome v2) |
| Write (receiver → device) | `0xFF` |
| Read (device → receiver) | `0xFE` |

The write and read values are not transmitted; they are implicit in the
operation. A captured advertisement therefore never validates as a write or a
read, and a captured read never validates as a write — cryptographically, with no
extra field on the wire.

> **Naming caution.** The `0xFF` above is a device-information byte value; the
> `0xFF` of §2.1 is an object ID. Different fields sharing a number.

### 5.2 Sealed payload

A sealed write or read is

```
<ciphertext> <counter u32 LE> <MIC 4>
```

where the ciphertext is the AES-CCM encryption of the plaintext object of §4.2 or
§4.3. This is byte-for-byte BTHome's encrypted advertising layout minus the
device-information byte, so both sides share one framing routine for every
direction (D-008).

### 5.3 Counters

- **Writes.** The receiver keeps one write counter per device, across all its
  characteristics, and MUST persist it across restarts. The device MUST track the
  highest write counter it has accepted and MUST reject any write whose counter is
  less than or equal to it; it MUST accept forward jumps, so a receiver that lost
  its state can resume. The device SHOULD persist its counter periodically and on
  resume MUST continue strictly above anything it may have accepted.
- **Reads.** The device seals each read with a counter it never reuses under the
  read device-information byte. It MAY use its advertising counter; the nonces
  differ by direction.

The receiver SHOULD offer a resynchronisation step when writes start failing
authentication.

### 5.4 Unencrypted devices

Remain permitted, consistent with BTHome policy. A receiver SHOULD warn once per
device that exposes writable entries without encryption.

### 5.5 Test vectors

`test-vectors/test-vectors.json` is the normative contract between
implementations: bindkey, MAC, direction, counter, plaintext, sealed payload, for
advertising, writes and reads, including cross-direction negative cases. Both
reference implementations consume it. A change to that file is a change to this
specification.

---

## 6. Receiver behaviour

- **Discovery.** A device is writable if its BTHome service data ends with a
  declaration of at least one known entry. The receiver discovers the GATT
  service by connecting; it MUST NOT rely on a cached GATT table across a change
  of declaration, since a changed layout usually means new firmware and a rebuilt
  table.
- **Writing.** Connect, write with response to the entry's characteristic,
  disconnect. Several writes to one device SHOULD share a connection.
- **Failure.** A write that is not acknowledged MUST be reported to the user and
  MUST NOT be shown as applied.
- **State.** Assumed state for §3.1 devices; read state for §3.2 devices.
- **Availability.** From advertising presence, exactly as for any BTHome device.

---

## 7. Device requirements

- **Static BLE address.** A resolvable private address breaks receiver-side
  identity and merging with the core BTHome device.
- **Connectable advertising** at all times (§4.1).
- **Capacity check** at configuration time (§2.4).
- **Strict write validation**: object ID, length, no trailing bytes (§4.2).
- **Settings revision and readable characteristics** when writable values can
  change by themselves (§3.2).

---

## 8. Worked examples

### 8.1 One light

Advertising service data for `0xFCD2` (BTHome v2, unencrypted):

```
40 00 09 01 61 FF 1E
|  |     |     |
|  |     |     +-- declaration: entry 1 = 0x1E light
|  |     +-------- 0x01 battery = 97 %
|  +-------------- 0x00 packet id = 9
+----------------- device-information byte
```

To switch the light on, the receiver writes `1E 01` to characteristic
`2FAA0001-…` and receives the write response. The light has no local control, so
the device needs no settings revision and the receiver shows it as assumed state.

### 8.2 Thermostat with a local knob

```
40 00 09 02 C4 09 65 03 FF 10 57
         |        |     |
         |        |     +-- entries: 1 = 0x10 power, 2 = 0x57 temperature (target)
         |        +-------- 0x65 settings revision = 3
         +----------------- 0x02 temperature = 25.00 °C (measured, a sensor)
```

- Target 22 °C: write `57 16` to characteristic `2FAA0002-…`.
- Someone turns the knob to 20 °C: the device advertises `65 04`. The receiver
  sees the revision change, connects, reads characteristic 1 (`10 01`) and
  characteristic 2 (`57 14`), and shows heating on, target 20 °C.
- The device does not change `0x65` after the 22 °C write: the receiver already
  knows.

### 8.3 Two lights and a display

```
40 00 09 FF 1E 1E 53
            |  |  |
            |  |  +-- entry 3: 0x53 text -> characteristic 2FAA0003
            |  +----- entry 2: 0x1E light -> characteristic 2FAA0002
            +-------- entry 1: 0x1E light -> characteristic 2FAA0001
```

Turning off the second light writes `1E 00` to characteristic 2 and nothing else.
Showing "Hello" writes `53 05 48 65 6C 6C 6F` to characteristic 3.

### 8.4 A momentary action

```
40 00 09 FF 3A
```

Writing `3A 01` (button, press) to characteristic 1 opens a gate. There is nothing
to confirm and nothing to read: the write response is the whole interaction.

---

## 9. Status and open items

Nothing in this document is frozen. At the first public release the following
freeze permanently: the service and characteristic UUID scheme, the declaration
object ID and format, the write and read payload layout, and the direction bytes
of §5.1.

Open items:

1. **`0xFF` is not reserved.** Asking BTHome to reserve this one object ID is the
   standardization step (`bthome-dossier.md`), pursued once a working
   implementation exists.
2. **UUIDs are provisional** (D-001).
3. **Settings revision in the Espruino module.** The upstream `BTHome` module has
   no type for `0x65` yet; devices use its `raw` escape hatch until it does.

Settled since draft.1: the size of a write is `ATT_MTU - 3` and fragmentation is
out of scope (§4.4, `decisions.md` D-058).

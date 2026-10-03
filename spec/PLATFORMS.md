# Object ↔ platform mapping

How a receiver turns a writable BTHome object into a control. This is the T2.1
deliverable, and it is **receiver guidance, not wire format**: nothing here
changes a byte on the air, and `PROTOCOL.md` stands alone without it. Two
receivers that disagree here still interoperate — they just present the same
device differently, which is reason enough to write it down.

Object ids, lengths, formats and units are **not repeated here**. They belong to
BTHome, and this project reads them from `bthome-ble` at runtime
(`protocol._object_table`) rather than keeping a copy that would drift the first
time BTHome assigns a new id.

## The classification

`bthome-ble` already sorts every object into four kinds, and that sorting is the
one this table uses. The counts are of the library, so they move when BTHome
assigns an id; these are **92 objects, counted against `bthome-ble` 3.9.2** with
`protocol.describe`:

| kind | count | writable ⇒ platform |
|---|---|---|
| binary sensor | 28 | `switch` |
| numeric sensor | 59 | `number` |
| string (`0x53`) | 1 | `text` |
| event (`0x3A` button, `0x3C` dimmer, `0x3B` command) | 3 | `button`, one per value |
| raw (`0x54`) | 1 | — not exposed |

**Recounted 2026-10-03, and the previous correction was wrong twice over.**
The counts above are measured against **`bthome-ble` 3.22.1**, which is what the
integration's test environment installs and what `manifest.json` pins as its
minimum. The note that stood here said 3.9.2 and claimed the metadata objects
`0xF0`–`0xF2` "are not in the library" — both false:

| library | objects | `0xF0`–`0xF2` |
|---|---|---|
| 3.22.1 (integration, `manifest.json`) | 92 | absent |
| 3.24.0 (tools environment, `requirements-dev.txt`) | 95 | **present**, as `device_type_id`, `firmware_version_4`, `firmware_version_3` |

So they were *added* later rather than never present, and the earlier total of 95
was right for a newer library than the one it was attributed to. Nothing
functional turns on it — `FORBIDDEN_ENTRIES` refuses `0xF0`–`0xF2` either way
(§2.1) — but the numbers in this table move with the library, so **state the
version whenever you quote them.** The classification itself is read from
`bthome-ble` at runtime and is never copied into this project, which is why a
new object type needs no code change here.

### Why the device decides, not the table

An earlier draft of the switch platform exposed only four of the 28 binary
classes — `generic`, `power`, `light`, `lock` — on the reasoning that a
`motion` switch is nonsense.

That reasoning is wrong, and worth saying why. **A device does not declare an
object writable by accident**: the entry costs it a byte of advertising and a
GATT characteristic. A
device advertising a writable `window` is telling us it has a window opener; one
advertising a writable `garage_door` has a garage door. Refusing those makes
them unusable, in the name of protecting the user from a device they own.

The conservative list also fails at its own goal, because the awkward cases do
not divide cleanly. A writable `motion` is odd; a writable `running` or
`problem` is exactly how a device would expose a mode it can be put into.

So: **every declared-writable object of a supported kind becomes a control**,
named after its BTHome class so the user can see what it is. A device that
declares something strange presents as something strange, which is the truthful
outcome.

### Not exposed, and why

- **`raw` (`0x54`)** carries bytes with no agreed meaning. There is no control
  that can offer "arbitrary bytes" usefully, and guessing an encoding would be
  worse than declining.
- **Metadata (`0xF0`–`0xF2`)**: device type and firmware version. A receiver
  that let a user write these would be offering to lie about the device.
- **The packet id (`0x00`) and the declaration (`0xFF`)** are the protocol's own
  fields, and §2.1 forbids them as entries. An entry naming one is counted — so
  that the entries after it keep their characteristic numbers — and never
  offered (`forbidden-entry` in the fixtures). The same goes for an object ID
  this receiver does not know (`unknown-entry-type`).

## Per-platform rules

### `switch` — binary objects

One switch per writable binary object. Multiple instances of the same id are
numbered the way `bthome-ble` numbers duplicate sensors (`light_1`, `light_2`),
so a device's controls and its readings are numbered by one scheme rather than
two.

The value is one byte, `0x00` or `0x01`, written to that entry's own
characteristic and nothing else. The state follows §3: what was last written,
shown as assumed state, unless the device reports state — it advertises a
settings revision and serves readable characteristics — in which case it is what
was last read.

### `number` — numeric objects

The bounds are **derived, not invented**. `bthome-ble` gives each object a data
length, a signedness and a factor, which is exactly a range and a step:

```
step  = factor
min   = 0                        (unsigned)
      = -(2^(8·len-1)) · factor  (signed)
max   = (2^(8·len) - 1) · factor (unsigned)
      = (2^(8·len-1) - 1) · factor  (signed)
```

So a 2-byte unsigned object with factor 0.01 offers 0 … 655.35 in steps of 0.01,
and a 2-byte signed one offers −327.68 … 327.67. The unit comes from the same
table.

These are the *encoding's* limits, not the device's: a device whose dimmer only
goes to 100 has no way to say so in BTHome today. A receiver therefore cannot
prevent an out-of-range write, and the device is entitled to clamp or reject it
(§4.2 rejects the whole write). Worth knowing before treating the slider's range
as a promise.

### `text` — the string object

One `text` entity. A text object is normally write-only: nothing writable is
advertised in version 2, and a display has no reason to serve a readable
characteristic. So the entity's state is what the receiver last sent, and it is
unknown until something is sent — including after a restart. Restoring a
remembered value would assert something the receiver cannot check.

The maximum length is `ATT_MTU - 5` characters — three bytes of ATT framing and
two of the object's own (§4.4) — or less, where the device's characteristic
declares a smaller maximum: 48 characters on one board measured, 126 on another
(`decisions.md` D-017, D-035). Nothing splits a longer value across several
writes, by design, so a receiver lets the device refuse rather than guessing, and
reports the refusal rather than truncating.

### `button` — event objects

An event is naturally stateless: pressing writes the event to that entry's
characteristic, and there is no resting value to show. Nothing is coalesced
either — two presses are two writes, because the second is not a repeat to
drop.

**One button per value of the vocabulary**, read from `bthome-ble`: a writable
button object becomes seven buttons (press, double press, … hold press), a
dimmer becomes two (rotate left, rotate right). Picking a favourite would make
the rest unreachable, which is the mistake the switch platform used to make.

A dimmer's second byte is a step count; a press sends one step.

**`0x3B command` is offered**, which version 1 could not do. Its `0x00` is
`off`, a real command with no no-op, and a write-all payload would have sent it
one every time anything else on the device was written. Version 2 writes one
entry and nothing else, so the difficulty disappears (D-048). Its vocabulary is
five buttons — off, on, toggle, step up, step down — and the step commands carry
a one-step argument.

Its framing is `<argument length, low 5 bits><opcode><arguments>`, so **one
entry accepts writes of two different lengths**. That is unlike every other
object: a fixed-width object has one length and a length-prefixed one announces
its own. Until 2026-10-03 this sentence was true of the receiver and false of
the reference device — the Espruino module had no way to describe the framing,
so every command write it received was refused as `trailing_bytes` (D-081).
Both sides now agree, and the `writable-command` fixture pins the two shapes.

## How a brightness finds its light  [DECISION — ruled out of scope]

The task breakdown asks for "light+brightness": a writable `light` (`0x1E`)
paired with a writable level object, presented as one Home Assistant `light`
with a brightness slider instead of a switch and an unrelated number.

**BTHome has no way to express that pairing.** There is no grouping, no parent
id, no ordering rule that says "this level belongs to that light". The
candidates all have costs:

1. **Adjacency** — a level immediately following a light in the packet belongs
   to it. Costs nothing on the air and uses the ordering §2.1 already makes
   meaningful, but it is a convention two implementations could easily read
   differently, and it makes packet order load-bearing in a new way.
2. **A new object** carrying the pairing. Honest and explicit; costs a second
   BTHome object id, where the whole of this extension currently asks for one.
3. **Leave it apart** — a `switch` and a `number`, and let the user group them
   in Home Assistant. Costs nothing and asks something of every user.

**Ruled out of scope** (D-073), by Gordon and accepted by the owner: *"dealing
with the meaning of the stuff that appears in home assistant is probably out of
scope of the spec anyway."* The protocol carries a command and says nothing about
what the receiver makes of it.

**So option 3 is the answer, not a holding position**: a writable `light` is a
switch, a writable level is a number, and nothing pairs them. A user who wants
one control groups them in Home Assistant, which is where that kind of meaning
belongs. The alternatives are kept above because they are the reasoning, and
because anyone proposing a grouping object to BTHome will meet them again.

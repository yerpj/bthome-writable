# Changelog: the protocol

Every change to [`PROTOCOL.md`](PROTOCOL.md), newest first. The number in that
document's own header is the number here, and `tools/tests/test_changelog.py`
fails if the two disagree: a specification that changes without saying so is how
four hand-written fixtures spent twelve days contradicting §2.1 (D-083).

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
A draft number is not a semantic version: nothing is frozen until the first
release, and `decisions.md` carries the reasoning and the measurement behind
each line below.

## 2.0-draft.8 - 2026-10-22

### Added

- **§3.2**: a device MAY **group** changes that happen close together into a
  single change of the settings revision, provided the revision has changed by
  the time the last of them is in effect and the readable characteristics then
  return the values it settled on. A clarification of the existing requirement
  rather than a new one, but the obvious reading of that requirement was one
  revision change per change, and announcing each one on its own costs a packet
  rebuild of 26 to 38 ms, or 375 ms sealed (D-124).

### Changed

- **§4.1** says the entry numbering is per device, not global (D-103), and
  **§2.1** names what positional addressing would have cost and corrects an
  entry-count figure nobody had measured (D-105). Both were written on
  2026-10-15 **without bumping the draft number**, so they are recorded here
  under the number that first carries them. This changelog exists so that
  cannot happen again.

## 2.0-draft.7 - 2026-10-05

### Added

- **§5.6, the counter report** (optional): a receiver that has lost its place
  in the write counter writes a challenge to `2FAA1000` and reads back the
  device's current counter, sealed under the read direction. The device MUST
  seal the report and MUST NOT answer in clear; the receiver MUST check that
  its challenge came back and SHOULD resume at `counter + 1`; a write there is
  not an entry write and MUST NOT advance the counter of §5.3 (D-083, with
  Gordon assenting in espruino#8024, D-086).

### Fixed

- **§5.1**: the MAC bytes of the nonce were specified **reversed**. Found by an
  independent audit and checked against `bthome-ble`, which is the receiver
  that has to agree (D-083).
- **§4.2**: **one command per connection**. A receiver MUST NOT hold the link
  open, where the document had merely said that several writes SHOULD share a
  connection (D-084).
- **§2.4** and **§1**: the declaration's cost restated as `1 + n` bytes made
  explicit as a count byte and one byte per entry, a real `showName` measurement
  in place of an invented one, and "receiver" said plainly to mean the central
  (D-084).

## 2.0-draft.6 - 2026-10-01

### Added

- **§4.1**: characteristic numbers `2FAA1000` and above are reserved for the
  protocol itself, so that an entry's number can never collide with a mechanism
  added later. Proposed by Gordon in espruino#8024 (D-077).

## 2.0-draft.5 - 2026-09-30

### Changed

- **§5.3**: a write counter must be **ahead**, not merely greater. A counter `C`
  is ahead of `LAST` when `(C - LAST) mod 2^32` lands in `1..0x80000000`, which
  makes wrap-around work and lets a receiver that lost its place jump forward
  without being refused. Proposed by Gordon in espruino#8024 (D-076).
- **§4.2**: one receiver per device (D-074), written on 2026-09-30 without a
  bump of its own and so carried by this number.

## 2.0-draft.4 - 2026-09-29

### Changed

- **§2.1**: the declaration gains a **length byte**, which was Gordon's
  condition for it, and a device sends **one declaration** rather than several.
  No MTU floor is required of a receiver (D-073, agreed in espruino#8013).

## 2.0-draft.3 - 2026-09-29

### Changed

- **§2.1**: the settings revision `0x65` cannot be declared writable, alongside
  `0x00`, `0xFF` and `0xF0`-`0xF2`. Raised by an independent review's object
  inventory (D-072).

## 2.0-draft.2 - 2026-09-20

### Changed

- **§4.4**: a write carries one object in one ATT Write Request, so at most
  `ATT_MTU - 3` bytes, and fragmentation is out of scope. A tightening rather
  than a change of mechanism: it says what every implementation already did
  (D-058).

## 2.0-draft.1 - 2026-09-17

### Added

- **Protocol version 2**, agreed with Gordon in espruino#8013 on 2026-09-17/18:
  a device lists the writable object **types** in a `0xFF` declaration object,
  each entry gets its own GATT characteristic, and a writable value is never
  advertised. This replaced version 1's positional bitmask, its write-all
  payload and its advertising-based confirmation (D-048).

## 1.0-draft.1 - 2026-09-08

The first specification, now **superseded in part**: its positional bitmask,
write-all payload and confirmation by refreshed advertising are gone. What
survives is in `SPEC-WORKING-DOCUMENT.md`, which says so in its own banner.

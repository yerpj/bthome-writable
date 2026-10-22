# Changelog

What changed in the two things this repository ships: the Home Assistant
integration in `custom_components/bthome_writable/`, versioned in its
`manifest.json` and tagged in git, and the Espruino module in
`espruino/BTHomeWritable.js`, which EspruinoDocs serves by name and which
therefore carries no version of its own: it rides the release below it. The
protocol has its own changelog, [`spec/CHANGELOG.md`](spec/CHANGELOG.md),
because it is versioned on its own axis.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project means to follow [Semantic Versioning](https://semver.org/) from
its first non-draft release. Every entry names the decision behind it:
`spec/decisions.md` has the reasoning and, where there is one, the measurement.

## [Unreleased]

Everything here is on `candidate/enaon-retest` and not yet on `main`.

### Added

- The integration chooses which Bluetooth adapter to connect through, by what
  actually hears the device, rather than taking the first answer the stack
  gives. A write through an ESP32 proxy that could not reach the device was
  being lost without a word (D-117).
- A write to an entry the device can also report is read back and checked. A
  device that applies a write slowly, a fade or a ramp, is logged rather than
  called broken, because §4.3's getter is published and not served on demand
  (D-117, D-120, D-122).
- The `bthome_writable_write` event carries `confirm_ms`, the time the read back
  took (D-122).
- The Espruino module is offered to EspruinoDocs as a tutorial page as well as a
  reference page (D-112).

### Changed

- **The module rebuilds its advertising packet when an encoded value has moved,
  not on every interval.** BTHome's own format asks for exactly this, the packet
  id being what tells a receiver the data is new. @enaon's PPK2 measured 235 µA
  falling to 50 on a sealed device (D-106, merged upstream as EspruinoDocs#765).
- Changing the advertising rate republishes the bytes already on air instead of
  building the same packet again: one connect-and-disconnect cycle on a
  nice!nano went from 189 ms of the single thread to 7 with a bindkey (D-108).
- The module wakes when an entry falls due instead of on a fixed timer, so a
  device whose entries are all slow wakes slowly. Gordon's proposal (D-109).
- `bw.changed()` folds a burst of calls into one rebuild 250 ms later. Twenty
  presses of a button cost 7.5 s of rebuilding before and 1.1 s after, and the
  application's own fade could not get a step in edgeways until it did (D-124).
- The module dropped four unused exports and one of two identical write paths,
  which bought the margin the fold above needed (D-123).

### Fixed

- **A value read from the wrong entry.** An Espruino device rebuilds its GATT
  table on every upload while the object ids it declares stay the same, and only
  a change to that list used to drop the cached table: a wrong value was
  dropped and the stale table kept, so on a value nobody wrote again it never
  healed. @enaon saw it 43 times. The read path now drops the table and reads
  again, and a declared entry missing from the table is a failure rather than a
  silent skip (D-116, D-118).
- A bindkey of 32 characters that are not all hexadecimal was accepted:
  `parseInt` stops at the first bad character, so one typo made the key
  silently a different key and every receiver reported a key that was not at
  fault. `setup()` now throws `bindkey_not_hex` (D-123).
- A write to an entry the plan does not have threw a `TypeError` inside the
  Bluetooth stack's own callback, where nothing catches it (D-114).
- A writable entry declared by name when its type is an event or a raw object is
  refused at `setup()`, instead of being probed into nonsense (D-114).
- A `get()` that throws no longer stops the device reading for ever: the read
  timer is re-armed, and `setup()` leaves a device working even when the radio
  refuses its packet (D-114).
- A refused write no longer sits in the characteristic where the entry's own
  value belongs, which on a sealed device meant a write-direction ciphertext
  where §4.3 promises a read-direction one (D-102).
- The write and advertising counter marks are masked to 32 bits (D-114).

## [0.1.0] - 2026-10-14

### Added

- First tagged release: the Home Assistant integration, installable through
  HACS, with the Espruino module and the protocol at `2.0-draft.7`. Switches,
  numbers, text and buttons from a BTHome device's own declaration, a bindkey
  prompt when the device is encrypted, and nothing to configure by hand.

[Unreleased]: https://github.com/yerpj/bthome-writable/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yerpj/bthome-writable/releases/tag/v0.1.0

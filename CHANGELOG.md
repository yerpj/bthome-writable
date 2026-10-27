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

The integration's `manifest.json` carries the version of the last tag cut, so it
reads 0.2.0 until something here touches `custom_components/` and bumps it.

### Added

- **A refused write is counted on the device, with or without a handler.**
  Espruino acknowledges a write before application code runs, so a device that
  refuses one cannot say so over the air: `onError` was the only place it
  showed, and `onError` is optional. A device deployed without one had no trace
  of a write it did not apply. `bw.rejects()` now returns a count per error
  code, so a stale layout, a bindkey that does not match and a replayed counter
  are told apart from each other rather than merely totalled. The protocol asks
  for it at §7 of `2.0-draft.9`, where two independent readings found the same
  gap (D-144, D-145). Measured on a board, not only under Node: six writes to
  one entry, all six acknowledged by the stack before application code ran, and
  the five that could not be applied counted under their own codes (D-146).
  What it cannot count is a write refused for its length:
  that one is refused by the stack below the module, which is also the only
  notice the central gets.

### Fixed

- **The module stated five advertising options and inherited the sixth.**
  Espruino holds the advertising flags in the stack rather than in the call, so
  an option nobody passes keeps whatever the last caller left there, and
  `scannable` is latched off for good by any use of the coded phy or of
  extended advertising. Connectable advertising with scannable off is a
  directed type, whose peer address the firmware leaves NULL, and on a
  SoftDevice 6 board the radio then refuses to be configured at all:
  `ERR 0x10 (INVALID ADDR)`, which is what @gfwilliams got from a Jolt.js
  running 2v29 on 2026-10-26 where the same code works on a Puck.js.
  `advOptions()` now names `scannable:true` with the rest, which changes
  nothing on a device that never turned it off and leaves nothing of ours to
  inherit (espruino#8024, D-143).
- **A refused fallback packet threw away the refusal that led to it.** When the
  radio refuses the real packet the module publishes a small one so the device
  can still be found, then reports `advertising_rejected`. If the small packet
  was refused too, its own raw error escaped alone: no packet size, no first
  reason, no sign that a fallback had been tried, and a stack frame pointing at
  `setup()`. That is the whole of what the Jolt.js report above had to go on.
  One error now names both refusals and their sizes, and the cached packet is
  cleared so the next rate change rebuilds instead of republishing bytes the
  radio never took (D-143).
- **A device whose advertising interval was set to 100 ms could never change
  rate again.** `setAdvertisingInterval()` republished only when the rate the
  radio was running differed from the *fast* interval, rather than from the
  interval being asked for. 100 ms is the fast interval's own default and a
  perfectly legal idle interval, so once the two were equal the test was false
  for good: every later call updated the module's idea of the interval and
  handed nothing to the radio. Found on the bench on 2026-10-26 by a swept
  power measurement that began at 100 ms and then advertised at 100 ms for
  seventeen minutes while walking through eight intervals, which the current
  trace showed step by step. The guard now compares against the interval being
  set, which is what it was for.

### Documentation

- **Two neutral audits, and it was the numbers that were wrong.** One read-only
  agent compared every document to the protocol, the vectors and the code; a
  second implemented the device side from the specification alone, without
  reading this repository. The prose held: no stale narrative outside its own
  banner, no invented API name, no broken link, one protocol version across the
  six files that state it. The figures did not. Corrected here: the ~45 uA
  quoted as @enaon's floor when it is his whole lamp script, still wrong in
  section 9 of `docs/measurements.md` after sections 8 and 23 were put right; a
  conclusion that the module "still calls `Date.now()`", which it has not since
  the deferred change landed; bundle sizes given as 40 kB and 18 kB in three
  documents against 60 to 74 kB and 21 to 26 kB today, which also halves the
  margin under the 32 768-byte paste limit; 716 automated tests against 882; a
  submission dossier still calling battery cost out of scope after D-142
  measured it; two documents disagreeing by a factor of two and a half on how
  long a device takes to go unavailable; a `README.md` sending a new reader
  first to a protocol version 1 report; a tutorial packet counted at 13 bytes
  that is 12. The published module page gains the second refusal code, the
  measured service data budgets beside the arithmetic one, the hexadecimal form
  of the entry UUIDs, the per-entry `signed` option and two exported helpers.
  The install guide gains the connection cap and the `bthome_writable_write`
  event, neither of which was documented anywhere but this file (D-144).

## [0.2.0] - 2026-10-24

Everything the integration learned since the first release, and it is mostly one
theme: **fewer connections**. A BLE device serves one central at a time and a
host has a handful of slots, so the work was to stop spending them. The module's
own changes rode along, since EspruinoDocs serves it by name and it carries no
version of its own.

### Added

- **The connection cap can be changed.** An options form on each device, one
  field, for a host with several adapters or proxies that can afford more
  simultaneous connections than the default two, or with a single adapter that
  can afford fewer. Nobody is prompted and the default still works, so there is
  still nothing to configure. A new value takes effect on the next command
  rather than at the next restart, and no connection is dropped to apply it
  (D-003, D-132).
- A write to an entry the device can also report is read back and checked. A
  device that applies a write slowly, a fade or a ramp, is logged rather than
  called broken, because §4.3's getter is published and not served on demand
  (D-117, D-120, D-122).
- The `bthome_writable_write` event carries `confirm_ms`, the time the read back
  took (D-122), and `counter_ms`, the time the counter question of §5.6 took
  when the command carried one (D-129).

### Changed

- The integration connects through the adapter or proxy Home Assistant chooses,
  as every other Bluetooth integration does. For two days it scored the
  connectable sources itself, after a write through a proxy that could not reach
  the device was lost without a word (D-117); measured against the stack's own
  scorer, the two named the same source with the same number on every write, and
  the stack's also knows what an integration cannot see: connect failures per
  source, connections in flight, whether a source has a free slot at all
  (D-127).
- **A read the settings revision called for rides a command's connection.** A
  device whose knob or button moved reports it by moving its revision (§3.2),
  and the read that answers used to be a connection of its own, taken moments
  after a command's. A read whose revision has since been read now returns
  without connecting at all. Measured on a device that does both: a local change
  reached Home Assistant within 20 s in eight of nine commands, against four of
  nine before (D-130). Reading *everything* on every command, which is what
  prompted the question, is not what this does and is explained in D-130.
- **The counter question of §5.6 rides the connection a command already makes.**
  It used to take one of its own: one connection at setup per configured sealed
  device, and one before any command whose device had moved its settings
  revision. A user measured the result as a first command taking 5 to 10 s after
  a restart of Home Assistant, which is two connections at a 1000 ms advertising
  interval and nothing else (D-129).
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

- **A host out of connection slots stood down for the next command only.** The
  hold-off of D-133 reached callers that had not asked yet and not the ones
  already queued, so on a host this integration had itself filled, the device
  that discovered the exhaustion released its slot straight into the next
  waiter, which spent its own nine attempts and about 36 seconds finding the
  same wall. Nobody is admitted now while the host is held off (D-135).
- **A command could wait behind this integration's own housekeeping.** Nothing
  told a user's command apart from a background state read, so on a host with
  several devices two reads could hold every connection slot while somebody
  waited for a switch to move: 2528 ms of it, measured. Commands now go first,
  and a read that waits is retried on the device's next advertisement (D-134).
- **A command that waited its turn said it had been slow to connect.** The
  moment a command was allowed to open a link was taken before it queued, not
  after, so waiting for a device's turn or for one of the host's connection
  slots was counted as time spent connecting. On the bench a command that waited
  nine seconds behind another device reported two milliseconds of queueing.
  `queued_ms` now covers everything before the link is opened and `connect_ms`
  only the link itself (D-133).
- **A host with no connection slot free was reported as an unreachable
  device.** It is neither the device's fault nor its problem: the adapter or the
  proxy had nothing to spare. A command now says so, and names what fixes it,
  while the rest of this integration's devices stand off for a moment instead of
  each spending `bleak_retry_connector`'s nine attempts discovering the same
  thing (D-133).
- **The connection cap stopped capping as soon as two devices disagreed about
  it.** It was one semaphore per distinct limit, so a device set to two
  connections and a device set to three opened five between them on a host that
  had been told three. There is now one gate for the whole host, and the most
  cautious value any device asks for is the one in force. Unreachable until now,
  since nothing could change the limit, and the reason exposing it came second
  (D-132).
- **Two of this integration's own connections could arrive at one device at
  once.** An Espruino serves one central at a time; the connection cap protects
  the host's adapters and proxies, not a device. So a command and the state read
  a moved settings revision calls for could each take a host slot and reach for
  the same device: one waited on a link the other held, retried, and arrived up
  to 34 s later or gave up and left the user's button press unreported. Every
  device now has its own turn. Measured on a board that does both: the worst
  command fell from 33.6 s to 6.6 s and every local change arrived, 9 of 9
  against 4 of 9 (D-131).
- A command no longer stays open while this integration finishes its own
  bookkeeping after the write: the caller is released when the device
  acknowledges it, which is what §4.2 makes the confirmation (D-130).
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

[Unreleased]: https://github.com/yerpj/bthome-writable/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/yerpj/bthome-writable/releases/tag/v0.2.0
[0.1.0]: https://github.com/yerpj/bthome-writable/releases/tag/v0.1.0

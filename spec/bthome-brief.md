# bthome-writable — one page for the BTHome maintainers

**A briefing, not a draft**: facts and links to speak from. The submission is
the owner's own words — the Open Home Foundation
[AI policy](https://developers.home-assistant.io/docs/ai_policy) closes
contributions believed to be agent-written (`decisions.md` D-091).

## The ask

**Reserve one object ID: `0xFF`.** Everything else reuses BTHome's own object
table, encodings and AES-CCM. And a question rather than a request: the
specification is BTHome's to take if the maintainers want it.

## What it does

A device lists, in its ordinary BTHome advertising, the object types it accepts
writes for — object `0xFF`, **last in the service data**, so existing receivers
skip it. A receiver connects briefly and writes **one BTHome object** to that
entry's own GATT characteristic. The write response is the acknowledgement; a
writable value is never advertised.

```
advertising   40 00 09 01 61 FF 01 1E     battery, and "entry 1 accepts 0x1E"
write         1E 01  ->  2FAA0001         one object, one characteristic
```

## It answers requests already made here

- **[bthome-ble #257](https://github.com/Bluetooth-Devices/bthome-ble/issues/257)**
  — *"BTHome should define an Object Id for supported events"*: a declaration
  object, asked for independently in 2025 for a narrower case.
- **[#146](https://github.com/Bluetooth-Devices/bthome-ble/issues/146)**
  two-way communication — Ernst79: *"we will welcome contributions from others
  if they want to add this somehow."*
  **[#287](https://github.com/Bluetooth-Devices/bthome-ble/issues/287)**
  controlling Shelly BLU devices.

Re-checked 2026-10-07: no downlink proposed anywhere, and `0xFF` unassigned —
`0xF2` is the highest ID in use.

## Evidence

Three independent sites. Gordon Williams on a Puck.js: *"works great"*,
connections brief, no missed writes. @enaon on an RPi4b with OpenWrt, six
ESPHome proxies and local BlueZ: working over both paths, and his report found
a fault the original bench could not produce.

| Measured through Home Assistant | |
|---|---|
| Click to action, 1 s advertising interval | **1.7 s**, of which 36 ms is the write |
| Repeated commands | **0.31 s** |
| Delivered, two devices | **100 %**, no retries |
| Declaration on the air, three writable lights | **5 bytes** |

Two reference implementations, a shared test-vector contract with AES-CCM
vectors that pass on-device, 683 automated tests across three suites.

## Objections, and the short answers

- **Slow, and costly in battery.** 1.7 s click to action. The idle advertising
  interval is the device application's choice and is unchanged by this.
- **Unknown objects break existing receivers.** `bthome-ble` skips an unknown ID
  and stops parsing, so the declaration goes last and existing installs lose
  nothing. Verified against the real parser in CI.
- **Writes are a security hole.** BTHome's own AES-CCM both directions, the
  direction bound into the nonce so no recording replays as another, and a
  monotonic write counter. Without the key there is no write.

## Links

<https://github.com/yerpj/bthome-writable> — specification `spec/PROTOCOL.md`,
every resolved question with the measurement that resolved it
`spec/decisions.md`, ten-minute replication `docs/try-it.md`. Design converged
with Gordon Williams in
[espruino#8024](https://github.com/orgs/espruino/discussions/8024).

**Status update — bthome-writable**

Phases 0–3 of the plan are done and verified on hardware; phase 4 is release work.

- **Protocol** — unchanged since we converged it. The declaration is object `0xFF`, one positional bitmask byte, MUST be last in the service data. A write carries every writable object in packet order to a single GATT characteristic, and the refreshed advertising is the confirmation. No ack channel.
- **Espruino module** — wraps the existing `BTHome` module rather than forking it. Sensors, controls and write-only objects (`set` with no `get`) all come from one `advertise:` list.
- **Home Assistant integration** — zero-config discovery; entities merge onto the device card the core BTHome integration already made. Switch, number, text and button platforms.
- **Encryption** — BTHome's own AES-CCM, both directions, no JavaScript AES needed. The shared crypto test vectors pass **on-device** on a Puck.js and on a nice!nano.
- **Measured on hardware** — positional addressing and whole-write rejection both proven; 1.7 s click-to-confirmed at best, 3.3 s on today's bench, on one Raspberry Pi with no ESPHome proxy.

Two points I'd value your view on, both written up in `spec/for-gordon.md`:

1. **Write-only has no representation for fixed-length objects.** A light that is off advertises `1E 00`, byte-identical to an "empty value" placeholder. Proposed wording: write-only means a *variable-length* object advertising length 0, or an *event-class* object advertising its "none" value.
2. **`0x3B command` has no no-op** — its `0x00` is `off`, a real command. Since a write carries every writable object, a device declaring it writable alongside anything else cannot have that other thing written without also being switched off.

Unrelated to BTHome, but found on the way and it appears unreported: **master builds emit service data without the 16-bit UUID.** On `2v29.242`, `NRF.getAdvertisingData({0x180F:[1,2,3]},{showName:false})` returns `02 01 06 04 16 01 02 03` instead of `02 01 06 06 16 0f 18 01 02 03` — a standard UUID, nothing to do with this project. Release builds are fine. Measurements and a working raw-form workaround in `decisions.md` D-046.

# bthome-writable

A minimal, BTHome-compatible **downlink** for BLE devices in Home Assistant.

Devices declare in their BTHome advertising which of their objects are *writable*.
Home Assistant connects briefly, writes new values — in BTHome's own format and with
BTHome's own encryption — to a single GATT characteristic, then disconnects. The
refreshed advertising is the confirmation; there is no ack protocol.

| Directory       | Contents                                                        |
|-----------------|-----------------------------------------------------------------|
| `spec/`         | `PROTOCOL.md` (normative), `decisions.md`, advertising fixtures  |
| `espruino/`     | Espruino JS module (nRF52-class devices) + pure-JS unit tests    |
| `ha/`           | Home Assistant custom integration (`bthome_writable`, HACS)      |
| `test-vectors/` | Crypto test vectors — the shared contract between both codebases |
| `tools/`        | Generators and verification scripts                              |

Status: **draft / pre-release.** The protocol is being converged publicly with
Gordon Williams (Espruino) in
[espruino#8013](https://github.com/orgs/espruino/discussions/8013). Nothing here is
frozen yet; UUIDs and wire formats freeze at the first public release.

See `SPEC-WORKING-DOCUMENT.md` for the design rationale and task breakdown, and
`spec/PROTOCOL.md` for the protocol itself.

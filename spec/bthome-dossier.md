# Dossier for the BTHome maintainers (T4.4)

Working material for the submission to BTHome, collected ahead of time. **Not
the submission itself**: the timing and the ask belong to the owner and Gordon
(`SPEC-WORKING-DOCUMENT.md` §7, T4.4). Everything here is sourced; dates are
when the item was checked.

---

## 1. Prior art: has anyone proposed a downlink? (checked 2026-09-17)

Searched `Bluetooth-Devices/bthome-ble` and `home-assistant/bthome.io` (the
specification repository) for issues and PRs mentioning write, writable,
downlink, actuator, command, two-way, bidirectional, control, GATT, switch; plus
GitHub-wide searches for BTHome combined with writable, downlink, two-way,
actuator.

**No downlink mechanism has been proposed.** There are requests, and there are
adjacent building blocks already accepted.

### Requests, still open

- **[bthome-ble #146](https://github.com/Bluetooth-Devices/bthome-ble/issues/146)**
  — *Add 2-way communication for acknowledgement and control?* (EternityForest,
  2024-09-04). Asks for a way to control relays and acknowledge remote presses.
  - **Ernst79 (maintainer):** BTHome is passive and one-way; two-way needs a
    connection, a different technique; *"we will welcome contributions from
    others if they want to add this somehow."*
  - **thecode (Home Assistant core):** suggests ESPHome; objects that a
    connection is *"a longer process and battery consuming"* and that
    connect-and-reply *"may take too long for a decent user experience."*
  - **pvvx:** points at PAwR (BLE 5.4); notes Linux does not support it.
- **[bthome-ble #287](https://github.com/Bluetooth-Devices/bthome-ble/issues/287)**
  — *Shelly BLU Distance: add control over range and interval* (2025-10-27). A
  user wants to change a device's settings from Home Assistant. Ernst79: *"That
  is not supported by BTHome at the moment. BTHome only listens to messages. I'll
  leave the issue open, if someone is willing to implement this."*

### Adjacent pieces already in BTHome

- **[bthome.io #73](https://github.com/home-assistant/bthome.io/pull/73)** —
  **settings revision `0x65`**, merged 2026-04. A monotonic uint8 telling
  receivers the device's configuration changed, so they *"should re-read the
  relevant data out-of-band (e.g. via a GATT connection)."* **The specification
  already accepts a GATT channel alongside advertising.** Strongest single
  precedent for this project.
- **[bthome.io #74](https://github.com/home-assistant/bthome.io/pull/74) /
  [#75](https://github.com/home-assistant/bthome.io/pull/75)** — **command
  `0x3B`**, merged 2026-04. Variable length: length byte (low 5 bits), opcode
  (`00` off, `01` on, `02` toggle, `03` step up, `04` step down), arguments.
  Filed under **events**, i.e. uplink — a remote emitting a command, not a device
  receiving one. First placed at `0xE0`, moved next to button and dimmer at
  Ernst79's request. Its `toggle` and `step` are relative, which is exactly what a
  retried write cannot tolerate.
- **[bthome.io #72](https://github.com/home-assistant/bthome.io/issues/72)** —
  *Add a generic quantity percentage type* (open, 2026-03). A typeless 0–100 %
  "level of something". A writable one would be the natural way to express a
  generic setpoint, and it costs this project nothing either way — the entry
  would simply name that ID.
- **[bthome-ble #25](https://github.com/Bluetooth-Devices/bthome-ble/issues/25)**
  — *Characteristic to offer configuration* (open since 2022, originally raised
  by balloob). A read-only GATT characteristic for static device data. Shows the
  "BTHome plus a GATT connection" pattern has been considered by the project's
  founders, not only by us.
- **Channel `0x60`** — checked: a plain uint8 value, not an addressing
  mechanism. Does not compete with entry numbering.
- Home Assistant core already writes to BLE sensors over GATT in other
  integrations (e.g. setting the clock on ThermoPro devices,
  home-assistant/core #135740), so connect-write-disconnect is not foreign to
  HA either.

### People

- **Ernst79** — maintainer of both repositories. Has said contributions are
  welcome; decides object ID assignment.
- **benmaximov** — author of both `0x65` and `0x3B` in April 2026. Evidently
  working on configurable BTHome devices; a natural reviewer or ally.
- **thecode** — raised the latency and battery objection; the person the
  measurements in §3 answer.
- **pvvx** — author of widely used custom sensor firmware; well placed to judge
  what small SoCs can afford.

---

## 2. The ask: one object ID (settled 2026-09-17, D-048)

**BTHome is asked for a single object ID: `0xFF`, the declaration.** Everything
else in this extension reuses BTHome's own object table, encodings and
encryption. No new data format, no new parsing concept, no second ID.

```
0xFF <objectID_1> <objectID_2> ... <objectID_n>
```

Last in the service data, it lists the BTHome object types the device accepts
writes for. Entry *k* is served on its own GATT characteristic; a write carries
one object, `ID + value`, in BTHome's own encoding. Writable values are not
advertised, so a device that only receives commands publishes nothing extra. A
device whose values can change by themselves advertises the **settings revision
`0x65`** — BTHome's own, already merged — and serves readable characteristics,
which is exactly the out-of-band re-read `0x65` was specified for.

The full specification is `PROTOCOL.md`; the reasoning is D-048.

### The actuator-objects proposal, and why it was dropped

An earlier draft (sent to Gordon on 2026-09-17) asked BTHome for four new
*actuator* objects — Switch, Level, Action, Text — on the grounds that BTHome
has no notion of an actuator, so making sensor objects writable mixes
measurement and command: a writable LED appeared in Home Assistant both as a
`binary_sensor` and as a `switch`.

Gordon's answer removed the problem instead of solving it. Since a written value
is no longer advertised, nothing writable is parsed as a sensor, and the
duplicate entity disappears without new objects. What the four objects were for:

| It was meant to fix | How version 2 fixes it |
|---|---|
| Sensor/actuator confusion | Writable values are not advertised at all; a control is never also a sensor |
| Per-instance addressing | One characteristic per entry |
| No no-op for `0x3B command` | A write touches one entry, so no object is ever sent a filler value |
| The 8-object limit and the packet-id shift of the v1 bitmask | The declaration lists object IDs, not positions |
| Confirming a write | The GATT write response, plus `0x65` and a read where the device can change by itself |

That leaves four fewer IDs to ask for, and no new concept for the maintainers to
review. Still deliberately out of scope: pairing a level with its light
(`PLATFORMS.md`), and setpoints with a unit.

---

## 3. Objections to expect, and the evidence

| Objection | Answer | Source |
|---|---|---|
| A connection is too slow for a good experience (#146) | 1.7 s click to action at best, of which 16 ms is the write itself; measured again on version 2 through an ESP32 proxy | `decisions.md` D-013, D-024, D-049; `docs/figures/latency.png` |
| It costs battery: the device must advertise fast | **Not answered.** This project has measured no power at all (D-055). What is measured is latency, which is a different question: the idle interval does not set command latency, because the device advertises fast only during and after a connection. But §7 asks for connectable advertising at all times and the module advertises at 100 ms for 30 s after every disconnect, and nothing here says what that costs a coin cell. **The experiment to run before submitting** | D-014, D-024, D-055 |
| Unknown objects break existing receivers | bthome-ble skips an unknown ID and stops parsing; placing new objects last loses nothing for existing installs. Tested in CI | D-005 |
| Writes are a security hole | BTHome's own AES-CCM, all three directions (advertising, write, read), the direction bound into the nonce so no recording replays as another; vectors pass on-device on two boards; HA warns once per unencrypted device, and refuses to downgrade a keyed device to plaintext | D-033, D-041, D-042, D-045 |
| It only works on one bench | Two boards (Puck.js, nice!nano), one HA install, one adapter and one ESP32 proxy. **Weak point** — needs testers outside this bench before submission | `docs/try-it.md` |
| Advertising space is too tight | The declaration costs one byte per writable entry and nothing else — writable values are not advertised. Measured budgets are below §2.4's arithmetic (Espruino manufacturer data and the local name), and a three-light declaration is 4 bytes | D-030, D-046, D-049 |

Claims to avoid, because they were wrong once in public:

- "A host with one adapter cannot scan while connected" — true of Windows/WinRT
  only (D-047).
- Anything about firmware behaviour without the exact build: `2v29.242` had an
  advertising bug that `2v29.396` does not (D-046).

---

## 4. Before submitting

- ~~Gordon's answer on the actuator proposal~~ — answered; version 2 is the
  result (D-048), implemented and verified on hardware (D-049).
- ~~A test through an ESPHome Bluetooth proxy~~ — done 2026-09-17 through
  `esp32-bluetooth-proxy-1f1020`.
- At least one tester outside this bench (`docs/walkthrough.md`,
  `docs/try-it.md`). **The remaining gap.**
- ~~An encrypted device on version 2, on hardware~~ — done 2026-09-21. A
  Puck.js running `encrypted-light.js`: Home Assistant raised the bindkey step
  by itself, read the declaration out of the decrypted advertising, and a sealed
  write drove the LED — 114 → 601 → 111 lux, read back out of a sealed packet
  (D-063, D-064). It also found a release blocker there, and fixed it.
- Re-run the prior-art search; update §1 with anything new.

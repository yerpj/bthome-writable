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
  "level of something". Same shape as the proposed Level actuator; worth aligning
  the encoding.
- **[bthome-ble #25](https://github.com/Bluetooth-Devices/bthome-ble/issues/25)**
  — *Characteristic to offer configuration* (open since 2022, originally raised
  by balloob). A read-only GATT characteristic for static device data. Shows the
  "BTHome plus a GATT connection" pattern has been considered by the project's
  founders, not only by us.
- **Channel `0x60`** — checked: a plain uint8 value, not an addressing
  mechanism. Does not compete with positional addressing.
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

## 2. Proposal under discussion: actuator objects (status: sent to Gordon 2026-09-17)

Prompted by Gordon's question whether events should be writable at all. The
underlying issue: BTHome has no notion of an actuator, so the current design
makes *sensor* objects writable, mixing measurement and command — a writable
LED shows up in Home Assistant both as a `binary_sensor` and as a `switch`, and a
thermostat setpoint would pass for a measured temperature.

Four objects, IDs to be assigned by BTHome (`0x66`–`0xFE` were free in
bthome-ble 3.22.1; the values below are placeholders):

| Object     | ID (provisional) | Size | Format                     | Advertised   | No-op in a write | HA entity |
|------------|------------------|------|----------------------------|--------------|------------------|-----------|
| **Switch** | `0xF0`           | 1    | uint8: 0 off, 1 on         | actual state | current value    | switch    |
| **Level**  | `0xF1`           | 2    | uint16 LE, 0.01 %, 0–10000 | actual level | current value    | number    |
| **Action** | `0xF2`           | 1    | uint8: 0 idle, 1 trigger   | always 0     | 0                | button    |
| **Text**   | `0xF3`           | 1+n  | length + UTF-8             | length 0     | length 0         | text      |

Rules:

1. Only actuator objects are writable; sensors and events never are.
2. Actuator objects come after all other objects, so a parser that does not know
   them stops without losing anything.
3. The advertised value is the device's actual state, which is what confirms a
   write.
4. Values are absolute — no toggle, no increment — so a retried write is
   harmless.
5. A write carries every actuator object in packet order; unchanged ones resend
   their current value, Action sends 0, Text sends length 0.
6. An unknown ID, a wrong order or an out-of-range value rejects the whole write.

Consequences: the `0xFF` declaration becomes unnecessary (the ID says what is
writable), taking with it the 8-object limit, the packet-id shift and the
`0x3B` no-op problem. For BTHome: four table entries and no new parsing concept.
GATT, encryption and the confirmation model are unchanged. Deliberately left
out: setpoints with a unit (e.g. target temperature), which would fit better as
a wrapper around an existing sensor object — a new parsing concept, so a later
extension.

---

## 3. Objections to expect, and the evidence

| Objection | Answer | Source |
|---|---|---|
| A connection is too slow for a good experience (#146) | 1.7 s click-to-confirmed at best, 3.3 s on the current bench, one Raspberry Pi, no proxy | `decisions.md` D-013, D-024; `docs/figures/latency.png` |
| It costs battery: the device must advertise fast | The idle advertising interval does not set command latency: 1.7 s measured at a 5 s interval, because the device advertises fast only during and after a connection | D-014, D-024 |
| Unknown objects break existing receivers | bthome-ble skips an unknown ID and stops parsing; placing new objects last loses nothing for existing installs. Tested in CI | D-005 |
| Writes are a security hole | BTHome's own AES-CCM, both directions, direction bound into the nonce so an advertisement cannot be replayed as a write; vectors pass on-device on two boards; HA warns once per unencrypted actuator | D-033, D-041, D-045 |
| It only works on one bench | Two boards (Puck.js, nice!nano), one HA install, one adapter. **Weak point** — needs outside testers and an ESPHome-proxy test before submission | `docs/try-it.md` |
| Advertising space is too tight | Measured budgets are below §2.3's arithmetic (Espruino manufacturer data and the local name); a few actuator objects still fit | D-030, D-046 |

Claims to avoid, because they were wrong once in public:

- "A host with one adapter cannot scan while connected" — true of Windows/WinRT
  only (D-047).
- Anything about firmware behaviour without the exact build: `2v29.242` had an
  advertising bug that `2v29.396` does not (D-046).

---

## 4. Before submitting

- Gordon's answer on the actuator proposal (§2), and the protocol updated
  accordingly.
- A test through an ESPHome Bluetooth proxy — the setup most HA users have, and
  an unmet T1.2 acceptance criterion.
- At least one tester outside this bench (`docs/walkthrough.md`,
  `docs/try-it.md`).
- Check #72 again: if a generic percentage lands, reuse its encoding for Level.
- Re-run the prior-art search; update §1 with anything new.

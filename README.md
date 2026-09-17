# bthome-writable

A minimal, BTHome-compatible **downlink** for BLE devices in Home Assistant.

Devices list in their BTHome advertising which BTHome object types they accept
writes for. Home Assistant connects briefly, writes one value — in BTHome's own
format and with BTHome's own encryption — to that entry's own GATT
characteristic, and disconnects. A device whose values can change by themselves
makes those characteristics readable and bumps BTHome's settings revision
(`0x65`) when they do, so a receiver knows to read them again.

| Directory       | Contents                                                        |
|-----------------|-----------------------------------------------------------------|
| `spec/`         | `PROTOCOL.md` (normative), `decisions.md`, advertising fixtures  |
| `espruino/`     | Espruino JS module (nRF52-class devices) + pure-JS unit tests    |
| `custom_components/` | The Home Assistant integration itself — at the root so HACS can install straight from GitHub |
| `ha/`           | Its test suite, harness and hardware-test procedure              |
| `test-vectors/` | Crypto test vectors — the shared contract between both codebases |
| `tools/`        | Generators and verification scripts                              |

Status: **draft / pre-release**, protocol version 2.0-draft.1. The protocol is
converged publicly with Gordon Williams (Espruino) in
[espruino#8013](https://github.com/orgs/espruino/discussions/8013). Nothing here is
frozen yet; UUIDs and wire formats freeze at the first public release.

Version 2 replaces version 1's positional bitmask, its write-all payload and its
advertising-based confirmation with a list of writable object types, one
characteristic per entry, and reads gated on the settings revision
([`decisions.md` D-048](spec/decisions.md)). Both implementations, all three test
suites and the bench tools are on version 2, verified on a Puck.js and a
nice!nano through Home Assistant and an ESP32 proxy (D-049). What remains is
release work: documentation, HACS and EspruinoDocs publication, and the
standardisation dossier for the BTHome maintainers.

## Start here

- **[`docs/espruino-quickstart.md`](docs/espruino-quickstart.md)** — make your
  own device writable, from a self-contained file you paste into the Web IDE.
- **[`docs/home-assistant-install.md`](docs/home-assistant-install.md)** —
  install through HACS, add the device, and what to do when a control misbehaves.

## Reading order

- [`docs/first-use-case.md`](docs/first-use-case.md) — the first working
  end-to-end demonstration, with diagrams, timings and what broke. Start here
  for what this actually does. Also as a
  [PDF](docs/first-use-case.pdf), regenerated with
  `python -m tools.md_to_pdf docs/first-use-case.md`.
- [`docs/measurements.md`](docs/measurements.md) — every number this project
  has measured, with the command that produces it again: response time against
  advertising interval, write and rejection timings, advertising budgets per
  board, text limits, the cost of encryption on the device.
- `spec/PROTOCOL.md` — the protocol. Normative.
- `spec/decisions.md` — every resolved question, with the measurement or the
  ruling that resolved it.
- `spec/bthome-dossier.md` — material for the eventual submission to the
  BTHome maintainers: prior art, the actuator proposal, objections and evidence.
- `SPEC-WORKING-DOCUMENT.md` — the original design rationale and task
  breakdown. Superseded by `spec/PROTOCOL.md` wherever the two differ.

## Running the tests

Three suites. The two Python ones need **separate virtualenvs**: the newest
`bthome-ble` requires a `habluetooth` and `cryptography` that the Home Assistant
release the test harness pins holds back.

```sh
# Spec tooling: test vectors, advertising fixtures, the bthome-ble checks
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q

# Home Assistant integration
python -m venv .venv-ha
.venv-ha/bin/pip install -r ha/requirements-test.txt bthome-ble bleak-retry-connector
cd ha && ../.venv-ha/bin/pytest -q

# Espruino module
cd espruino && npm install && npm test && npm run lint
```

`test-vectors/test-vectors.json` and `spec/advertising-fixtures.json` are
generated, and both are consumed by the Python and the JavaScript suites — they
are the contract between the two implementations. Regenerate with
`python -m tools.gen_test_vectors` and `python -m tools.gen_advertising_fixtures`;
a change to either is a change to the specification.

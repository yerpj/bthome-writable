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

Phase 0 (spec, test vectors, fixtures) and the software half of Phase 1 (both
MVPs) are done and green. Both MVPs are now waiting on hardware: see
`espruino/HARDWARE-TEST.md` and `ha/HARDWARE-TEST.md`.

## Reading order

- [`docs/first-use-case.md`](docs/first-use-case.md) — the first working
  end-to-end demonstration, with diagrams, timings and what broke. Start here
  for what this actually does. Also as a
  [PDF](docs/first-use-case.pdf), regenerated with
  `python -m tools.md_to_pdf docs/first-use-case.md`.
- `spec/PROTOCOL.md` — the protocol. Normative.
- `spec/decisions.md` — every resolved question, with the measurement or the
  ruling that resolved it.
- `spec/for-gordon.md` — what still needs Gordon in espruino#8013.
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

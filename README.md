# BTHome Writable

**Write to BTHome devices from Home Assistant.** A device declares, in its
ordinary BTHome advertising, which BTHome object types it accepts writes for.
Home Assistant connects briefly, writes one value — in BTHome's own format and
with BTHome's own encryption — to that entry's own GATT characteristic, and
disconnects. The write response is the acknowledgement: a writable value is
never advertised back.

[![HACS: custom repository](https://img.shields.io/badge/HACS-custom%20repository-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![CI](https://github.com/yerpj/bthome-writable/actions/workflows/ci.yml/badge.svg)](https://github.com/yerpj/bthome-writable/actions/workflows/ci.yml)

![A BTHome device with writable controls in Home Assistant](https://raw.githubusercontent.com/yerpj/bthome-writable/main/docs/screenshots/device-page.png)

## What you get in Home Assistant

Entities, discovered on their own. There is nothing to configure beyond the
bindkey prompt an encrypted BTHome device already asks for:

| What the device declares | What appears in Home Assistant |
|---|---|
| a binary object — 28 of them | a `switch` |
| a numeric object — 59 | a `number`, with that object's own unit, range and step |
| the string object `0x53` | a `text` |
| an event object — `0x3A`, `0x3C` | one `button` per value |

**The device decides what is writable, not a table in this repository.** The
classification is read from `bthome-ble` at runtime, so an object BTHome assigns
next year needs no change here. The counts are against `bthome-ble` 3.22.1.

A device whose values can also change by themselves makes those characteristics
readable and bumps BTHome's settings revision (`0x65`) when they do, so Home
Assistant knows to read them again.

## What you need

- **Home Assistant 2026.7 or newer**, with Bluetooth working: an adapter on the
  host, or an ESPHome Bluetooth proxy in range of the device. If the core BTHome
  integration already shows your device's sensors, Bluetooth is working.
- **A device that advertises a writable declaration.** If you have none yet,
  [`docs/espruino-quickstart.md`](docs/espruino-quickstart.md) turns a Puck.js
  into one from a single file you paste into a web page.

## Install

Through HACS, as a custom repository:

1. **HACS → ⋮ → Custom repositories**
2. Repository `https://github.com/yerpj/bthome-writable`, type **Integration**, Add
3. Find **BTHome Writable** in the list, **Download**
4. **Restart Home Assistant** — a custom integration is not loaded until you do

Your device should then be discovered without being asked for.
[`docs/home-assistant-install.md`](docs/home-assistant-install.md) is the longer
version: installing without HACS, and what to do when a control misbehaves.

> **Status: draft / pre-release** — protocol 2.0-draft.11. It works, and every
> claim here is measured on three benches, two of them not mine. But the wire
> format is not frozen: the GATT UUIDs freeze at the first public release, and
> the declaration's object id `0xFF` is
> [proposed to BTHome](https://github.com/home-assistant/bthome.io/pull/82),
> not yet assigned.

## How it works, and why

![What it needs, and what then happens on the air](https://raw.githubusercontent.com/yerpj/bthome-writable/main/docs/figures/try-it.png)

- [`docs/try-it.md`](docs/try-it.md) — **start here for what this actually
  does**: ten minutes, one board, one Home Assistant, and the exchange on the
  air at the end of it.
- [`docs/first-use-case.md`](docs/first-use-case.md) — the first working
  end-to-end demonstration, with diagrams, timings and what broke. It describes
  **protocol version 1**, and it is what produced the move to version 2, so read
  it as history; also as a [PDF](docs/first-use-case.pdf).
- [`docs/measurements.md`](docs/measurements.md) — every number this project has
  measured, with the command that produces it again: response time against
  advertising interval, write and rejection timings, advertising budgets per
  board, text limits, the cost of encryption on the device.
- [`docs/chain-test.md`](docs/chain-test.md) — the scenario that qualifies the
  whole chain with Home Assistant in it: eight checks from an advertisement
  reaching an entity to a burst of commands reaching the device, and what each
  one would catch. Its narrower companion is
  [`docs/regression.md`](docs/regression.md), the latency and delivery guard.
- [`spec/PROTOCOL.md`](spec/PROTOCOL.md) — the protocol. Normative.
- [`spec/decisions.md`](spec/decisions.md) — every resolved question, with the
  measurement or the ruling that resolved it.
- [`CHANGELOG.md`](CHANGELOG.md) and
  [`spec/CHANGELOG.md`](spec/CHANGELOG.md) — what changed in the two
  implementations, and what changed in the protocol, by draft number.
- [`spec/PLATFORMS.md`](spec/PLATFORMS.md) — how a BTHome object becomes a Home
  Assistant entity, and which ones are deliberately not exposed.

## Devices

Any device implementing [`spec/PROTOCOL.md`](spec/PROTOCOL.md) works. One
implementation ships today: the
**[BTHomeWritable module](https://github.com/espruino/EspruinoDocs/blob/master/modules/BTHomeWritable.md)**
in Espruino's own module library, for nRF52-class boards — Puck.js, nice!nano
and the like. It is developed in `espruino/` here, with its own unit tests, and
published from there.

## Acknowledgements

The protocol was designed in the open with **Gordon Williams**
([@gfwilliams](https://github.com/gfwilliams)), who created Espruino, in
[espruino#8024](https://github.com/orgs/espruino/discussions/8024) — this
project's topic — and before that in
[espruino#8013](https://github.com/orgs/espruino/discussions/8013), kept for
history. **[@enaon](https://github.com/enaon)** ran it on hardware that mine did
not resemble and found defects no bench here would have reached, including one
in the encryption path.

---

## For contributors

| Directory | Contents |
|---|---|
| `spec/` | `PROTOCOL.md` (normative), `PLATFORMS.md`, `decisions.md`, `CHANGELOG.md`, advertising fixtures |
| `custom_components/` | the Home Assistant integration itself — at the root so HACS installs straight from GitHub |
| `ha/` | its test suite, harness and hardware-test procedure |
| `espruino/` | the Espruino JS module + pure-JS unit tests |
| `test-vectors/` | crypto test vectors — the shared contract between both codebases |
| `tools/` | generators and verification scripts |
| `docs/` | everything above, plus the figures and the bench notes |

Two more files worth knowing about:
[`docs/data/github-watch.json`](docs/data/github-watch.json) is the state of
what this project has proposed in other people's repositories, refreshed by
`python -m tools.watch_github` and committed so that its git history is the
history of how the submission was received; and
[`spec/bthome-brief.md`](spec/bthome-brief.md) is the two pages the
standardisation case is made from, with
[`spec/bthome-dossier.md`](spec/bthome-dossier.md) behind it.

### Protocol version 2

Version 2 replaces version 1's positional bitmask, its write-all payload and its
advertising-based confirmation with a list of writable object types, one
characteristic per entry, and reads gated on the settings revision
([`decisions.md`](spec/decisions.md), D-048). Both implementations, all three
test suites and the bench tools are on version 2, verified on a Puck.js and a
nice!nano through Home Assistant and an ESP32 proxy (D-049).
`SPEC-WORKING-DOCUMENT.md` is the original design rationale and is superseded by
`spec/PROTOCOL.md` wherever the two differ.

### Running the tests

Three suites. The two Python ones need **separate virtualenvs**: the newest
`bthome-ble` requires a `habluetooth` and `cryptography` that the Home Assistant
release the test harness pins holds back.

```sh
# Spec tooling: test vectors, advertising fixtures, the bthome-ble checks
python -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt     # Scripts/ on Windows
.venv/bin/python -m pytest -q

# Home Assistant integration
python -m venv .venv-ha
.venv-ha/bin/python -m pip install -r ha/requirements-test.txt
cd ha && ../.venv-ha/bin/python -m pytest -q

# Espruino module
cd espruino && npm install && npm test && npm run lint
```

Two notes on those commands, both learned the hard way. On Windows the
interpreter is `.venv/Scripts/python.exe`, not `.venv/bin/python`. And install
**only** `ha/requirements-test.txt`: it already pins `bthome-ble` and
`bleak-retry-connector` at versions that match the Home Assistant release it
brings, and naming either package again on that line resolves it to the newest
release — which is the very clash the paragraph above warns about. CI installs
the file alone (`.github/workflows/ci.yml`).

`test-vectors/test-vectors.json` and `spec/advertising-fixtures.json` are
generated, and both are consumed by the Python and the JavaScript suites — they
are the contract between the two implementations. Regenerate with
`python -m tools.gen_test_vectors` and `python -m tools.gen_advertising_fixtures`;
a change to either is a change to the specification.

# CLAUDE.md — bthome-writable

## What this project is

A minimal, BTHome-compatible **downlink** for BLE devices in Home Assistant: devices declare in their BTHome advertising which objects are *writable*; HA connects briefly, writes new values in BTHome's own format to a single GATT characteristic, disconnects; the refreshed advertising is the confirmation. Two implementations: an **Espruino JS module** (nRF52-class devices) and a **HA custom integration** (HACS). Goal: get the mechanism adopted by the BTHome project once proven (ID reservation, ideally a merge).

## Source of truth

**`SPEC-WORKING-DOCUMENT.md` in this repo. Read it entirely before writing any code.** It contains the protocol draft (§3), both implementation designs (§4–5), the risk list (§6 — read before coding, several risks gate design choices), the task breakdown with acceptance criteria (§7), and open decisions (§8).

The design was converged publicly with **Gordon Williams (@gfwilliams)**, creator and maintainer of Espruino, in this discussion (you may fetch it for context, but the working document supersedes the thread — earlier iterations there, e.g. a 4-characteristic "EHAC" GATT profile or an objectID-list declaration, are **abandoned**; do not resurrect them):
https://github.com/orgs/espruino/discussions/8013

The project owner (JP, @yerpj on GitHub) drives the discussion with Gordon; you drive the code.

## Rules of engagement

1. **Respect the markers.** `[DECISION]` items are not yours to decide — implement behind a clearly named constant/flag and ask the owner. `[HW]` tasks need physical hardware: prepare everything (code, test procedure, expected results), then hand back to the owner. `[VERIFY]` items are cheap checks that gate design choices — do them at the scheduled point, record the result in `/spec/decisions.md`.
2. **Do not modify the protocol** (§3) on your own initiative. If implementation reveals a genuine spec problem, stop, write up the issue (what breaks, options, recommendation) and hand it to the owner — the spec is co-designed with Gordon and changes must go through him.
3. **Wrap, don't fork.** Espruino side: build on the existing `BTHome` module (https://www.espruino.com/BTHome), reuse its encoding tables, keep advertising ownership in one place. HA side: depend on the `bthome-ble` library for all BTHome parsing — never reimplement it.
4. **Zero-config is non-negotiable.** Any step that would require the user to write configuration by hand (beyond a bindkey prompt) is a design bug. This is the lesson of the failed "Generic Bluetooth Integration" prior art.
5. **Stay upstreamable.** Code as if the HA logic will be proposed into the core `bthome` integration later: HA core style, typing, tests via `pytest-homeassistant-custom-component`, no exotic dependencies.
6. **Test vectors are the contract.** `/test-vectors/test-vectors.json` (produced in T0.3) must be consumed by BOTH test suites; a change to it is a spec change (rule 2 applies).

## Repo layout (create in T0.1)

```
/spec           PROTOCOL.md, decisions.md, advertising fixtures
/espruino       the JS module + pure-JS unit tests (parse/encode separated from NRF calls)
/ha             the custom integration (custom_components/bthome_writable/)
/test-vectors   crypto test vectors (shared contract)
```

## Execution order

Follow §7 of the working document: T0.1 → T0.2 (pause for owner decisions) → T0.5 (early verify: `bthome-ble` tolerance of the 0xFF declaration — it gates the container choice) → T0.3 + T0.4 → T1.1 + T1.2 → hand back for hardware testing → continue per phases.

Start every session by re-reading `SPEC-WORKING-DOCUMENT.md` §3 and §6, and `/spec/decisions.md` if it exists.

# CLAUDE.md — bthome-writable

## What this project is

A minimal, BTHome-compatible **downlink** for BLE devices in Home Assistant: devices declare in their BTHome advertising which objects are *writable*; HA connects briefly, writes one value in BTHome's own object format to that entry's own GATT characteristic, disconnects; the write response is the confirmation — a writable value is never advertised. Two implementations: an **Espruino JS module** (nRF52-class devices) and a **HA custom integration** (HACS). Goal: get the mechanism adopted by the BTHome project once proven (ID reservation, ideally a merge).

## Source of truth

**`spec/PROTOCOL.md` is the protocol, and it is normative.** Read it entirely before writing any code. `spec/decisions.md` is the decision log — read the end of it; `spec/PLATFORMS.md` maps BTHome objects to Home Assistant entities.

`SPEC-WORKING-DOCUMENT.md` is the original working document and is **superseded in part**: its §3 and §7 describe protocol version 1 — a positional bitmask, a write-all payload, confirmation by refreshed advertising — all replaced in version 2 (D-048, D-059, D-073). Take from it §1 (purpose), items 1–2 of §2 (core model), §6 (the risk list, still current and still gating design choices) and the phase structure of §7. Its own banner says which parts to distrust. Nothing in it is normative.

The design was converged publicly with **Gordon Williams (@gfwilliams)**, creator and maintainer of Espruino. There are now **two** discussions to follow, and they are not interchangeable:

- **espruino#8024** — <https://github.com/orgs/espruino/discussions/8024> — this project's own topic, opened 2026-09-29. Everything about bthome-writable belongs here.
- **espruino#8013** — <https://github.com/orgs/espruino/discussions/8013> — where the design was converged, and the home of Gordon's Home Assistant integration (`espruino/homeassistant-espruino`). Read it for history; do not post bthome-writable business there.

The split exists because the two were being mixed up: a request about the *other* integration's web panel arrived addressed to this project. When reading either thread, check which extension a comment is about before acting on it.

You may fetch both for context, but `spec/PROTOCOL.md` supersedes them — earlier iterations there, e.g. a 4-characteristic "EHAC" GATT profile or an objectID-list declaration, are **abandoned**; do not resurrect them.

The project owner (JP, @yerpj on GitHub) drives the discussion with Gordon; you drive the code.

## Rules of engagement

1. **Respect the markers.** `[DECISION]` items are not yours to decide — implement behind a clearly named constant/flag and ask the owner. `[HW]` tasks need physical hardware: prepare everything (code, test procedure, expected results), then hand back to the owner. `[VERIFY]` items are cheap checks that gate design choices — do them at the scheduled point, record the result in `/spec/decisions.md`.
2. **Do not modify the protocol** (§3) on your own initiative. If implementation reveals a genuine spec problem, stop, write up the issue (what breaks, options, recommendation) and hand it to the owner — the spec is co-designed with Gordon and changes must go through him.
3. **Wrap, don't fork.** Espruino side: build on the existing `BTHome` module (https://www.espruino.com/BTHome), reuse its encoding tables, keep advertising ownership in one place. HA side: depend on the `bthome-ble` library for all BTHome parsing — never reimplement it.
4. **Zero-config is non-negotiable.** Any step that would require the user to write configuration by hand (beyond a bindkey prompt) is a design bug. This is the lesson of the failed "Generic Bluetooth Integration" prior art.
5. **Stay upstreamable.** Code as if the HA logic will be proposed into the core `bthome` integration later: HA core style, typing, tests via `pytest-homeassistant-custom-component`, no exotic dependencies.
6. **The bench may not be yours alone.** Home Assistant, the Bluetooth adapter and the Espruino devices are single instances that more than one agent may be using. Reads are free; before any write — deploying, toggling, connecting, cutting power — take the lock (`python -m tools.bench_lock acquire --note "..."`) and release it afterwards. `docs/shared-bench.md` explains what counts as a write and why the failure is silent.
7. **The submission is the owner's to write.** The Open Home Foundation's [AI policy](https://developers.home-assistant.io/docs/ai_policy) governs `home-assistant/*` — `bthome.io`, `brands`, `core` — and says plainly: *"We do not allow autonomous agents to be used for contributing to our projects. We will close any pull requests or issues that we believe were created autonomously"*, and *"Do not use AI to generate answers to questions from maintainers."* So: measure, verify, find contradictions, prepare material for the owner to read and make his own — but **never draft an issue, a pull request or a reply to a maintainer on those repositories**, and never hand over long extracts of this repository's prose to be pasted there. The Espruino discussion is a different project under its own rules (D-091).
8. **Test vectors are the contract.** `/test-vectors/test-vectors.json` (produced in T0.3) must be consumed by BOTH test suites; a change to it is a spec change (rule 2 applies).

## Repo layout (create in T0.1)

```
/spec           PROTOCOL.md, decisions.md, advertising fixtures
/espruino       the JS module + pure-JS unit tests (parse/encode separated from NRF calls)
/custom_components  the HA integration -- at the repo root so HACS installs from GitHub
/ha             its tests, harness and hardware-test procedure
/test-vectors   crypto test vectors (shared contract)
```

## Execution order

Follow §7 of the working document: T0.1 → T0.2 (pause for owner decisions) → T0.5 (early verify: `bthome-ble` tolerance of the 0xFF declaration — it gates the container choice) → T0.3 + T0.4 → T1.1 + T1.2 → hand back for hardware testing → continue per phases.

Start every session by re-reading `spec/PROTOCOL.md`, `SPEC-WORKING-DOCUMENT.md` §6 (the risks), and the most recent decisions at the end of `/spec/decisions.md`.

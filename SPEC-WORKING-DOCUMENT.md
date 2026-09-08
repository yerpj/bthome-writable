# bthome-writable
## Working document v0.4 — spec draft & task breakdown

> Audience: a coding agent (and human reviewers) implementing the project. Read CLAUDE.md first.
> Status: DRAFT, design converged with Gordon Williams (Espruino) in GitHub discussion espruino#8013.
> v0.4 changes (Gordon's second reply, Sep 2026): **same-packet rule** replaces the list-vs-bitmask debate (solves rotation AND multi-instance in one move); write semantics settled as **write-all in packet order**; no-op conventions defined (len-0 / event "none"); encryption direction implemented via the **BTHome device-information byte** (0x41 advertising / 0xFF writes) — no new nonce field; write-only entities are stateless in HA; roadmap confirmed as PoC-first, then approach BTHome for ID reservation.
> Items marked **[DECISION]** need confirmation by the project owner (or Gordon where noted) before the corresponding task starts. Items marked **[HW]** require physical hardware and are handed back to the owner. Items marked **[VERIFY]** are cheap checks that gate a design choice — do them early.

---

## 1. Purpose

BTHome standardizes the BLE **uplink** (device → Home Assistant, advertising-based) but has no **downlink**. This project extends BTHome minimally so devices can declare some of their advertised objects as *writable*, and HA can write new values to them over a short GATT connection — reusing BTHome's own data format and encryption.

Three deliverables:
1. A **spec extension** (writability declaration in advertising + one write characteristic), designed for eventual adoption by the BTHome project.
2. An **Espruino module** making the device side declarative.
3. A **HA custom integration** `bthome-writable` (HACS), designed so its logic could later be upstreamed into the core BTHome integration.

### Non-goals
- Any new data format: values are encoded exactly as BTHome encodes them in advertising.
- Acknowledgements, notifications, or in-connection state: the device's post-disconnect advertising is the confirmation of applied state (write-only entities excepted, see 3.2).
- Connection-oriented sessions: connect → write → disconnect, ideally < 1 s.
- BLE bonding (fragile through ESPHome proxies); security is BTHome's application-layer AES-CCM.

---

## 2. Core model

1. Device advertises normal BTHome (service data UUID `0xFCD2`), including a **writability declaration** (3.1). The declaration and **all writable objects live in the same advertising packet** (the same-packet rule).
2. HA's `bthome-writable` integration sees the declaration and creates writable entities (switch, light, number, text...) alongside the sensor entities that core BTHome already provides. Same MAC → HA merges everything into **one device card**.
3. When the user actuates an entity, HA connects, writes **all writable values** (in BTHome format, in packet order — see 3.3) to a single characteristic, and disconnects.
4. The device applies the values, **immediately refreshes its advertising data**, and HA confirms the new state from the next advertisement (≤ 1 advertising interval). No ack protocol.
5. If the advertisement doesn't reflect the write within a timeout, HA reverts the entity to the last advertised state and logs a warning (advertising is the single source of truth).
6. **Write-only entities** (3.2) are excluded from steps 4–5: they have no advertised state, and are exposed as stateless entities in HA.

---

## 3. Protocol specification (draft)

### 3.1 Writability declaration (advertising) — the same-packet rule

**Settled with Gordon:** the declaration is a bitmask, made unambiguous by the same-packet rule.

- Declaration element: `<0xFF> <bitmask u8>` inside the BTHome service data. Bit *n* = 1 means the *n*-th BTHome object **in this same packet** is writable (bit 0 = first object).
- **Same-packet rule:** a device that rotates advertising payloads MUST place the declaration and every writable object together in one packet (Gordon: "put all the stuff you want to write into the first advertising packet"). Non-writable sensors may rotate freely in other packets.
- **Multi-instance:** ten lights = ten `0x1E`-class objects in the packet; the bitmask and the write order (3.3) both refer to packet position, so instances are unambiguous without new identifiers. This is why position, not objectID, is the reference — Gordon's counter-point to the objectID-list idea, accepted.
- **Placement:** the declaration SHOULD be the **last** element in the service data, so parsers that stop at an unknown object ID (core `bthome-ble` behavior **[VERIFY — T0.5]**) still parse all sensors before hitting it. If `bthome-ble` tolerates/skips unknown IDs, placement is free; if it errors loudly, fall back to the manufacturer-data container below.
- Capacity constraint (normative): declaration + all writable objects must fit one 31-byte advertising payload alongside the BTHome header. Fine for realistic devices (writable objects are few); state the limit explicitly in the spec.
- Extension headroom: bitmask limited to 8 writable objects per device for v1; a second bitmask byte can extend later (flagged by declaration length).
- **Fallback container** (if T0.5 fails, or until BTHome tolerates 0xFF): identical `<tag><bitmask>` payload in an Espruino manufacturer-data AD element **[DECISION — company ID / layout with Gordon]**. Payload byte-identical in both containers; parsing behind a single function per side so migration costs one function.
- **Upstream target:** after the PoC works, ask the BTHome maintainers to at minimum reserve the `0xFF` ID, ideally merge the spec (Gordon's plan, = T4.4).

### 3.2 Write-only entities (official pattern)

Writable objects with no natural uplink value (text display, buzzer/trigger) are declared by advertising the object with an **empty/zero value** (e.g. text object, len 0) plus its writability bit. Agreed with Gordon, with his corollary made explicit:

- The device does **not** advertise written values for these objects (they may exceed the 31-byte budget). The advertised value stays empty.
- HA exposes them as **stateless** entities (`text` in fire-and-forget mode, `button`, event-like actions); the optimistic/confirm/revert model of section 2 does not apply to them.

### 3.3 The write characteristic

One primary service, one characteristic **[DECISION: final UUIDs — freeze before first release, never change after]**:

```
Service (128-bit):                       <to-generate>
  Write (write, write-no-response):      <to-generate>
```

- **Write-all, packet order:** a write is the concatenation of `[objectID][value]` for **every writable object**, in the same order as in the declaration packet. ObjectIDs are technically redundant given positional order, but they keep the payload in pure BTHome format and serve as a sanity check: the device MUST verify each objectID against the expected one at that position and reject the whole write on mismatch (protocol desync guard).
- HA composes the write from: the user's changed value(s) + last advertised values for untouched read-write objects + no-op values for write-only objects.
- **No-op conventions** (for write-only objects the writer doesn't want to trigger):
  - Variable-length objects (text/raw): length 0 = "do not modify".
  - Event-class objects (button-like triggers): BTHome's existing "none" event value (0x00) = no-op — reuses BTHome's own semantics.
- MTU: HA requests MTU ≥ 64; devices SHOULD support long writes (text payloads). Worst case at default MTU 23 (20-byte payload) documented.
- Unknown/extra trailing bytes: reject the write (unlike advertising parsing, writes are a closed format — strictness is safety here).
- Example (Gordon's, single light): packet `D2FC 40 0161 1E01 FF02` → battery 97 %, light on, light writable (bit 1 of the two objects — bit numbering to pin down in T0.2 **[DECISION: bit 0 = first object, recommended]**); HA writes `1E00` → light off → device re-advertises `1E00`.

### 3.4 Encryption

Reuses BTHome v2 AES-CCM (same bindkey, same MIC-4, same nonce construction) with **two deltas, both settled**:

- **Direction via the device-information byte** (Gordon's refinement of the direction-byte idea, adopted): the BTHome nonce already contains the device-info byte (`0x41` in advertising). Writes use `0xFF` as the device-info byte in their nonce. A captured encrypted advertisement can therefore never validate as a write, nor vice versa — cryptographically, with **zero new fields**. (Note for implementers: `0xFF` here is a device-info byte value; the `0xFF` of 3.1 is an object ID. Different fields, no technical conflict — distinct names in the spec to avoid confusion.)
- **Independent counters per direction** — still required (the device-info split kills *cross*-direction replay only): the device tracks the last accepted **write** counter (RAM + periodic flash persist), rejects `counter <= last`, accepts forward jumps (recovery after HA reinstall); the device's own advertising counter is unrelated. HA persists its write counter in the config entry and offers a resync step on auth failure.
- Rationale kept from review: "a write wouldn't contain the 0xFF bitmask so replay wouldn't work" is not a defense — the write parser tolerating unknown objects would still apply the rest of a replayed advertisement. The device-info split is the real fix; additionally, per 3.3, writes reject unexpected content anyway.
- Encrypted write payload: `[counter u32 LE][ciphertext][MIC 4]`, ciphertext = plaintext of 3.3.
- Unencrypted devices remain permitted (BTHome policy); HA config flow SHOULD warn when actuator-class objects are writable without encryption.
- Deliverable: `test-vectors.json` (bindkey, MAC, device-info byte, counter, plaintext, ciphertext, MIC — ≥ 10 vectors both directions, including a cross-direction replay negative test). **This file is the contract between the two codebases.**

### 3.5 Device requirements

- Static BLE address (Espruino/nRF52 default). RPA breaks HA device merging; spec mandates static.
- After applying a write: update advertising data **immediately** (agreed with Gordon) so HA confirms within one interval.
- Connectable advertising at all times (only battery delta vs. a plain BTHome beacon; measure, expect negligible).

---

## 4. Espruino module

Target API:

```js
var bw = require("bthome-writable");   // wraps/extends require("BTHome")
bw.setup({
  key: "0123...ef",                    // optional bindkey; absent = unencrypted
  advertise: [
    { type: "battery", get: () => E.getBattery() },
    { type: "switch",  get: () => light.on,
      set: v => { light.on = v; digitalWrite(D2, v); } },   // writable: has `set`
    { type: "text",    writeOnly: true, maxLen: 32,
      set: t => { g.clear().drawString(t,0,0); g.flip(); } },
  ],
  interval: 2000
});
```

- An entry is writable iff it has `set`. The module: orders writable entries into the declaration packet (same-packet rule), builds the bitmask, enforces the 31-byte capacity at setup (throw with a clear message if exceeded), parses write-all payloads with positional objectID verification, applies no-op conventions, refreshes advertising immediately after a write.
- Reuse/extract the encoding tables from the existing BTHome module rather than duplicating; advertising ownership lives in exactly one place.
- AES-CCM in interpreted JS: Espruino `crypto` exposes mbedTLS AES but possibly not CCM; may need CTR + CBC-MAC assembly. **Benchmark early [HW — T1.3]**; if > ~50 ms/frame, track a firmware `crypto.ccm` upstream proposal (non-blocking: unencrypted ships first).
- Write-counter persistence via `Storage`: write every 64 increments + on disconnect, resume at `stored + 64` after boot.
- RAM target: < 4 kB with 8 entries.

---

## 5. Home Assistant integration (`bthome-writable`, HACS)

- **Matcher:** primary path (0xFF in BTHome service data) → match UUID `0xFCD2` like core BTHome, config flow inspects the advertisement and **aborts `not_supported`** when the declaration is absent (standard shared-UUID mechanism; users never see plain BTHome devices). Fallback container (manufacturer data) → match directly on `manufacturer_id`. Keep both behind the single parsing function of 3.1.
- Config flow: discovery → confirm → bindkey prompt if the advertising is encrypted (parse via the `bthome-ble` library — dependency, do not reimplement) → unencrypted-actuator warning when applicable.
- Entity mapping from writable objects → platforms: on/off-class → `switch`/`light`, percentage/level-class → `number`/`light` brightness, text → `text` (stateless when write-only), event/trigger-class → `button`. Table written in T2.1 against the BTHome object list; unknown writable IDs ignored with a debug log.
- State model: read-write entities are advertising-driven with optimistic update → confirm → revert-on-timeout (default 5 s **[DECISION]**); write-only entities are stateless (3.2).
- Write composition: coalescing queue per device (latest value per position); each flush produces one write-all payload (3.3); `establish_connection()` (bleak-retry-connector), MTU ≥ 64, write, disconnect. Global simultaneous-connection cap (default 2 **[DECISION]**) for ESPHome proxy slot safety.
- Device registry: `DeviceInfo(connections={(CONNECTION_BLUETOOTH, mac)})` → merges with the core BTHome device card.
- Availability: advertising presence callbacks (habluetooth), same timeout as BTHome.
- Dependencies: `habluetooth`, `bleak-retry-connector`, `cryptography`, `bthome-ble`.
- Reference code to study first: core `bthome` integration (matching, parser usage) and `switchbot` (connection handling). Prior art for lessons (why it didn't catch on): the "Generic Bluetooth Integration" HA community project — manual per-device configs, no self-description. `bthome-writable` must remain strictly zero-config.
- **Coexistence with `homeassistant-espruino`** (Gordon's integration: arbitrary JS over UART + embedded Web IDE): complementary channels — developer/administration vs entity/automation. Same device may expose both. `bthome-writable`'s short connect-write-disconnect must never starve a UART/IDE session; document the combo; longer-term (out of scope): a PR so `homeassistant-espruino`'s UI can scaffold `bthome-writable` device code.
- End-game shaping the code: logic clean enough to propose upstream into core `bthome` once the ID is reserved. Avoid architectural choices that would block that.

---

## 6. Known risks & gotchas (read before coding)

1. **Core `bthome-ble` behavior on unknown object 0xFF** — gates declaration placement and container choice. **[VERIFY — T0.5, do first]**: feed the parser a valid BTHome payload with a trailing `0xFF <bitmask>`; check sensors still parse and no error spam. Tolerant → primary path confirmed; loud failure → manufacturer-data fallback becomes primary.
2. **Same-packet capacity** — declaration + all writable objects ≤ 31 bytes. Enforced at Espruino setup with a clear error; documented limit in spec.
3. **CCM performance in interpreted JS** — benchmark in Phase 1 [HW]; firmware fallback path identified.
4. **MTU vs. text writes** — MTU negotiation + long writes; 20-byte worst case documented.
5. **Write-counter desync** (HA reinstall / device reflash) — forward-jump acceptance + HA resync step (3.4).
6. **RPA / unstable MAC** breaks device merge — spec mandates static address; integration logs a clear error on instability.
7. **Confirmation latency** — long advertising intervals (battery-tuned) are covered by the immediate-refresh rule (3.5); verify Espruino can update adv data instantly while connectable [HW].
8. **Positional desync between HA's view and the device** (device reflashed with different entity order while HA holds stale layout) — mitigated by objectID verification in 3.3 (device rejects mismatched writes) + HA re-reads layout from advertising on every write composition.
9. **Coexistence with the existing Espruino BTHome module** — wrap, don't fork, if feasible; advertising ownership in exactly one place.
10. **Config-flow abort UX** — verify the `not_supported` abort doesn't leave noisy "discovered" notifications for plain BTHome devices [Phase 2 test].
11. **UUID / format freeze** — service & characteristic UUIDs, declaration format and no-op conventions are frozen at first public release; never change after.

---

## 7. Task breakdown

### Phase 0 — Foundations (no hardware)
- **T0.1 Repo & scaffolding.** `/spec`, `/espruino`, `/ha`, `/test-vectors`; CI (Python lint+pytest, JS lint). → AC: CI green on skeletons.
- **T0.2 Spec v1-draft → `/spec/PROTOCOL.md`.** Formalize section 3 (same-packet rule, bitmask numbering, no-op conventions, nonce device-info values); generate UUIDs; resolve remaining [DECISION] items with owner. → AC: reviewed, tagged, linked in discussion espruino#8013.
- **T0.5 (early) `bthome-ble` tolerance check [VERIFY].** Unit-level: feed payloads with trailing `0xFF` declaration to the `bthome-ble` parser; document behavior; record container decision. → AC: written result in `/spec/decisions.md`; risk #1 closed.
- **T0.3 Crypto test vectors.** Generator + `test-vectors.json` (≥ 10 vectors both directions, cross-direction replay negative test, edge counters), verified against an independent AES-CCM implementation. → AC: cross-checked.
- **T0.4 Advertising fixtures.** Sample payloads (hex): declaration placements, multi-instance (several same-ID objects), write-only empty values, rotation with same-packet rule, encrypted. Matching write-all payloads incl. no-ops. → AC: fixtures in `/spec`, used by both test suites.

### Phase 1 — MVP (unencrypted, one switch)
- **T1.1 Espruino module MVP.** Declaration packet + bitmask + GATT write characteristic + write-all parsing (on/off only) + positional objectID check + immediate adv refresh. Pure-JS parse/encode separated from NRF calls. → AC: nRF Connect manual test: write toggles GPIO, advertising reflects it < 1 interval [HW].
- **T1.2 HA integration MVP.** Matcher + `not_supported` abort + `switch` platform + queue → write-all composition → connect-write-disconnect + optimistic/confirm/revert. → AC: end-to-end toggle from HA UI, direct and via ESPHome proxy [HW]; plain BTHome device not offered.
- **T1.3 CCM latency spike (Espruino)** [HW]. → AC: ms/frame on nRF52840 recorded; go/no-go on JS CCM.

### Phase 2 — Full model
- **T2.1 Object ↔ platform mapping** (spec + HA + Espruino encodings): light+brightness, number, text (write-only pattern), button/event with "none" no-op. → AC: mapping in `/spec`; T0.4 fixtures produce expected entities in `pytest-homeassistant-custom-component` harness.
- **T2.2 Same-packet rule & multi-instance** both sides: rotation fixtures, several same-ID objects, positional writes. → AC: fixtures pass on both implementations; desync writes rejected (risk #8 test).
- **T2.3 Device merge & availability.** Shared-MAC merge with core BTHome; advertising-presence availability. → AC: one device card mixing sensors and writable entities [HW]; unavailable on power-off.
- **T2.4 Confirmation model hardening.** Timeout/revert, warning surfacing, batching into one write-all, stateless write-only paths. → AC: fault-injection (write applied but adv suppressed → revert; slow adv interval → confirm; write-only never waits).

### Phase 3 — Encryption
- **T3.1 Espruino:** CCM (per T1.3) + device-info-byte direction + write-counter persistence. → AC: all vectors pass on-device [HW]; reboot without replay lockout; cross-direction replay rejected.
- **T3.2 HA:** encrypted writes + bindkey flow + counter persistence + resync-on-auth-failure + unencrypted-actuator warning. → AC: vectors pass; wrong-key, counter-jump and replayed-advertisement-as-write tests pass.

### Phase 4 — Release & standardization
- **T4.1 Robustness.** Coalescing, retries/backoff, connection cap, failure surfacing (logbook). → AC: disconnect-mid-write fault injection passes; slider spam → one write.
- **T4.2 Docs.** Espruino flash-and-go tutorial, HACS install guide, spec page. → AC: naive-user walkthrough executed by owner [HW].
- **T4.3 Publication.** HACS (hacs.json, brands PR); Espruino module PR to EspruinoDocs. → AC: installable from HACS; PR opened.
- **T4.4 Standardization** (owner + Gordon, not the agent) — evidence-first, per Gordon's plan: working integration + PoC code, then submit to the BTHome maintainers to at minimum **reserve the 0xFF ID**, ideally merge into BTHome; exploratory issue on upstreaming into HA core `bthome`. → AC: dossier prepared (demo, spec, adoption, migration story); submission filed when owner/Gordon judge timing right.

### Suggested agent execution order
T0.1 → T0.2 (pause: owner decisions) → **T0.5** → T0.3 + T0.4 → T1.1 + T1.2 in parallel → owner [HW] loop → T1.3 → Phase 2 → Phase 3 → Phase 4.

---

## 8. Open decisions

1. Final service/characteristic UUIDs (freeze at T0.2).
2. Bitmask bit numbering (recommend bit 0 = first object in packet) — trivial, but pin it in T0.2 and confirm with Gordon.
3. Manufacturer-data fallback container details (company ID, tag byte) — with Gordon; only needed if T0.5 fails.
4. Confirmation timeout default (5 s?).
5. Global connection cap default (2?) and user-configurability.
6. Project/module naming: `bthome-writable` assumed — have a fallback ready if the BTHome maintainers object to the name at T4.4.
7. License (suggest MIT both sides).

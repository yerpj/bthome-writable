# T4.2 walkthrough — the acceptance test for the documentation

The acceptance criterion for T4.2 is not "the documents exist". It is that
someone who has never seen this project can follow them and end up with a
working control. That cannot be verified by the person who wrote them, so this
is the owner's to run.

**How to run it.** Use only
[`espruino-quickstart.md`](espruino-quickstart.md) and
[`home-assistant-install.md`](home-assistant-install.md). If you find yourself
reaching for the source, the decision log, or something you happen to remember,
**stop and write down what was missing** — that is the finding, and it is worth
more than finishing the run.

Best done on a board that is not already set up, and ideally by someone else.

## The run

| # | Step | Expected | Result |
| --- | --- | --- | --- |
| 1 | Paste `single-light-standalone.js` into the Web IDE, send | console prints the address and `writable entries: [ 30 ]` | **FAILED (2026-10-09).** IDE set to *Save on Send: direct to flash*: `Compacting...` then `Uncaught Error: Unable to find or create file`. 41 848 bytes written into a Puck.js's 40 960 of Storage. The quickstart names RAM as a consequence (*"It runs from RAM"*), never as a setting, so nothing said the send mode mattered; Espruino's message names neither RAM, flash nor size, leaving no next step. The `.min.js` (18 193 bytes) would have fitted. **The documented path was then tried properly, to RAM, and it fails too**: `OUT OF MEMORY at getAdvertisement`, then `New interpreter error: LOW_MEMORY,MEMORY`, and `bw.plan()` null — setup() died half-built. So the readable bundle fits a Puck.js neither in flash nor in RAM. Every readable bundle is 40-42 kB and every minified one 18-19 kB, so this is the whole shelf, not one file. The quickstart's main instruction and `try-it.md`'s fallback both name a readable bundle; neither works on the board this project uses as its reference. Nobody had hit it because the bench always sends the `.min.js` or goes through `espruino_deploy`, which installs the modules into Storage and uploads a small application. **Passed on the second attempt** with the `.min.js` to flash: `advertising as c8:80:32:ad:f7:b9` / `writable entries: [ 30 ]`, on 2v27. One cosmetic mismatch: the quickstart's expected console shows the address followed by `public`, the board printed it without. |
| 2 | Scan, or `python -m tools.bthome_write --address <mac> --payload 1e01` | LED on, the write acknowledged in milliseconds | **Passed**, and by the independent path: nRF Connect on a phone, `1E01` -> red LED on, `1E00` -> off. No tool of ours in the loop, which is the stronger version of this step. |
| 3 | Install via HACS, restart | *BTHome Writable* appears in HACS and in the integration list | **Not tested.** Already installed on this instance, and nothing in the documents tells a reader in that position what to do. Honest gap: the install path has still never been walked by someone who did not write it. |
| 4 | Look at Devices & services | the board is offered without being asked for | **Passed.** Offered by itself; the entry records `source=bluetooth`. |
| 5 | Configure it | one switch, no questions beyond confirming | **Passed.** One switch, no bindkey asked — notable, because Home Assistant had been holding a stale *encrypted* advertisement for this address and the fresh plaintext one superseded it. |
| 6 | Find the device page | switch **and** the core BTHome sensors on one card | **Passed.** `switch.bureau_mobilesensf7b9_light` from this integration and `sensor.bureau_mobilesensf7b9_battery` (100 %) from core `bthome`, on one device, renamed `mobileSensf7B9` by the owner. |
| 7 | Toggle from the UI | LED follows, entity settles in about 1–3 s, shown as assumed state | **Passed** both ways. The owner's words on the delay: *"conforme"* — it matched what the document led him to expect, which is the question this row is really asking. |
| 8 | Power the board off, wait | entity goes unavailable | **Passed, but the document implies something quicker.** Seven minutes by the owner's clock; the recorder says both entities flipped at 13:54:06, 8 min 35 s after the last packet. **Ours and core BTHome's turned unavailable in the same second**, which settles whose timing it is: we delegate to `bluetooth.async_track_unavailable` and every Bluetooth integration waits exactly as long. Nothing to fix in the code; a sentence is missing from the documents. |
| 9 | Power it back on | the sketch is gone (it runs from RAM) and the docs said so | **Could not be tested** — this run put the sketch in flash (see the deviation above), so it survived by design. What was observed instead: the entity came back **in under a second** after the cell went in. Disappearing takes 8½ minutes, reappearing is immediate; only the first of those is in the documents. |
| 10 | Re-send, toggle again | works, without re-adding anything in Home Assistant | **Passed**, without the re-send: the toggle worked straight away and Home Assistant needed nothing. The half this run does test — that a power cycle costs the user no reconfiguration — held. |

**Deviation in the 2026-10-09 run, so the rows below read correctly.** After
step 1 failed, the run continued with `single-light-standalone.min.js` sent *to
flash* rather than the documented bundle sent to RAM. Step 9 therefore cannot
test what it was written to test: a sketch in flash survives a power cycle by
design.

## Then the part that is actually being tested

- Was there a moment you did not know what to do next?
- Did anything take materially longer than the document implied?
- Did any error message leave you without a next step?

**Found in the 2026-10-09 run, at step 8:** *"where will I see unavailable in
Home Assistant?"* — the documents say an entity goes unavailable and never say
where that is visible. The owner had to ask. Two sentences on the device page
and on Developer tools / States would close it.
- Is there a step you only completed because you already knew the answer?

Record the answers in `spec/decisions.md` as the T4.2 entry, including the
failures. A walkthrough that reports "all fine" is usually a walkthrough run by
someone who knew too much.

### Answers, 2026-10-09 (the owner, on a Puck.js and the bench instance)

1. **Yes** — at step 8: *"where will I see unavailable in Home Assistant?"*.
   Neither document says where that is visible.
2. **Yes** — 8 min 35 s to go unavailable, against a document that says "wait".
   Recovery, by contrast, was under a second.
3. **Yes** — `Uncaught Error: Unable to find or create file`, which names
   neither RAM, nor flash, nor size.
4. **No.** *"j'ai joué à l'ignorant... Je n'ai pris aucun raccourci."* The only
   step not taken was installing through HACS, which was already installed.

One observation the owner's answer does not cover, because it is visible only
from outside: recovering from the step 1 failure meant reaching for
`single-light-standalone.min.js`, **a file no document mentions**. He found it
by listing `espruino/dist/`, which a reader could also do — but the documents
offer no route to it.

## Known rough edges, so they are not reported as discoveries

- **The Web IDE cannot send a single very large statement.** The bundles are
  flat rather than wrapped in a closure for exactly this reason. If you build
  your own and wrap it, it will truncate silently.
- **The first command after a quiet period is slow** — two to three seconds at
  a one-second advertising interval. It is the battery trade, not a fault.
- **An ESPHome proxy that is configured is not necessarily registered.** Check
  that Home Assistant actually lists it as a scanner before assuming it gives
  the device a second route.

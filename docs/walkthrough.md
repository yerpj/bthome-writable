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
| 1 | Paste `single-light-standalone.js` into the Web IDE, send | console prints the address and `writable entries: [ 30 ]` | |
| 2 | Scan, or `tools.bthome_write --payload 1e01` | LED on, the write acknowledged in milliseconds | |
| 3 | Install via HACS, restart | *BTHome Writable* appears in HACS and in the integration list | |
| 4 | Look at Devices & services | the board is offered without being asked for | |
| 5 | Configure it | one switch, no questions beyond confirming | |
| 6 | Find the device page | switch **and** the core BTHome sensors on one card | |
| 7 | Toggle from the UI | LED follows, entity settles in about 1–3 s, shown as assumed state | |
| 8 | Power the board off, wait | entity goes unavailable | |
| 9 | Power it back on | the sketch is gone (it runs from RAM) and the docs said so | |
| 10 | Re-send, toggle again | works, without re-adding anything in Home Assistant | |

## Then the part that is actually being tested

- Was there a moment you did not know what to do next?
- Did anything take materially longer than the document implied?
- Did any error message leave you without a next step?
- Is there a step you only completed because you already knew the answer?

Record the answers in `spec/decisions.md` as the T4.2 entry, including the
failures. A walkthrough that reports "all fine" is usually a walkthrough run by
someone who knew too much.

## Known rough edges, so they are not reported as discoveries

- **The Web IDE cannot send a single very large statement.** The bundles are
  flat rather than wrapped in a closure for exactly this reason. If you build
  your own and wrap it, it will truncate silently.
- **The first command after a quiet period is slow** — five to seven seconds at
  a one-second advertising interval. It is the battery trade, not a fault.
- **An ESPHome proxy that is configured is not necessarily registered.** Check
  that Home Assistant actually lists it as a scanner before assuming it gives
  the device a second route.

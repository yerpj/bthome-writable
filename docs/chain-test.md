# The chain test: Home Assistant in the loop

`tools.regression` answers the two things a user feels — **does a command
arrive, and when**. It says nothing about the two things D-108 and D-109
changed, which are *when the module publishes an advertisement* and *when it
reads a sensor*. Neither can be judged on the device: half of each claim is
what a receiver makes of it.

- **P2 (D-108)** republishes the bytes already on air when only the advertising
  rate changes — same packet id, and on a sealed device the same encryption
  counter. A receiver that treated an unchanged counter as a replay would have
  made that unshippable, silently, on encrypted devices only.
- **P1 (D-109)** reads each entry on its own schedule instead of at a fixed
  tick. A device that woke correctly but stopped reading would look perfectly
  healthy from the console and go stale in Home Assistant.

So this drives the whole chain — Espruino sketch, radio, the host's adapter,
`bthome-ble`, the integration, the entity, a service call, the GATT write, the
device — and judges it.

```
python -m tools.bench_lock acquire --note "chain test"
.venv-ha/Scripts/python.exe -m tools.chain_test
python -m tools.bench_lock release
```

About six minutes. Exit status 0 only if nothing failed, so it can gate a
release next to `tools.regression`. `aiohttp` lives only in `.venv-ha`
([`shared-bench.md`](shared-bench.md)).

**What the bench must look like:** `HA_URL` and `HA_TOKEN` in the environment,
the bench lock held, the nano running `examples/oled-text.js` and the Puck
running `examples/light-loop.js`. Those two examples are not decoration — the
checks below depend on exactly what they advertise: a 30 s die temperature, an
`interval: 0` illuminance, a 300 s battery, a writable text and a writable
light.

## The eight checks

| | what it asserts | what it would catch |
|---|---|---|
| **A** | `bthome_writable` is loaded and every entity of both devices exists and is not `unavailable` | a config entry that failed to come back up; the zero-config promise broken |
| **B** | the `interval: 0` illuminance reaches HA at the advertising rate — at least ten reports in 30 s, no gap over 5 s | P1 scheduling the fast entry at the wrong rate, or not at all |
| **C** | the 300 s battery reaches HA once or twice in 320 s, and if twice, 280–340 s apart | P1 reading a slow entry far too often — Gordon's objection, at the far end of the chain |
| **D** | a command lands and is acknowledged on both boards | the write path, both kinds of entity |
| **E** | a write through HA moves what HA measures: the illuminance follows the light | the closed loop. The light's own state is never advertised (§2.3), so this is a *different* object proving the write had an effect |
| **F** | ten commands in a row all arrive, and the tenth is the one that stands | the dimming burst of D-106, now that `handleWrite` publishes once (D-108) |
| **G** | the fast window opening and closing is invisible: advertisements keep arriving across it and nothing goes `unavailable` | P2's republication being mistaken for new or corrupt data |
| **H** | Home Assistant logged nothing about any of it | everything else, cheaply |

B and C together are the whole of P1 seen from outside: **one self-arming timer
serving a one-second entry and a five-minute one, each at its own rate, on the
same device.** E, F and G are P2's: the advertisements a burst and a rate change
publish are the bytes already on air, and a receiver cannot tell.

## The two checks that are not on the bench

The bench's Home Assistant has no encrypted device configured — there is no
config entry with a bindkey, and creating one needs the config flow — so the
sealed half of P2 is qualified in the test suite instead, against the real
receiver library, in `tools/tests/test_bthome_ble_tolerance.py`:

- **the same sealed advertisement three times over** keeps verifying, keeps its
  values and keeps its packet id. This is P2's premise, checked rather than
  argued: `bthome-ble` accepts a repetition with an unchanged counter, which is
  what BTHome's *"multiple advertisements that are exactly the same"* allows.
- **a counter that goes backwards** is what the library does refuse, and it
  refuses it by *skipping* the advertisement and keeping the last good one — a
  warning in the log and stale data, not an exception. That is the failure P2
  had to avoid, so it is worth having both halves written down.

## When E says it could not tell

Check E reads a light sensor, so it depends on the room. Under a cover, the
Puck's own green LED is the only thing its sensor can see and the difference is
enormous. **Uncovered — which is how this bench has stood since 2026-10-20 —
the room can swallow it.** The check takes five readings with the light off and
five with it on, and asks for a difference of at least 5 lx plus three times
the noise it just measured; when the room does not allow that it prints

```
  ????  E  a write through HA moves what HA measures   ... -- cover the Puck and run this again
```

and the run ends *qualified except E*, exit status 0. That is deliberate: an
inconclusive check must not read as a bug in the module, and must not read as a
pass either. Cover the Puck and E answers.

## The first run

2026-10-20, on commit `06a3da0` (P1 and P2 both in), both boards redeployed from
that commit: **every check passed, exit 0.** The `interval: 0` illuminance was
reported 11 times in 30 s and 140 times across the 320 s window; the 300 s
battery once in that same window; ten commands in a row all landed, median
0.38 s; and the closed loop read 75 lx with the light off against 540 lx with it
on — the Puck uncovered, and still a factor of seven. See
[`measurements.md`](measurements.md) §12 for the output.

## If check H fails

It will name a logger and a message. One of them has a history: `bthome_ble.parser`
warning that *object ids are not in numerical order*. Twice on 2026-10-20 that
warning named these boards, and both times the payload in it had lost the
`0xFF` declaration byte — while what the boards were really advertising parsed
cleanly at that same moment, and a three-minute scan of 174 advertisements found
none malformed (`tools.adv_health`, D-111). **Capture the advertisement before
suspecting the module:**

```
.venv-ha/Scripts/python.exe -m tools.adv_health 180
```

The module computes the declaration's bytes and its position once, in `setup()`,
and never touches them again (D-106), so a packet that has lost them did not
leave the device that way.

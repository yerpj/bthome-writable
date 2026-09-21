# The reliability and latency guard

Three test suites check bytes and branches: 241 in `tools`, 123 in `ha`, 211 in
`espruino`. Not one of them could have caught the changes that moved this
project's numbers most.

- The write batching held a second command behind the first for 1.5 s. Every
  test passed. It took a hardware campaign to see it (D-059, D-060).
- One connection in ten timed out and was silently retried, so a command landed
  30–50 s after the click and reported success. Every test passed (D-061).
- A re-created config entry restarted its write counter at zero, so an encrypted
  device refused every write — silently, because the GATT write is acknowledged
  before it is validated. Every test passed (D-063).

Those are the two things a user actually feels: **does a command arrive, and
when**. This guards them.

```
python -m tools.bench_lock acquire --note "regression run"
python -m tools.regression                      # judge both devices
python -m tools.regression --device puck        # one of them
python -m tools.regression --update-baseline    # record a new baseline
python -m tools.bench_lock release
```

Exit status is 0 when nothing regressed and 1 when something did, so it can gate
a release. About three minutes per device.

## What it measures

One advertising interval, 1 s — a guard, not a study; the ladder from 100 ms to
5 s lives in [`measurements.md`](measurements.md). Per device: eight first
commands, each after the device has fallen back to its idle interval, and
sixteen repeated ones inside its fast-advertising window.

| Metric | What a change in it would mean |
|---|---|
| First command, median and 90th percentile | the cost of catching an advertisement and opening a link |
| Repeated command, median and 90th percentile | the warm path — the receiver's own queueing, where D-059 lived |
| The write itself, median | the GATT exchange; it has never moved from 36 and 43 ms |
| Delivered fraction | commands that arrived at all |
| Connected without a retry | how often the receiver's second attempt was needed (D-061) |

## What counts as a regression

The thresholds are in `compare()` in `tools/regression.py`, in one place, so
that changing one is a reviewable diff. They are deliberately generous:

| | allowed |
|---|---|
| First command, median | baseline × 1.6 + 0.30 s |
| First command, p90 | baseline × 2.0 + 0.50 s |
| Repeated command, median | baseline × 1.6 + 0.15 s |
| Repeated command, p90 | baseline × 2.0 + 0.30 s |
| The write itself | baseline × 2.0 + 20 ms |
| Delivered | baseline − 0.10 |
| Connected without a retry | baseline − 0.20 |

**Why so loose.** Two runs of the same build, at the same interval, produced
medians 30–50 % apart (D-061) — the distribution is wide by nature, and a guard
that fails on weather is a guard someone switches off. The factors catch the
changes that matter, which were not subtle: the batching's pause was a factor of
five, the retry a factor of twenty.

**The floors matter as much as the factors.** A baseline of 0.35 s guarded only
by ×1.6 would fail at 0.56 s, and a single repeated command has legitimately
reached 1.94 s in eighty samples (D-062). Without a floor the small numbers
would be policed more tightly than the large ones, which is backwards.

**A suspiciously fast run is flagged, not celebrated.** Through the ESP32 proxy,
first commands came back faster than catching an advertisement allows, because
it reuses a recent link (D-054). A result far below the baseline says the bench
stopped measuring the same thing; the run prints `hm` and says so, and does not
fail.

**A run with a sample on the wrong side of the fast window is not judged.** A
first command taken while the device is still advertising fast measures the
other case under this one's label. The harness records, per sample, how long the
device had been left alone when the command was issued, and refuses to compare a
run that contains one — that is a broken measurement, not a regression.

## What it does to the bench, and restores

`tools/ha_bench.py` disables the ESP32 proxy and the OLED automation for the
duration and puts back exactly what it changed. Both would otherwise make a run
incomparable: the proxy reuses links, and the automation keeps the nice!nano
permanently inside its fast window. The device's fast window is shortened to 8 s
for the run and restored to 30 s. Take the bench lock first, as for any
measurement (`docs/shared-bench.md`).

## When it fails

In order:

1. **Was the bench the same?** The baseline records what it was taken on. A
   proxy left enabled, a device at a different advertising interval, someone
   else's campaign running — check before believing the number.
2. **Is it the radio or the receiver?** The split says so: `connect_ms` against
   the rest. A change in the write itself, or in the repeated-command median
   with the queue empty, is this integration's doing. A change in the first
   command alone is usually the link.
3. **Re-run once.** The spread is wide, and a single run of eight first commands
   can land badly.

## The baseline

[`data/regression-baseline.json`](data/regression-baseline.json), with the date,
the commit it was taken at, the bench configuration and the sample counts. Re-record
it deliberately — `--update-baseline`, with the lock — and say in the commit
message what changed and why the new numbers are the ones to keep. A baseline
quietly re-recorded to make a run pass is the one way this guard becomes
worthless.

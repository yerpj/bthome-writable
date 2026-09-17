# Sharing the bench with another agent

Read this before touching Home Assistant or the hardware. It is short because
there is really only one rule, and one list of things that rule does not cover.

## The bench

One Home Assistant instance at `http://haosjry.local:8123`, one Bluetooth
adapter that instance owns, one Puck.js, one nice!nano with an SSD1306, and one
OOTY debug board on `COM8` that switches the Puck's 3V3 rail. There is exactly
one of each. Home Assistant's configuration is reachable over SMB at
`\\haosjry.local\config` (the integration lives in `custom_components/`).

## The rule

**Reads are always free. Writes are serialised by a lock.**

A read is anything that only observes: `python -m tools.ha_probe`, reading the
entity or device registry, watching advertisements with a passive scan, reading
the log. Two agents can do that at once all day.

A write is anything else, and the list is longer than it looks:

- deploying `custom_components/bthome_writable` to the share, or reloading it
- calling a service, toggling an entity, adding or removing a config entry,
  renaming or deleting entities
- connecting to the Puck or the nice!nano at all — a BLE connection is
  exclusive, and so is the adapter
- deploying anything to either Espruino device
- changing a device's advertising interval (`tools.set_adv_interval`,
  `tools.latency_sweep`) — this one outlives the lock, so put it back when you
  are done
- touching `COM8` / the 3V3 rail

## Why it has to be a lock and not good manners

Because the failure is silent. If you redeploy the integration while another
agent is halfway through a hardware test, that agent's test still *passes* —
against code it did not write, on a device in a state it did not set up. It
gets a green result and believes it.

That is not hypothetical here. Twice in this project a single agent reached a
wrong conclusion by reading the receiver's optimistic state instead of the
device (`spec/decisions.md`, D-039 and D-041). An optimistic entity looks
exactly like a working one. Two agents make that mistake cheap to reproduce and
much harder to spot.

## Taking the lock

```
python -m tools.bench_lock status
python -m tools.bench_lock acquire --holder <your-name> --note "what you are doing"
python -m tools.bench_lock renew                 # before a long run runs out
python -m tools.bench_lock release               # always, even after a failure
```

`acquire` exits non-zero if the bench is busy and prints who has it and for how
long. `--wait <minutes>` polls instead of failing. Set `BENCH_HOLDER` in the
environment once and you can drop `--holder`.

Default lease is 30 minutes. It expires so that an agent which dies mid-test
does not block the bench until a human notices; the next `acquire` takes an
expired lock and says loudly that it did. Renew rather than relying on that.

Please put something real in `--note`. "deploying integration + toggling the
Puck's LED" tells the other agent whether they can wait five minutes or should
go do something else.

### If you cannot run the script

The lock is one JSON file, `\\haosjry.local\config\bthome-writable.lock`
(`//haosjry.local/config/bthome-writable.lock` opens cleanly from Python on
Windows). Absent means free. Present and `expires` in the future means held.
Create it with `O_EXCL` — that is honoured over this SMB share, verified — and
write at least:

```json
{ "holder": "your-name", "note": "what you are doing", "expires": 1789459200.0 }
```

Delete the file to release.

## What the lock does not do

It is advisory. It cannot stop an agent that never asks, and no file can
arbitrate a power rail. It makes the common case correct and a collision
visible. That is the whole of its ambition.

It also does not protect the git working tree at
`C:\Users\JP\Documents\perso\bthome-writable`. If you are working in the same
checkout, coordinate separately.

## Rules the lock cannot enforce, and that matter more than it does

**Never write application code to an Espruino's flash.** Modules may go to
Storage; the sketch runs from RAM. `tools/espruino_deploy.py` already does this
and only writes `.bootcde` with an explicit `--to-flash`. The reason is D-029:
a bad advertising payload throws inside `setup()`, the radio stops to
reconfigure and stays stopped, `.bootcde` replays the failure at every boot, and
a device that does not advertise cannot be connected to — so it cannot be fixed
over the air at all. Recovery needs the owner's hands on the button. Do not
spend someone else's afternoon this way.

**Do not delete or rename config entries and entities to tidy up.** The entry
carries the bindkey and the write counter. A counter that goes backwards is
refused by the device silently, and the symptom is "the control stopped
working" hours later.

**The repository is the source of truth for the integration**, not the copy on
the share. If you deploy, you have just overwritten whatever the other agent
put there — say so in your lock note, and expect them to redeploy after you.

**Verify on the device, not on the receiver.** If Home Assistant shows the new
state, that may only mean the entity is optimistic. Read the advertisement back,
or read the Puck's own variables over the console.

**Your BLE connection can lock Home Assistant out of a device for hours.** An
Espruino accepts one central at a time, and Windows keeps the link open well
past `disconnect()`. Home Assistant then reports `The proxy/adapter is out of
connection slots or the device is no longer reachable` — which is false in both
halves and points at the receiver, so it is very easy to spend an evening
restarting Home Assistant instead. If writes from Home Assistant fail while your
own direct writes still work, that is not evidence the device is healthy: it is
evidence *you* are holding it. Power-cycle the device first (D-043).

## Work that needs no lock at all

Most of it, which is the real answer to "can two agents help here":

- both test suites — `ha/tests` runs under `pytest-homeassistant-custom-component`
  with no hardware and no live Home Assistant, and the Espruino module's
  parse/encode tests are pure JavaScript
- the test vectors in `test-vectors/` and anything that consumes them
- the spec, the decision log, the documentation
- code review, and any change that does not need to be observed on hardware to
  know whether it is right

Take the lock for the last mile, not for the work.

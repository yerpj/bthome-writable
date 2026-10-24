# Sharing the bench with another agent

Read this before touching Home Assistant or the hardware. It is short because
there is really only one rule, and one list of things that rule does not cover.

## The bench

One Home Assistant instance at `http://haosjry.local:8123`, one Bluetooth
adapter that instance owns, two ESPHome Bluetooth proxies, one Puck.js, four
nice!nanos and one OOTY debug board on `COM8` that switches a 3V3 rail. There is
exactly one of each.

**The OLED automation is off since 2026-10-23**, by the owner, who does not
need it. It wrote the Puck's illuminance to the `COM15` nice!nano every 30 s
over the same adapter, which is traffic every measurement had to turn off first
(`tools.ha_bench.bench_prepared`). Leave it off; a run that wants it on must put
it back.

**The second nice!nano, on `COM6`, arrived 2026-10-23** and runs
`espruino/bench/revision-lamp.js`: the bench's only device whose writable
entries are also readable, so it is the only one that advertises a settings
revision and owes the receiver a read (D-130). Its sketch lives in RAM, so a reset or a power cut leaves it silent
until it is uploaded again.

**The bench runs sealed by default since 2026-10-24** (D-139): encrypted is the
normal state of a board here and in clear is the exception that needs a reason.
One key for everything, `231d39c1d7cc1ab1aee224cd096db932`, the public one from
`test-vectors/test-vectors.json`. The Puck is the standing exception: it runs
from a coin cell and AES-CCM costs it about 135 uA.

**The lamp is sealed, and that matters to anyone else reading it.**
It was reflashed with a firmware that has `crypto` (2v29.396, `MODULES` now
lists it), and `espruino/bench/revision-lamp.js` runs with the bindkey from
`test-vectors/test-vectors.json`, which is public on purpose. Its Home Assistant
entry holds the same key. So a receiver without that key sees an undecodable
BTHome device rather than a plain one: a silent lamp is a missing key before it
is a dead board. Putting it back in clear costs a rebuild and an upload (D-138).

**Two more nice!nanos arrived 2026-10-24**, `C2:38:F5:70:B6:BA` on `COM9` and
`E0:A4:BA:16:54:89` on `COM11`, both with `crypto` and both agreeing with the
seventeen shared CCM vectors. They are declared in `tools/devices.py` as `lamp2`
and `lamp3` and they exist for one purpose: to make the host run out of
connection slots, which three devices never could. **They are deliberately left
dark** until a run wants them, and their sketches live in RAM, so an unflashed
board is a silent one. They stay out of the §17 and §21 campaigns, whose figures
only compare with §16 and §20 on the bench as it was.

**A second proxy was added 2026-10-24**, `esp32-bluetooth-proxy-cff508` at
`10.191.52.200`, BLE MAC `1C:DB:D4:CF:F5:0A`, an ESP32-C3 with
`bluetooth_proxy: active: true`, so it offers connection slots and does not
merely listen. Its API has no password and no encryption, which is why it could
be added without a human at the keyboard. It is on Wi-Fi with a 29 to 41 ms
round trip, so anything routed through it pays that. The older proxy's ESPHome
entry `01M2QKAFXHKY07577VZ1PDZ8F2` stays disabled by campaign convention.

**The Puck.js is no longer on that rail.** Since 2026-10-09 it runs from a
CR2032 and is power-cycled by hand. `tools.ooty` still switches the rail, and
the rail still reads `ON`, so a silent Puck looks exactly like a dead one:
cycling the rail does nothing to it, and no amount of `ooty cycle` will bring
it back. Ask the owner to pull the cell. This cost an hour the first time. Home Assistant's configuration is reachable over SMB at
`\\haosjry.local\config` (the integration lives in `custom_components/`).

## The rule

## Anything that talks to Home Assistant needs two environment variables

`tools.regression`, `tools.chain_test`, `tools.ha_bench`, `tools.ha_probe` and
the latency sweeps read `HA_URL` and `HA_TOKEN` from the environment and fail
without them. No
document said so until 2026-10-05, which made every command block below look
like it would work from a clean shell.

```sh
export HA_URL=http://<your-home-assistant>:8123
export HA_TOKEN=<a long-lived access token>
```

The token is read from the environment and sent only to `HA_URL`; it is never
read from a file in the repository. On this bench both live in `.ha-env`, which
is gitignored -- `source .ha-env` before anything in this document.

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

## The ESP32 proxy is currently disabled, on purpose

As of 2026-10-01 the `Bluetooth Proxy 1f1020` config entry is **disabled** in
Home Assistant, and that is the state to leave it in.

An Espruino rebuilds its GATT table on every upload. The proxy relays against
the table it cached, so after a deployment it **acknowledges writes it never
delivers**: Home Assistant reports success, the device's `onWrite` never runs,
and nothing anywhere logs a failure (D-078 fault 2, reproduced and measured in
D-079). The cache lives on the ESP32, so disabling and re-enabling the entry
does not clear it -- only the proxy rebooting does.

This particular proxy exposes no restart button, no web server, and is not on
the switchable rail, so it cannot be rebooted remotely. Both bench devices are
in range of the Home Assistant host's own adapter and work without it.

**If you re-enable it:** reboot the ESP32 first, and expect every write to a
device you have reflashed since to vanish silently until you do.

## Reading the Home Assistant log on this installation

**`GET /api/error_log` returns 404 here, and nothing writes a log file to
`/config`.** Grepping either one returns nothing whether or not anything is
wrong, which is the worst possible failure for a diagnostic: a whole session's
worth of "no errors in the log" rested on a 404 (D-082).

Use the WebSocket command instead. It returns captured warnings and errors,
with tracebacks and occurrence counts:

```python
from tools.ha_bench import _ws
rows = await _ws(session, {"type": "system_log/list"})
for row in rows:
    print(row["level"], row["name"], row["count"], row["message"])
    print(row.get("exception"))
```

There is no `system_log/clear`; a restart empties it. The counts matter -- a
warning at `count: 312` is a loop, not an incident.

**And read the flow list sceptically.** `config_entries/flow/progress` shows
flows that are merely *open*, including ones a person left open hours ago. A
reauthentication flow sitting there is not evidence that anything just
happened; mistaking one for live evidence cost most of an afternoon.

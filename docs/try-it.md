# Try it: a Puck.js that measures what it was told to do

`bthome-writable` adds a **downlink** to BTHome. A device declares in its
ordinary BTHome advertising which of its objects are writable (object `0xFF`, a
1-byte positional bitmask, last in the service data). Home Assistant connects
briefly, writes the new values in BTHome's own format to one GATT
characteristic, and disconnects. **The refreshed advertising is the
confirmation** — there is no ack protocol.

Repo: <https://github.com/yerpj/bthome-writable> · protocol in
[`spec/PROTOCOL.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/PROTOCOL.md) · every resolved question, with the
measurement that resolved it, in [`spec/decisions.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/decisions.md).

## The test case, and why this one

The Puck advertises battery, illuminance, and a writable `light`. HA writes
`light` → green LED switches → **the Puck's own light sensor reads brighter**,
and that reading goes back out as illuminance in the same packet.

So the loop is closed by a measurement, not by an echo: a receiver sees that the
write had a *physical effect*, not merely that the device repeated the value
back. `Puck.light()` reads through the red LED, so the green one actuates and
the two never fight over the same part.

Observed end to end through HA: **~100 lux → ~590 lux in 1.7 s**, and back.

## Replicating it

Needs a Puck.js, Home Assistant with Bluetooth, and a host with Python +
`bleak`. ~10 minutes.

```bash
git clone https://github.com/yerpj/bthome-writable && cd bthome-writable
pip install bleak

# 1. Install the integration, then restart HA.
cp -r ha/custom_components/bthome_writable <config>/custom_components/

# 2. Install the sketch on the Puck. Modules go to Storage under their bare
#    names, the app to .bootcde, so it survives a power cut.
python -m tools.espruino_deploy --address <mac> --app espruino/examples/light-loop.js
```

3. HA discovers **BTHome Writable** within seconds. Add it, toggle the switch,
   watch the illuminance sensor.

Without HA, the same loop from a terminal — exit status 0 only if the measured
illuminance actually moved with the commanded state:
`python -m tools.closed_loop --address <mac>`.

## What I would value opinions on

1. **Write-only objects.** A text object for a screen can't be advertised back —
   too big for the 23-byte object budget — so it has no confirmation at all.
   Detecting "write-only" from the declaration alone is currently ambiguous.
2. **The declaration is positional**, so the packet-id object shifts every bit.
   Cheap on-device, but it means a layout change silently re-points every entity.
3. **MTU−3 is a hard ceiling** for a write; there is no long-write fallback.
   48 chars at MTU 53, ~18 at MTU 23.
4. **Provisional UUIDs** and an `illuminance` type missing from the Espruino
   `BTHome` module (this example goes through its `raw` escape hatch).

Details and the rest in [`spec/for-gordon.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/for-gordon.md).

## Two things that will look like faults but are not

- After any disconnection the device advertises at 100 ms for 30 s before
  falling back to its idle interval. That is `fastTimeout`, not a setting that
  failed to apply.
- The idle interval does **not** tax command latency — the device is in that
  fast mode during and after the connection. It sets the idle refresh rate and
  the cost of the *first* interaction after a quiet period. Measured at a
  deliberately slow 5 s interval, commands still landed in 1.7 s
  ([D-024](https://github.com/yerpj/bthome-writable/blob/main/spec/decisions.md)).

Status: draft. Nothing is frozen; UUIDs and wire formats freeze at first
release. Both test suites are green and the protocol has a shared test-vector
contract, but it has run on exactly one device, one HA install, and one
Bluetooth adapter — which is the reason for this post.

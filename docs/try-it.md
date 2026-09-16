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

# 1. Install the integration, then restart HA. (Or add the repo to HACS.)
cp -r custom_components/bthome_writable <config>/custom_components/

# 2. Install the sketch on the Puck. Modules go to Storage under their bare
#    names; the application runs from RAM and .bootcde is erased, so a power
#    cut undoes it. That is deliberate while you are experimenting -- an
#    advertising payload the radio refuses throws inside setup(), and a device
#    that is not advertising cannot be connected to, so it cannot be fixed over
#    the air (decisions.md D-029). Add --to-flash once you are happy with it.
python -m tools.espruino_deploy --address <mac> --app espruino/examples/light-loop.js
```

3. HA discovers **BTHome Writable** within seconds. Add it, toggle the switch,
   watch the illuminance sensor.

Without HA, the same loop from a terminal — exit status 0 only if the measured
illuminance actually moved with the commanded state:
`python -m tools.closed_loop --address <mac>`.

## What I would value opinions on

1. **Write-only objects** have no representation for *fixed-length* ones. A
   light that is off advertises `1E 00`, byte-identical to an "empty value"
   placeholder, so a receiver cannot tell a stateless trigger from an actuator
   that happens to be off.
2. **`0x3B command` has no no-op** — its `0x00` is `off`, a real command. Since
   a write carries every writable object, declaring it writable alongside
   anything else means that other thing cannot be written without also
   switching something off.
3. **The declaration is positional**, so the packet-id object shifts every bit.
   Cheap on-device, but a layout change silently re-points every entity.
4. **MTU−3 is a hard ceiling** for a write; there is no long-write fallback.
   48 chars at MTU 53, ~18 at MTU 23.

These four and the rest, each with the measurement behind it, in
[`spec/for-gordon.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/for-gordon.md).

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
contract, including AES-CCM vectors that pass on-device. But it has run on two
boards, one Home Assistant install and one Bluetooth adapter, all on the same
bench — which is the reason for this post.

To make your own device writable rather than replicate this one, start at
[`docs/espruino-quickstart.md`](https://github.com/yerpj/bthome-writable/blob/main/docs/espruino-quickstart.md),
then
[`docs/home-assistant-install.md`](https://github.com/yerpj/bthome-writable/blob/main/docs/home-assistant-install.md).

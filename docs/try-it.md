# Try it: a Puck.js that measures what it was told to do

`bthome-writable` adds a **downlink** to BTHome. A device lists in its ordinary
BTHome advertising which BTHome object types it accepts writes for (object
`0xFF`, the object IDs themselves, last in the service data). Home Assistant
connects briefly, writes one value in BTHome's own format to that entry's own
GATT characteristic, and disconnects. **The write response is the
acknowledgement**; there is no ack protocol, and writable values are not
advertised.

Repo: <https://github.com/yerpj/bthome-writable> · protocol in
[`spec/PROTOCOL.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/PROTOCOL.md) · every resolved question, with the
measurement that resolved it, in [`spec/decisions.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/decisions.md).

## The test case, and why this one

The Puck advertises battery, illuminance, and declares a writable `light`. HA
writes `light` → green LED switches → **the Puck's own light sensor reads
brighter**, and that reading goes back out as illuminance in the same packet.

So the loop is closed by a measurement, not by an echo: a receiver sees that the
write had a *physical effect*, not merely that the device repeated the value
back. That distinction is the point of version 2, where a written value is never
advertised at all. `Puck.light()` reads through the red LED, so the green one
actuates and the two never fight over the same part.

Measured on the bench: **~103 lux → ~595 lux and back**, the write itself
acknowledged 16 ms after the link is up, the link taking 1.7 s to establish from
a Windows host.

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

## What version 2 settled, and what is still open

Version 1 was a positional bitmask and a write-all payload: every write carried
every writable object, addressed by where it sat in the packet. Three of the four
questions that raised are gone with it.

- **One characteristic per entry.** Entry *k* is served at `2FAAkkkk-…`, and a
  write touches nothing else. Events are writable now: `0x3B command` has no
  no-op, which write-all made unusable.
- **The declaration lists object IDs**, not positions, so a sensor added to the
  packet no longer re-points every entity.
- **Writable values are not advertised.** A device whose values change by
  themselves — a knob, a button, a schedule — makes its characteristics readable
  and bumps BTHome's settings revision (`0x65`); a receiver reads them again when
  it changes, and on first sight. Everything else is shown as assumed state.

Still open, and worth an opinion:

1. **MTU−3 is a hard ceiling** for a write; there is no long-write fallback.
   48 characters of text at MTU 53, ~18 at MTU 23.
2. **A write-only value has nothing to read back.** That is by design — the
   device is the authority on whether it applied a write — but it means a lost
   write on a text display is invisible to the receiver.
3. **BTHome is asked for exactly one object ID**, `0xFF`. Everything else reuses
   BTHome's own object table, encodings and encryption.

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
release. All three test suites are green and the protocol has a shared
test-vector contract, including AES-CCM vectors that pass on-device. But it has
run on two boards, one Home Assistant install, one Bluetooth adapter and one
ESP32 proxy, all on the same bench — which is the reason for this post.

To make your own device writable rather than replicate this one, start at
[`docs/espruino-quickstart.md`](https://github.com/yerpj/bthome-writable/blob/main/docs/espruino-quickstart.md),
then
[`docs/home-assistant-install.md`](https://github.com/yerpj/bthome-writable/blob/main/docs/home-assistant-install.md).

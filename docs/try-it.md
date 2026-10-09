# Try it: a Puck.js that measures what it was told to do

`bthome-writable` adds a **downlink** to BTHome. A device lists in its ordinary
BTHome advertising which BTHome object types it accepts writes for (object
`0xFF`, the object IDs themselves, last in the service data). Home Assistant
connects briefly, writes one value in BTHome's own format to that entry's own
GATT characteristic, and disconnects. **The write response is the
acknowledgement**; there is no ack protocol, and writable values are not
advertised.

![What it needs, and what then happens on the air](https://raw.githubusercontent.com/yerpj/bthome-writable/main/docs/figures/try-it.png)

Repo: <https://github.com/yerpj/bthome-writable> · protocol in
[`spec/PROTOCOL.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/PROTOCOL.md) · every resolved question, with the
measurement that resolved it, in [`spec/decisions.md`](https://github.com/yerpj/bthome-writable/blob/main/spec/decisions.md).

## The test case, and why this one

The Puck advertises battery, illuminance, and declares a writable `light`. HA
writes `light` → green LED switches → **the Puck's own light sensor reads
brighter**, and that reading goes back out as illuminance in the same packet.

So the loop is closed by a measurement, not by an echo: a receiver sees that the
write had a *physical effect*, not merely that the device repeated the value
back. That distinction is the point: a written value is never advertised at
all. `Puck.light()` reads through the red LED, so the green one
actuates and the two never fight over the same part.

Measured on the bench, through Home Assistant: **~103 lux → ~595 lux and
back**, about 1.7 s from the service call to the LED at a one-second
advertising interval, of which the write itself is 36 ms.

**Put the Puck in the dark.** Cover it, or shut it in an opaque box — a mug
upside down on a desk will do. The sensor has no idea which light it is looking
at, so in a lit room the ambient level swamps the LED and the reading barely
moves: the loop still works and you cannot see that it does. The figures above
were taken under cover, which is why 103 lux is the *off* state rather than
office daylight.

## Replicating it

Needs a Puck.js, something opaque to put it under, and Home Assistant with
Bluetooth. ~10 minutes.

### 1. The integration

```bash
git clone https://github.com/yerpj/bthome-writable && cd bthome-writable
cp -r custom_components/bthome_writable <config>/custom_components/
```

Restart Home Assistant. (Or add the repo to HACS instead.)

### 2. The sketch, either way

**The module goes to the Puck's flash, the application runs from RAM.** That
split is deliberate: an advertising payload the radio refuses throws inside
`setup()`, and a device that is not advertising cannot be connected to, so it
cannot be fixed over the air. Running from RAM means a power cut undoes whatever
you just broke. Save it to flash once you are happy with
it, not before.

**A — with the tool in this repo.** Needs Python and `bleak`. On its first run
it also fetches the upstream `BTHome` module from espruino.com, caching it in
`.module-cache/`, so that run needs network. It does the whole
thing in one command, verifies each module's CRC after writing it, and erases
`.bootcde` so the application really is RAM-only.

```bash
pip install bleak
python -m tools.espruino_deploy --address <mac> --app espruino/examples/light-loop.js
# add --to-flash when you want it to survive a power cut
```

**B — with the Espruino Web IDE**, at <https://www.espruino.com/ide/>. Nothing
to install, and it is the tool Espruino users already have.

1. **Put the module in Storage.** Open the Web IDE's storage view, upload
   `espruino/BTHomeWritable.js` from this repo, and name the file
   **`BTHomeWritable`** — no extension. `require()` looks in Storage, so that
   bare name is what makes `require("BTHomeWritable")` resolve on the device.
   `require("BTHome")` needs nothing: the IDE fetches that one from
   espruino.com by itself.
2. **Send `espruino/examples/light-loop.js`** the ordinary way — paste it in the
   right-hand editor and click upload.

If the IDE says it cannot find `BTHomeWritable` rather than leaving the
`require` alone, it is trying to resolve the module online instead of trusting
Storage — Espruino's own documentation warns that it may. Two ways past it: drop
`BTHomeWritable.js` into your project's `modules/` folder, where the IDE will
inline it at upload; or paste `espruino/dist/light-loop-standalone.min.js`
instead, which is the same example with the module already inlined and needs no
step 1 at all. The minified one: its readable twin is 40 kB and a Puck.js has
neither the Storage nor the memory for it (`decisions.md` D-093).

### 3. In Home Assistant

It discovers **BTHome Writable** within seconds. Add it, toggle the switch,
watch the illuminance sensor — with the Puck under cover.

Without HA, the same loop from a terminal — exit status 0 only if the measured
illuminance actually moved with the commanded state:
`python -m tools.closed_loop --address <mac>` (Python and `bleak` again).

## What you are looking at

- **One characteristic per entry.** Entry *k* is served at `2FAAkkkk-…`, so a
  write touches that entry and nothing else on the device.
- **The declaration lists object IDs**, so adding a sensor to the packet does
  not disturb the writable entries.
- **Writable values are not advertised.** A device whose values can also change
  by themselves — a knob, a button — makes its characteristics readable and
  bumps BTHome's settings revision (`0x65`), and the receiver reads them again
  when that moves. Everything else is shown as assumed state.
- **BTHome is asked for exactly one object ID**, `0xFF`. Everything else reuses
  BTHome's own object table, encodings and encryption.

## Two things that will look like faults but are not

- After any disconnection the device advertises at 100 ms for 30 s before
  falling back to its idle interval. That is `fastTimeout`, not a setting that
  failed to apply.
- The idle interval costs you the *first* command after a quiet period, and
  nothing after it. At a deliberately slow 5 s interval that first one takes
  several seconds, because the receiver has to catch an advertisement before it
  can connect; once it has, the device is in fast mode and the commands that
  follow land in about a third of a second. So a slow interval looks broken for
  one press and then does not.

Status: draft — UUIDs and wire formats freeze at the first release, and
nothing is frozen yet. It has run on two boards, one Home Assistant install,
one Bluetooth adapter and one ESP32 proxy, **all on the same bench**, which is
the reason for this post: a second pair of hands is the thing it most needs.

To make your own device writable rather than replicate this one, start at
[`docs/espruino-quickstart.md`](https://github.com/yerpj/bthome-writable/blob/main/docs/espruino-quickstart.md),
then
[`docs/home-assistant-install.md`](https://github.com/yerpj/bthome-writable/blob/main/docs/home-assistant-install.md).

# T1.2 — hardware test procedure `[HW]`

The integration is complete and covered by 116 automated tests, but every one of
them runs against a fake radio and a fake GATT client. This is the part that
needs a real Espruino board, a real Home Assistant, and — for step 5 — a real
ESPHome Bluetooth proxy.

Run `espruino/HARDWARE-TEST.md` first. If the device does not behave there,
nothing here will make sense.

> **Steps 1 to 5 have been run on protocol version 2**, against Home Assistant
> 2026.7.4 on a Raspberry Pi 3 with a Puck.js — the integration deployed over the
> Samba add-on and driven through the REST API, the device reached through an
> ESP32 Bluetooth proxy. Results are recorded below each step and in
> `spec/decisions.md` D-049. Steps 6 and 7 need a hand on the hardware.

**Acceptance criteria (T1.2):** an end-to-end toggle from the Home Assistant UI,
both directly and through an ESPHome proxy; and a plain BTHome device is never
offered for setup.

## Install

1. Copy `custom_components/bthome_writable/` into your Home Assistant
   `config/custom_components/`.
2. Restart Home Assistant.
3. Install `espruino/examples/single-light.js` on the board so that it
   advertises on boot:

   ```
   python -m tools.espruino_deploy --address <mac>        --app espruino/examples/single-light.js
   ```

   This writes the modules to Storage and the application to `.bootcde` (D-023).
   `save()` would also survive a reset, but its memory image is restored
   *instead of* `.bootcde`, which then silently masks every later install.

## Step 1 — discovery, and the abort that matters

Within a few seconds of the board powering up, **Settings → Devices & Services**
should show a discovered **BTHome Writable** device.

Click **Configure**. The dialog should read, with your board's MAC:

> *… (A4:C1:38:…) accepts writes for 1 of its BTHome objects.*

Submit it.

**Now the important half.** If you own any ordinary BTHome device — a Shelly
BLU, an ATC-firmware thermometer, a plain Espruino BTHome beacon — confirm that
**it is not offered by this integration.** It should appear only under the core
BTHome integration, exactly as before.

This is the test that protects every existing BTHome user from a duplicate
discovery card, and it cannot be verified without a second, non-writable device.
If you have none to hand, say so in the report rather than skipping it silently.

> **Done, 2026-09-08, on a box with eight BTHome devices configured.** The
> integration's device list offered exactly one: the Puck.js carrying the
> declaration. Every plain BTHome device was filtered out, including one seen
> advertising at the time (`D5:83:51:F2:B2:3D`, service data
> `40 00 82 01 4B 02 70 12 5A 00 00 5A FB FF` — no `FF` declaration).
> Still worth a look in the UI to confirm no stray discovery card appears.

## Step 2 — one device card, not two

Open the new device. If the core BTHome integration also has this board (it
will, if you set it up there), you should see **one card** carrying both:

- the sensors core BTHome reads (battery, and the light as a *binary sensor*),
- and the **switch** this integration adds.

Two separate cards for the same MAC means the device merge failed — report the
MAC shown on each.

> **Done, 2026-09-08.** The switch landed on the existing device card rather
> than a new one: the entity came up as
> `switch.bureau_mobilesensf7b9_light`, inheriting both the device's name and
> its area from the registry entry that was already there.

## Step 3 — the toggle

Toggle the switch in the UI.

Expected: **the LED follows within a second**, and the toggle stays where you
put it. On a device that does not report state — most of them — the entity is
marked *assumed state*: it shows what Home Assistant last wrote.

Do it several times, both directions. The failure mode to watch for is a toggle
that **goes back on its own**: that is a write Home Assistant could not deliver,
and it leaves a row in the entity's logbook saying the command did not reach the
device.

> **Done, 2026-09-17 on version 2.** `switch.turn_on` returned in 0.3 s and the
> board reported `lamp.on === true`; the entity held its value. The LED itself
> is verified by the device's own light sensor rather than by eye — see step 3
> of the Espruino procedure.

## Step 4 — a write that does not land is not shown as applied

This distinguishes "it works" from "it looks like it works". Version 2 has no
confirming advertisement: what Home Assistant shows is what it last *delivered*,
so the thing to check is that an undelivered write changes nothing.

1. Power the board off (pull the battery, or hold reset).
2. Toggle the switch.

Expected: the entity **goes back** to its previous value within a few seconds,
and the entity's logbook carries a row:

```
... the command did not reach the device (...)
```

Then power the board back on and toggle again: it works, without re-adding
anything.

> **Covered by the test suite** against a fake link that drops mid-write, and
> by D-042/D-043 on hardware, where exactly this failure was silent in an
> earlier build. Still worth running by hand once.

## Step 5 — through an ESPHome proxy

Repeat step 3 with the board **out of range of the Home Assistant host's own
adapter** but in range of an ESPHome Bluetooth proxy.

This is the configuration most users will have, and the one most likely to
break: the proxy has a small number of connection slots, and the write needs
one.

Expected: the same behaviour, perhaps a second slower. Watch the ESPHome node's
log while toggling — you should see a connection open and close per write, not a
connection that stays up.

> **Done, 2026-09-17.** The Puck was reached through
> `esp32-bluetooth-proxy-1f1020`, which was the scanner that heard it throughout
> (Home Assistant's Bluetooth diagnostics name the source per device). Writes,
> reads and discovery all went through it, at the speeds recorded above.

## Step 5b — reading state back, on a device that reports it

Install `espruino/examples/button-light.js`. Its light entry has a `get`, so the
device advertises a settings revision and serves a readable characteristic.

1. Restart Home Assistant. The entity should come up with the board's **real**
   state, not `unknown`, and without the *assumed state* marking.
2. Press the board's button. Home Assistant should follow within a few seconds,
   without anyone writing anything.

> **Done, 2026-09-17.** The state was read on first sight after a restart; a
> local toggle at 17:23:47 showed in Home Assistant at 17:23:51. That second
> half found a real bug: a read that fails because something else holds the
> device's single connection used to count as done, leaving the state stale
> forever. It is now retried on a later advertisement (D-049).

## Step 6 — availability

Power the board off and leave it off.

Expected: the switch goes **unavailable** within the same timeout the core
BTHome sensors use. Power it back on: it returns.

## Step 7 — coexistence with the Espruino Web IDE

This one checks a rule we wrote into the design (§5 of the working document) and
have never exercised.

1. Connect to the board from the Espruino Web IDE over Web Bluetooth.
2. While that session is open, toggle the switch in Home Assistant.

Expected, in rough order of preference: the write succeeds; or it fails cleanly
and the entity reverts with a logged warning. What must **not** happen is the
IDE session dropping, or Home Assistant retrying in a loop.

Note exactly what you observe — this is new ground, and the answer shapes the
coexistence documentation.

## What to report back

- Whether a plain BTHome device was offered by this integration (step 1) — and
  which device you tested with, or that you had none.
- One card or two (step 2).
- Whether the toggle held (step 3).
- The exact logbook row from step 4.
- Whether step 5 worked, and how much slower it felt.
- What happened in step 7, in as much detail as you can.

Home Assistant's log with `custom_components.bthome_writable` at debug level is
worth attaching for anything that fails:

```yaml
logger:
  logs:
    custom_components.bthome_writable: debug
```

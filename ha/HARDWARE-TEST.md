# T1.2 — hardware test procedure `[HW]`

The integration is complete and covered by 57 automated tests, but every one of
them runs against a fake radio. This is the part that needs a real Espruino
board, a real Home Assistant, and — for the last section — a real ESPHome
Bluetooth proxy.

Run `espruino/HARDWARE-TEST.md` first. If the device does not behave there,
nothing here will make sense.

> **Steps 1 to 3 are already done**, against Home Assistant 2026.7.4 on a
> Raspberry Pi 3 with a Puck.js — the integration was deployed over the Samba
> add-on and driven through the REST API. Results are recorded below each step.
> Steps 4, 6 and 7 need a hand on the hardware; step 5 needs an ESPHome proxy
> powered up, and the three configured on that box were all offline.

**Acceptance criteria (T1.2):** an end-to-end toggle from the Home Assistant UI,
both directly and through an ESPHome proxy; and a plain BTHome device is never
offered for setup.

## Install

1. Copy `ha/custom_components/bthome_writable/` into your Home Assistant
   `config/custom_components/`.
2. Restart Home Assistant.
3. Flash the board with `espruino/examples/single-light.js` and `save()` it, so
   it advertises on boot.

## Step 1 — discovery, and the abort that matters

Within a few seconds of the board powering up, **Settings → Devices & Services**
should show a discovered **BTHome Writable** device.

Click **Configure**. The dialog should read, with your board's MAC:

> *… (A4:C1:38:…) declares 1 writable object(s).*

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
put it.

Do it several times, both directions. Then watch for the failure mode that
matters: a toggle that **flips back on its own** after a few seconds means the
device applied nothing, or its refreshed advertising never reached Home
Assistant. Note how long it takes to flip back.

> **Done, 2026-09-08 — and it found the bug this step was written for.** The
> first run bounced on every toggle: `on` at 0.5 s, `off` at 5.3 s, `on` again
> at 7.3 s. The write always worked; the confirmation window was being started
> when the value was queued rather than when the device had been told, so it
> expired before an answer was possible. Fixed (decisions.md D-010); three
> consecutive toggles now settle in under a second with no flip-back, and the
> device's advertising independently reads `1E 01`.
>
> The LED itself is verified too, by the device's own light sensor rather than
> by eye — see step 3 of the Espruino procedure. Four further toggles after the
> D-011 fix, each settling in under half a second with no spurious transition.

## Step 4 — the confirmation really comes from advertising

This distinguishes "it works" from "it looks like it works".

1. Toggle the switch on.
2. Immediately power the board off (pull the battery, or hold reset).

Expected: the toggle **reverts to its last advertised state** after a few
seconds, and `home-assistant.log` carries:

```
... did not advertise the written value within N.N s; reverting to its last advertised state
```

Then power the board back on. The entity should return with the state the board
actually has, not the one you asked for.

## Step 5 — through an ESPHome proxy

Repeat step 3 with the board **out of range of the Home Assistant host's own
adapter** but in range of an ESPHome Bluetooth proxy.

This is the configuration most users will have, and the one most likely to
break: the proxy has a small number of connection slots, and the write needs
one.

Expected: the same behaviour, perhaps a second slower. Watch the ESPHome node's
log while toggling — you should see a connection open and close per write, not a
connection that stays up.

> **Not done, 2026-09-08.** All three proxies configured on that box were
> unreachable (`Connect call failed` for each in the log), so every measurement
> above went through the Raspberry Pi's own adapter. This step is the one most
> likely to behave differently, because the write competes for a proxy's few
> connection slots — worth doing before anyone calls the MVP finished.

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
- Whether the toggle held, and any flip-back delay (step 3).
- The exact revert log line from step 4.
- Whether step 5 worked, and how much slower it felt.
- What happened in step 7, in as much detail as you can.

Home Assistant's log with `custom_components.bthome_writable` at debug level is
worth attaching for anything that fails:

```yaml
logger:
  logs:
    custom_components.bthome_writable: debug
```

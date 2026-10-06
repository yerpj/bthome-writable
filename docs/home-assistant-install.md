# Install it in Home Assistant

You need Home Assistant **2026.7 or newer** with Bluetooth working — an adapter on
the host, or an ESPHome Bluetooth proxy in range of your device. If the core
BTHome integration already shows your device's sensors, Bluetooth is working.

## Install through HACS

1. **HACS → ⋮ → Custom repositories.**
2. Repository: `https://github.com/yerpj/bthome-writable`. Type: **Integration**.
   Add.
3. Find **BTHome Writable** in the list, **Download**.
4. **Restart Home Assistant.** A custom integration is not loaded until you do.

<details>
<summary>Without HACS</summary>

Copy `custom_components/bthome_writable/` from this repository into your
`config/custom_components/` directory, and restart. That is all HACS does.

</details>

## Add your device

You should not have to. A device advertising a writable declaration is
discovered like any other Bluetooth device: **Settings → Devices & services**
shows a *BTHome Writable* card offering it. Click **Configure**, confirm, done.

If you dismissed the card, **Add integration → BTHome Writable** lists every
writable device Home Assistant has heard. There is still no address to type: a
device the list cannot show is one Home Assistant cannot hear, which no form
would fix.

If the device is encrypted you are asked for its 16-byte bindkey, and nothing
else. If you ever need to change it, use **Reconfigure** on the
device rather than removing it. Home Assistant cannot see what an encrypted device offers until it has the
key, which is why the question comes before the list of entities.

## What you get

**This integration adds controls only. Your sensors keep coming from the core
BTHome integration**, and you want both set up on the same device — that is the
design, not something that failed. Battery, temperature, illuminance and the
rest are ordinary BTHome objects that core BTHome already parses, and
reimplementing them here would be a second answer to a question Home Assistant
has already answered.

The new entities land on the **same device card** as those sensors, because
both integrations identify the device by its Bluetooth address. One card,
sensors and controls together — not a second device with half the story.

The seam shows in one place: an encrypted device needs its bindkey typed into
both integrations, with nothing linking them. That is inherent to being a
separate integration and is one of the arguments for merging this into core
BTHome rather than keeping it beside it.

Which entity you get depends on the BTHome object:

| Object | Entity |
| --- | --- |
| binary — `light`, `power`, `lock`, … | Switch |
| numeric — `temperature`, `brightness`, … | Number |
| `text` | Text |
| `button`, `dimmer`, and other events | One button per value |

The full table, and why the device decides rather than the receiver, is in
[`spec/PLATFORMS.md`](../spec/PLATFORMS.md).

## How a command behaves

Press the switch. Home Assistant connects, writes one BTHome object to that
entity's own characteristic, waits for the device's write response, and
disconnects. Nothing else on the device is touched. If the write does not land,
**the entity goes back** to the last value that did, and says why in the
logbook.

Expect about one to three seconds end to end on a healthy setup; the first
command after a quiet period costs more, because the device has to be caught
advertising before it can be connected to.

### Where the state comes from

A written value is not advertised, so most controls show **what Home Assistant
last wrote**, marked as assumed state — the device is the authority on whether
it applied it, and the write response is the evidence that it heard.

A device whose values can also change by themselves — a knob, a physical button,
a schedule — says so by advertising BTHome's *settings revision* (`0x65`) and
making its characteristics readable. Home Assistant then reads the real values
when it first sees the device, and again each time the revision changes. Those
entities are not assumed state: they show what the device said. If a read fails
because something else held the device's one connection, it is retried on a
later advertisement (D-049).

## Why 2026.7 and not older

This integration needs `bthome-ble` 3.22.1 or newer, because older versions do
not know BTHome's settings-revision object `0x65` — and a receiver that does not
know an object stops parsing there, taking the writability declaration behind it
with it.

Home Assistant's own `bthome` integration pins an exact `bthome-ble` version, and
on 2025.1 that pin is `==3.9.1`. **Two integrations with incompatible pins on one
instance fight**: each setup finds the other's version unsatisfactory and
reinstalls, every restart, and whichever module is on disk first is what both
then run against. This is not a theoretical conflict — it is exactly what the two
manifests say.

2026.7 is where we have measured the two coexisting. The oldest version that
works is probably older; nobody has established which, so the floor is the
evidence rather than a guess (`decisions.md` D-083).

## Unencrypted devices

You will get one warning per device, once:

> *`<device>` exposes 1 writable entry without encryption: any device in radio
> range can operate them. Set a bindkey on the device and reconfigure it here
> to seal both directions (PROTOCOL.md section 5)*

It means what it says. Without a bindkey the write characteristic is open to
anyone in range — which for an LED on your desk is fine, and for a lock is not.
Set a bindkey on the device and reconfigure it here to seal both directions.

## When something does not work

**The device is discovered but the flow says there is nothing writable.** It is
advertising BTHome without a declaration — an ordinary sensor. The core BTHome
integration handles it; this one deliberately does not offer it.

**A control stopped working and nothing is logged.** Check the logbook on the
entity: a failed write leaves a row there, saying the command did not reach the
device. The likeliest causes, in order:

- A stale GATT table after the device's code changed. It recovers by itself: the
  table is dropped and the next write rediscovers it.
- **An encrypted device that has restarted since Home Assistant last set up.**
  This one leaves *no* row in the logbook, because the device acknowledges the
  write before checking the counter and then discards it. A device must resume
  its counter strictly above anything it accepted, so a restart puts it ahead of
  Home Assistant with no way to say so. Home Assistant asks the device where it
  is when the device offers the counter report and Home Assistant is starting
  up — but a device that restarts while Home Assistant keeps running is not
  noticed. **Press *Resynchronise write counter* on the device, or reload it.**
- A device simply refusing the write, which it must do if the object ID or the
  length is not exactly what that entry expects.

**Home Assistant says it refuses to send an unencrypted write**, or that the
device is encrypted and no bindkey is configured. The two halves of the same
thing: the key Home Assistant holds and what the device is actually doing have
come apart, typically because the device was reflashed with a different sketch.
Home Assistant will not silently downgrade to plaintext, because that is what an
attacker would want it to do, and it will not send a plaintext write to a sealed
device, because the device would discard it without a word (D-042, D-079).

Home Assistant asks for the key on its own once two advertisements in a row
fail to decrypt — a notification saying the integration needs reconfiguring,
which is the same flow core `bthome` raises for the same reason. One failure is
not enough: a stray packet from a neighbour on the same address should not
raise anything.

You can also fix it without waiting, with **Settings → Devices & services →
the device → Reconfigure**: type
the key, or leave the field empty if the device no longer uses encryption. The
key is checked against the device's live advertising before it is accepted, so a
typo is caught there. Nothing else changes — the entities keep their names, and
so do the automations that use them.

**Writes fail with `out of connection slots` or `no longer reachable`.** Read
that message sceptically: it is assembled after a number of failed attempts and
describes the receiver, because the receiver is the only side it can see. Check
whether anything else is connected to the device — a phone, a laptop, an
Espruino IDE session. A BLE peripheral of this class accepts **one** central at a
time, and a desktop Bluetooth stack holds the link long after it has
disconnected. Power-cycling the device clears it in seconds; restarting Home
Assistant does not (D-043).

**Everything is slow and flaky.** If Home Assistant runs on a Raspberry Pi,
check for an under-voltage warning in Settings → Repairs before blaming
Bluetooth. A Pi at the edge of its power budget drops its radio and its network
in ways that look like anything but a power problem.

## Removing it

Delete the entry from **Settings → Devices & services**. It takes the bindkey
and the write counter with it, which is correct — and means that re-adding an
encrypted device asks for the key again.

To change only the key, use **Reconfigure** rather than removing the device:
deleting it discards every entity id, and so breaks every automation that names
one.

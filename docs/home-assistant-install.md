# Install it in Home Assistant

You need Home Assistant 2025.1 or newer with Bluetooth working — an adapter on
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
else. Home Assistant cannot see what an encrypted device offers until it has the
key, which is why the question comes before the list of entities.

## What you get

The new entities land on the **same device card** as the sensors the core BTHome
integration already created, because both identify the device by its Bluetooth
address. One card, sensors and controls together — not a second device with half
the story.

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

Press the switch. The entity shows the new value straight away, Home Assistant
connects, writes, disconnects, and waits for the device's next advertisement to
confirm. If the confirmation never comes, **the entity snaps back** to what the
device is actually advertising, and says why in the logbook.

That is the whole state model: the advertising is the truth, and an unconfirmed
command is not a command that worked. Expect about one to three seconds end to
end on a healthy setup; the first command after a quiet period costs more,
because the device has to be caught advertising before it can be connected to.

## Unencrypted devices

You will get one warning per device, once:

> *`<device>` exposes 1 writable object(s) without encryption: any device in
> radio range can operate them.*

It means what it says. Without a bindkey the write characteristic is open to
anyone in range — which for an LED on your desk is fine, and for a lock is not.
Set a bindkey on the device and reconfigure it here to seal both directions.

## When something does not work

**The device is discovered but the flow says there is nothing writable.** It is
advertising BTHome without a declaration — an ordinary sensor. The core BTHome
integration handles it; this one deliberately does not offer it.

**A control stopped working and nothing is logged.** Check the logbook on the
entity: a failed write leaves a row there. If it says the device did not confirm,
the likeliest causes in order are a stale GATT table after the device's code
changed (it recovers by itself on the next write), an encrypted device whose
counter has drifted (it resynchronises after two failures), and a device that is
simply refusing the write.

**Home Assistant says it refuses to send an unencrypted write.** You gave this
device a bindkey and it is now advertising in clear — typically because it was
reflashed with a different sketch. Home Assistant will not silently downgrade to
plaintext, because that is what an attacker would want it to do. Either reflash
the device with encryption enabled, or delete and re-add it here without a key
(D-042).

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

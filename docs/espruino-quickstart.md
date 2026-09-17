# Make your Espruino device writable

Fifteen minutes, an nRF52-class Espruino board (Puck.js, MDBT42Q, Bangle.js) and
a Chrome-based browser. At the end, Home Assistant has a switch that controls
your board, and you have not written a line of configuration anywhere.

If you only want to see it work before understanding it, start at step 1 and
stop after step 3.

## 1. Send the example to the board

Open the [Espruino Web IDE](https://www.espruino.com/ide/), connect to your
board, and paste the whole of
[`espruino/dist/single-light-standalone.js`](../espruino/dist/single-light-standalone.js)
into the right-hand pane. Send it.

That file is generated and self-contained: the `BTHomeWritable` module is
inlined into it, so there is nothing else to install. `require("BTHome")` is
resolved by the Web IDE from Espruino's own module library.

The console should answer with the board's address and which object types it is
offering writes for — `30` is `0x1E`, BTHome's `light`:

```
advertising as c8:80:32:ad:f7:b9 public
writable entries: [ 30 ]
```

**It runs from RAM.** A power cut undoes it, which is deliberate while you are
experimenting: an advertising payload the radio refuses throws inside `setup()`,
the radio stops to reconfigure and stays stopped, and a device that does not
advertise cannot be connected to — so it cannot be fixed over the air. That
cost a physical button press once (`spec/decisions.md`, D-029). When you are
happy with your sketch, `save()` it, or push it with
`python -m tools.espruino_deploy --address <mac> --app <file> --to-flash`.

## 2. Check it on the air

Any BLE scanner will do — nRF Connect on a phone, or from this repository:

```
python -m tools.bthome_write --address <mac> --payload 1e01
```

which writes `light = on` to entry 1's characteristic. You should see the LED
come on and the tool report the write acknowledged a few milliseconds after the
link is up. The light's state is not advertised: what proves the write arrived is
the device's own write response, and what proves it had an effect is the LED.

The advertisement looks like this:

```
40 00 01 01 5a ff 1e
│  │     │     │  └── entry 1: writes of light (0x1E) accepted, on 2FAA0001
│  │     │     └───── declaration (0xFF), last in the service data
│  │     └─────────── battery (0x01), 90 %
│  └───────────────── packet id (0x00)
└──────────────────── BTHome device information, unencrypted
```

Everything before `ff 1e` is ordinary BTHome that any receiver already
understands. `ff 1e` is the whole of this protocol on the air: object `0xFF`,
then one BTHome object ID per writable entry, last in the service data. A
receiver that does not know it skips it like any unknown object — which is why
it has to be last (D-005).

## 3. Add it to Home Assistant

See [`home-assistant-install.md`](home-assistant-install.md). The device
announces itself; there is nothing to type.

## 4. Now make it your own device

The example is thirty lines. The part that matters:

```js
var bw = require("BTHomeWritable");
var light = { on: false };

bw.setup({
  advertise: [
    { type: "battery", get: function () { return E.getBattery(); } },
    {
      type: "light",
      set: function (v) { light.on = v; digitalWrite(LED1, v); },
    },
  ],
  interval: 1000,
});
```

Each entry is one BTHome object.

- **`get` only** — an ordinary sensor, advertised exactly as the upstream
  `BTHome` module would advertise it.
- **`set` only** — a control: listed in the declaration, given a characteristic,
  and offered by Home Assistant as a switch, a number, a text box or a button
  depending on the object's type. Its value is never advertised, and Home
  Assistant shows what it last wrote, as assumed state.
- **`get` and `set`** — a control whose value can also change on the device
  itself: a knob, a button, a schedule. Its characteristic becomes readable, the
  device advertises BTHome's settings revision (`0x65`), and your code calls
  `bw.changed()` after a local change so receivers read it again.
  `espruino/examples/button-light.js` is the whole pattern in forty lines.

Reach for `get` and `set` only when something other than a receiver can change
the value. A light that only Home Assistant switches needs no readback: a
characteristic that is read on every restart costs a connection, and the device
is the authority either way.

`type` is a BTHome object name — `light`, `power`, `temperature`, `text`,
`button`… The mapping from object to Home Assistant platform is in
[`spec/PLATFORMS.md`](../spec/PLATFORMS.md).

`interval` is the advertising interval in milliseconds, 20 to 10000. It sets how
often the radio transmits, so it bounds how quickly a change becomes visible and
it is most of what the device spends its battery on. It does **not** set command
latency: after a connection the device advertises fast, so a command lands in
about the same time at 5000 ms as at 1000 ms (D-024). What a short interval buys
is the idle refresh rate and a cheaper first interaction after a quiet period.

Try values without reflashing:

```
python -m tools.set_adv_interval --address <mac> --ms 500
```

## 5. If you want encryption

Set `bindkey` to a 16-byte key and both directions are sealed with AES-CCM —
BTHome's own, not something invented here.

```js
bw.setup({
  advertise: [ /* … */ ],
  bindkey: "0123456789abcdef0123456789abcdef",
  interval: 1000,
});
```

Give Home Assistant the same key when it asks. Two warnings worth having up
front:

- **Your board's firmware needs AES.** Most official Espruino builds have it;
  some custom ones do not. `require("crypto").AES` tells you in one line.
- **Encryption costs advertising space.** The counter and the MIC take eight
  bytes, and this radio's real limit is lower than §2.3's arithmetic suggests
  (D-030). If `setup()` reports `advertising_rejected`, drop an object.

## Other examples

| File | What it shows |
| --- | --- |
| `single-light.js` | The minimum: one writable LED. |
| `light-loop.js` | The LED plus the board's own light sensor, so a receiver sees the write had a *physical* effect rather than an echo. |
| `three-lights.js` | Three objects sharing one BTHome ID, told apart by entry number. |
| `button-light.js` | A light the board's own button also switches: readable characteristic, settings revision, `bw.changed()`. |
| `encrypted-light.js` | The same, sealed with a bindkey. |
| `oled-text.js` | A writable `text` object driving an SSD1306. |

Each has a self-contained build under `espruino/dist/`.

## When something does not work

**The console prints `write rejected:` with a code.** The device refused the
whole write, which is what §4.2 requires: a write must carry exactly the entry's
object ID and exactly its length, or be rejected entirely. The usual cause is a
receiver holding a stale picture of the device after you changed the sketch; its
next advertisement, and a dropped GATT cache, fix it.

**Nothing advertises at all after sending your own sketch.** Almost always an
exception inside `setup()`. Reconnect with the Web IDE and read the console.
Because the sketch is in RAM, a power cycle also clears it.

**A syntax error in the module, from a line that is plainly fine.** On a
Puck.js that reads "Got UNFINISHED TEMPLATE LITERAL": it is an out-of-memory
message in disguise. Sending sketch after sketch without `reset()` leaves every
previous one's globals and listeners in RAM (D-049). `reset()` first;
`espruino_deploy` now does.

**Home Assistant cannot write, but your own tools can.** Do not conclude the
device is healthy. An Espruino accepts one central at a time, and a desktop
Bluetooth stack often holds the link long after it has disconnected — so your
own scanner can be the thing locking Home Assistant out. Power-cycle the board
before suspecting anything else (D-043).

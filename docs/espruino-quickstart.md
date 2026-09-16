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

The console should answer with the board's address and which positions it is
offering:

```
advertising as c8:80:32:ad:f7:b9 public
writable positions: [ 2 ]
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

which writes `light = on` and waits for the device to say so. You should see the
LED come on and the tool report a confirmation in well under a second.

The advertisement looks like this:

```
40 00 0c 01 64 1e 00 ff 04
│  │     │     │     └── declaration: bitmask 0b00000100 → position 2
│  │     │     └──────── light (0x1E), currently off
│  │     └────────────── battery (0x01), 100 %
│  └──────────────────── packet id (0x00) — always position 0
└─────────────────────── BTHome device information, unencrypted
```

Everything before `ff 04` is ordinary BTHome that any receiver already
understands. `ff 04` is the whole of this protocol on the air: object `0xFF`,
one byte of bitmask, last in the service data. A receiver that does not know it
skips it like any unknown object.

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
      get: function () { return light.on; },
      set: function (v) { light.on = v; digitalWrite(LED1, v); },
    },
  ],
  interval: 1000,
});
```

Each entry is one BTHome object, in packet order.

- **`get` only** — an ordinary sensor. Read-only, exactly as the upstream
  `BTHome` module would advertise it.
- **`get` and `set`** — a control. It is advertised *and* declared writable, and
  Home Assistant offers it as a switch, a number, or text depending on the
  object's type.
- **`set` only** — a control with no state to report: a button, a command, a
  trigger. It is declared writable and Home Assistant never waits for a
  confirmation it cannot get.

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
| `three-lights.js` | Three objects sharing one BTHome ID, addressed by position. |
| `encrypted-light.js` | The same, sealed with a bindkey. |
| `oled-text.js` | A writable `text` object driving an SSD1306. |

Each has a self-contained build under `espruino/dist/`.

## When something does not work

**The console prints `write rejected:` with a code.** The device refused the
whole write, which is what §4.2 requires: a write must match the declared layout
exactly or be rejected entirely. The usual cause is a receiver holding a stale
picture of the device after you changed the sketch. Its next advertisement fixes
it.

**Nothing advertises at all after sending your own sketch.** Almost always an
exception inside `setup()`. Reconnect with the Web IDE and read the console.
Because the sketch is in RAM, a power cycle also clears it.

**Home Assistant cannot write, but your own tools can.** Do not conclude the
device is healthy. An Espruino accepts one central at a time, and a desktop
Bluetooth stack often holds the link long after it has disconnected — so your
own scanner can be the thing locking Home Assistant out. Power-cycle the board
before suspecting anything else (D-043).

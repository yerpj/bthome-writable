/* bthome-writable — a screen that shows what Home Assistant sends it.
 *
 * This is the use case the project started from: put a Home Assistant sensor
 * value on a display attached to a BLE device, without the device polling
 * anything or the user writing any configuration.
 *
 * An SSD1306 over I2C on a nice!nano. The text entry has a `set` and no `get`:
 * nothing but a write changes the screen, so there is nothing for a receiver to
 * read back and no settings revision to advertise (PROTOCOL.md §3.1). The text
 * is never advertised, which also keeps what is on someone's screen off the air.
 *
 * Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/oled-text.js
 */

var bw = require("BTHomeWritable");

var DISPVCC = D45;
var DISPGND = D47;
var DISPSDA = D29;
var DISPSCL = D2;

var g;
// What the screen is showing. A global on purpose: a host can read it back over
// the console to check what actually arrived.
var shown = "";

/* Draw `text`, wrapping it across the 128x64 panel rather than running off the
 * edge -- a sensor reading arrives with its label and is rarely one short
 * word. */
function show(text) {
  shown = text;
  g.clear();
  g.setFontVector(14);
  var line = "";
  var y = 2;
  var words = text.split(" ");
  for (var i = 0; i < words.length; i++) {
    var candidate = line ? line + " " + words[i] : words[i];
    if (g.stringWidth(candidate) > 126 && line) {
      g.drawString(line, 0, y);
      y += 16;
      line = words[i];
    } else {
      line = candidate;
    }
  }
  if (line) g.drawString(line, 0, y);
  g.flip();
  console.log("SHOWN[" + shown.length + "]: " + shown);
}

function start() {
  bw.setup({
    advertise: [
      // The nice!nano has no battery sense -- E.getBattery() is a Puck.js
      // function -- so the device reports the nRF52's own die temperature.
      { type: "temperature", interval: 30000, get: function () { return E.getTemperature(); } },
      { type: "text", set: show },
    ],
    interval: 1000,
    // A nice!nano advertising its default "Espruino b216" measured 7 bytes of
    // service data with the name, 22 without, on 2v29.242 (D-046). This packet
    // needs 8. The device is still discovered: Home Assistant matches on the
    // BTHome service data, not on a name.
    showName: false,
    onError: function (error) {
      console.log("write rejected:", error.code, error.message);
    },
  });

  show("ready");
  console.log("advertising as", NRF.getAddress());
  console.log("writable entries:", bw.plan().entryIds);
  console.log("service data bytes:", bw.plan().serviceDataLength);
}

// The panel is powered from two GPIOs rather than the rail, so it has to be
// turned on before the bus is of any use.
DISPVCC.set();
DISPGND.reset();

var i2c = new I2C();
i2c.setup({ sda: DISPSDA, scl: DISPSCL, bitrate: 800000 });
g = require("SSD1306").connect(i2c, start, { height: 64, width: 128 });

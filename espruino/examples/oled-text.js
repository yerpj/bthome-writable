/* bthome-writable — a screen that shows what Home Assistant sends it.
 *
 * This is the use case the project started from: put a Home Assistant sensor
 * value on a display attached to a BLE device, without the device polling
 * anything or the user writing any configuration.
 *
 * An SSD1306 over I2C on a nice!nano. The text object is **write-only** — it
 * has a `set` and no `get`, which is all the module needs to work that out
 * (PROTOCOL.md §3). It is advertised as a zero-length placeholder, never as
 * content, for two reasons: a screen's worth of text does not fit in an
 * advertising packet, and what is on someone's screen is not necessarily
 * everyone's business.
 *
 * The consequence is worth stating plainly: **a write-only object has no
 * confirmation.** §6's model — the refreshed advertising is the proof — cannot
 * apply to a value the device never advertises. If a write is lost, nothing
 * says so. The temperature object below is there partly so the device still has
 * something to say for itself.
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
// What the screen is showing. A global on purpose: it is how a host can read
// back what actually arrived, which for an object with no confirmation is the
// only way to tell an applied write from one that vanished.
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
      // function -- so the device reports the nRF52's own die temperature
      // instead. Something to say for itself, since the text it is sent can
      // never be confirmed.
      { type: "temperature", interval: 30000, get: function () { return E.getTemperature(); } },
      // `set` and no `get`: write-only, so it advertises an empty placeholder.
      { type: "text", set: show },
    ],
    interval: 1000,
    onError: function (error) {
      console.log("write rejected:", error.code, error.message);
    },
  });

  show("ready");
  console.log("advertising as", NRF.getAddress());
  console.log("writable positions:", bw.plan().writablePositions);
  console.log("service data bytes:", bw.plan().serviceDataLength);
}

// The panel is powered from two GPIOs rather than the rail, so it has to be
// turned on before the bus is of any use.
DISPVCC.set();
DISPGND.reset();

var i2c = new I2C();
i2c.setup({ sda: DISPSDA, scl: DISPSCL, bitrate: 800000 });
g = require("SSD1306").connect(i2c, start, { height: 64, width: 128 });

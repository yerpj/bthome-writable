/* bthome-writable — a device that displays text pushed from Home Assistant.
 *
 * The use case: show a Home Assistant sensor value on a screen attached to an
 * Espruino device. The text entry is written by Home Assistant and shown by the
 * device; like every writable value it is never advertised (PROTOCOL.md §2.3),
 * which suits text anyway -- a screen's worth does not fit in advertising.
 *
 * The write response tells Home Assistant the text was delivered; showing it is
 * this code's job. On Espruino a write is acknowledged before `show` runs, so a
 * rejected write still looks delivered to the receiver -- `onError` below is
 * where that shows.
 *
 * This example has no screen: it stores the text and prints it, so a host can
 * read back what actually arrived and measure what gets through. Swap `show`
 * for `g.clear(); g.drawString(text, 0, 0); g.flip();` on a Bangle.js.
 */

var bw = require("BTHomeWritable");

// What the display is currently showing. Exposed as a global on purpose: the
// measurement in tools/text_limits.py reads it back over the console.
var shown = "";

function show(text) {
  shown = text;
  console.log("SHOWN[" + shown.length + "]: " + shown);
}

bw.setup({
  advertise: [
    { type: "battery", get: function () { return E.getBattery(); } },
    { type: "text", set: show },
  ],
  interval: 2000,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

console.log("advertising as", NRF.getAddress());
console.log("writable entries:", bw.plan().entryIds);

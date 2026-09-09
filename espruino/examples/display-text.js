/* bthome-writable — a device that displays text pushed from Home Assistant.
 *
 * The use case: show a Home Assistant sensor value on a screen attached to an
 * Espruino device. The text is a *write-only* object (PROTOCOL.md §3): Home
 * Assistant writes it, the device shows it, and the device never advertises it
 * back — a screen's worth of text does not fit in an advertising packet, and
 * §2.3's budget is 23 bytes for everything.
 *
 * That has a consequence worth understanding before building on it: **a
 * write-only object has no confirmation**. Section 6's model — the device's
 * refreshed advertising is the proof — cannot apply to a value the device never
 * advertises. If the write is lost, nothing says so.
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
  // Printed from `shown` rather than `text`: this line is how a host reads back
  // what actually arrived, which without a screen is the only way to tell a
  // write that was applied from one that vanished. A write-only object has no
  // confirmation to offer (§3).
  console.log("SHOWN[" + shown.length + "]: " + shown);
}

bw.setup({
  advertise: [
    { type: "battery", get: function () { return E.getBattery(); } },
    // Write-only: advertised as a zero-length placeholder, never as content.
    { type: "text", writeOnly: true, set: show },
  ],
  interval: 2000,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

console.log("advertising as", NRF.getAddress());
console.log("writable positions:", bw.plan().writablePositions);
console.log("writable object count:", bw.plan().layout.length);

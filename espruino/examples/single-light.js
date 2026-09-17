/* bthome-writable — the minimal device: one LED, writable from Home Assistant.
 *
 * Flash this onto an nRF52-class Espruino board (Puck.js, MDBT42Q, Bangle.js)
 * with the Web IDE. See ../HARDWARE-TEST.md for the test procedure.
 */

var bw = require("BTHomeWritable");

var light = { on: false };

function apply() {
  // LED1 exists on every Espruino nRF52 board; swap for a real output pin.
  digitalWrite(LED1, light.on);
}

bw.setup({
  advertise: [
    { type: "battery", get: function () { return E.getBattery(); } },
    // `set` makes it writable: listed in the declaration, served on
    // characteristic 2FAA0001. Its state is not advertised (PROTOCOL.md §2.3),
    // and nothing but a write changes it, so it needs no `get` either.
    {
      type: "light",
      set: function (v) {
        light.on = v;
        apply();
      },
    },
  ],
  interval: 1000,
  onError: function (error) {
    // Espruino acknowledges a write before this code runs, so a rejected write
    // looks delivered to the receiver. This is the only place it shows.
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable entries:", bw.plan().entryIds);

/* bthome-writable — the minimal device: one LED, writable from Home Assistant.
 *
 * Flash this onto an nRF52-class Espruino board (Puck.js, MDBT42Q, Bangle.js)
 * with the Web IDE. See ../HARDWARE-TEST.md for the T1.1 test procedure.
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
    {
      type: "light",
      get: function () { return light.on; },
      set: function (v) {
        light.on = v;
        apply();
      },
    },
  ],
  interval: 1000,
  onError: function (error) {
    // Writes are rejected silently on the wire (there is no ack channel), so
    // this is the only place a desync becomes visible during bring-up.
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable positions:", bw.plan().writablePositions);

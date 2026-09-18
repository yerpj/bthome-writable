/* bthome-writable — light-loop with the LED disconnected, for one experiment.
 *
 * Identical to light-loop.js in everything a receiver can see: the same three
 * entries, the same intervals, the same writable light on characteristic
 * 2FAA0001. The one difference is that applying a write drives no pin.
 *
 * It exists to answer a single question. On a Puck.js running the real
 * light-loop, 13 of 125 writes stalled for more than five seconds inside the
 * write call, several within milliseconds of 16.1 s, while a mains-powered
 * nice!nano did that 0 times in 124 (decisions.md D-052). A coin cell has a high
 * internal resistance, an LED draws a few milliamps, and the radio transmits
 * from the same rail: if the stalls are the battery sagging rather than anything
 * in the protocol, they should disappear here and nowhere else.
 *
 * Nothing else changes, deliberately. The illuminance object is still read on
 * every packet -- it simply stops moving, since nothing lights the sensor.
 *
 * Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/light-loop-no-led.js
 */

var bw = require("BTHomeWritable");

var lamp = { on: false };

// The whole experiment: the state is kept, the pin is not driven.
function apply() {}

function illuminance() {
  var value = Math.round(Puck.light() * 1000 * 100);
  if (value < 0) value = 0;
  if (value > 0xffffff) value = 0xffffff;
  return [0x05, value & 255, (value >> 8) & 255, (value >> 16) & 255];
}

bw.setup({
  advertise: [
    { type: "battery", interval: 300000, get: function () { return E.getBattery(); } },
    { type: "raw", interval: 0, get: illuminance },
    {
      type: "light",
      set: function (v) {
        lamp.on = v;
        apply();
      },
    },
  ],
  interval: 1000,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable entries:", bw.plan().entryIds);
console.log("battery:", E.getBattery(), "%  (no LED is driven in this build)");

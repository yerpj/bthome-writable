/* bthome-writable — a Puck.js that measures what it was told to do.
 *
 * Home Assistant writes to the light entry, which switches the green LED; the
 * Puck's light sensor then reads brighter, and that reading goes out in the
 * advertising as an illuminance object. The light's own state is never
 * advertised (PROTOCOL.md §2.3) -- but a receiver can still see, without anyone
 * watching the device, that the write produced a physical effect.
 *
 * Puck.light() reads through the red LED, so the green one is the actuator and
 * the two never fight over the same part.
 *
 * See ../HARDWARE-TEST.md. Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/light-loop.js
 */

var bw = require("BTHomeWritable");

var lamp = { on: false };

function apply() {
  // LED2 is green. LED1 (red) is the sensor, LED3 (blue) is left alone.
  digitalWrite(LED2, lamp.on);
}

/* BTHome illuminance, object 0x05: unsigned 24-bit, 0.01 lux per step.
 *
 * The published BTHome module has no `illuminance` type yet (it is in
 * EspruinoDocs master), so this goes through its `raw` escape hatch, which
 * emits the bytes it is given verbatim -- object ID included.
 *
 * Puck.light() returns 0..1 and is not calibrated in lux, so the scale below
 * is arbitrary. What matters is that the number moves when the green LED does. */
function illuminance() {
  var value = Math.round(Puck.light() * 1000 * 100);
  if (value < 0) value = 0;
  if (value > 0xffffff) value = 0xffffff;
  return [0x05, value & 255, (value >> 8) & 255, (value >> 16) & 255];
}

bw.setup({
  advertise: [
    // The battery does not move in a minute, and reading it is not free.
    { type: "battery", interval: 300000, get: function () { return E.getBattery(); } },
    // interval 0 -- read on every packet, so the effect of a write shows up in
    // the next advertisement rather than one read-interval later.
    { type: "raw", interval: 0, get: illuminance },
    {
      type: "light",
      set: function (v) {
        lamp.on = v;
        apply();
      },
    },
  ],
  // The BTHome advertising interval: how often the radio transmits, and so the
  // idle refresh rate of the illuminance, and the cost of the first command
  // after a quiet period. It does not set command latency: the device advertises
  // fast during and after a connection, and a command landed in 1.7 s with this
  // at 5000 (D-024). 20 to 10000 ms. Try values live, without reflashing:
  //   python -m tools.set_adv_interval --address <mac> --ms 500
  interval: 1000,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable entries:", bw.plan().entryIds);
console.log("light now:", Puck.light());

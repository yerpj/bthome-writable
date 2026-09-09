/* bthome-writable — a Puck.js that measures what it was told to do.
 *
 * The point of this example is that it closes the loop. Home Assistant writes
 * to the light object, which switches the green LED; the Puck's light sensor
 * then reads brighter, and that reading goes back out in the same advertising
 * packet as an illuminance object. So a receiver can see, without anyone
 * watching the device, that the write produced a physical effect — not merely
 * that the device echoed the value back.
 *
 * Puck.light() reads through the red LED, so the green one is the actuator and
 * the two never fight over the same part.
 *
 * See ../HARDWARE-TEST.md. Flash with:
 *   python -m tools.espruino_upload --address <mac> \
 *       espruino/dist/light-loop-standalone.min.js
 */

var bw = require("BTHomeWritable");

var lamp = { on: false };

function apply() {
  // LED2 is green. LED1 (red) is the sensor, LED3 (blue) is left alone.
  digitalWrite(LED2, lamp.on);
}

/* BTHome illuminance, object 0x05: unsigned 24-bit, 0.01 lux per step.
 *
 * The upstream BTHome module has no `illuminance` type, so this goes through
 * its `raw` escape hatch, which emits the bytes it is given verbatim — object
 * ID included. Adding the type upstream would be better; see
 * spec/for-gordon.md.
 *
 * Puck.light() returns 0..1 and is not calibrated in lux, so the scale below
 * is arbitrary. It does not need to be right: what matters is that the number
 * moves when the green LED does. */
function illuminance() {
  var value = Math.round(Puck.light() * 1000 * 100);
  if (value < 0) value = 0;
  if (value > 0xffffff) value = 0xffffff;
  return [0x05, value & 255, (value >> 8) & 255, (value >> 16) & 255];
}

bw.setup({
  advertise: [
    { type: "battery", get: function () { return E.getBattery(); } },
    { type: "raw", get: illuminance },
    {
      type: "light",
      get: function () { return lamp.on; },
      set: function (v) {
        lamp.on = v;
        apply();
      },
    },
  ],
  // A battery-sane idle rate. The module advertises much faster than this from
  // the moment a receiver connects until a while after it leaves, so a burst of
  // commands does not pay the idle interval more than once (decisions.md
  // D-013, D-014).
  interval: 2000,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable positions:", bw.plan().writablePositions);
console.log("light now:", Puck.light());

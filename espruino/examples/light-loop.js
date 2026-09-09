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
    // The battery does not move in a minute, and reading it is not free.
    { type: "battery", interval: 300000, get: function () { return E.getBattery(); } },
    // interval 0 -- read on every packet build, including the extra one that
    // follows a write. That is a choice this example makes because its whole
    // point is that the measurement follows the command, and Puck.light() is
    // cheap. It is not a rule: omit the interval and the sensor follows the
    // advertising interval instead, so a write's confirmation would carry the
    // previous reading and the new one would arrive a packet later. A sensor
    // that takes tens of seconds to read wants a long interval, not this.
    { type: "raw", interval: 0, get: illuminance },
    {
      type: "light",
      get: function () { return lamp.on; },
      set: function (v) {
        lamp.on = v;
        apply();
      },
    },
  ],
  // The BTHome advertising interval: how often the radio transmits, and so
  // the fastest Home Assistant can see anything change. Each entry above may
  // be read less often than this, never more.
  //
  // It also decides how long a receiver waits before it can begin a
  // connection, so it sets the latency of the first command of a burst -- and
  // it is what the device spends its battery on while nothing is happening.
  // 20 to 10000 ms.
  //
  // Try other values live, without reflashing:
  //   python -m tools.set_adv_interval --address <mac> --ms 500
  //
  // 1000 for a device you interact with. Measuring this at 5000 (D-024) showed
  // the interval does not tax the latency of a command -- the device is in fast
  // advertising during and after the connection -- so what a shorter interval
  // actually buys is the idle refresh rate and a cheaper first interaction
  // after a quiet period, which is where the cliff is (D-021).
  interval: 1000,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable positions:", bw.plan().writablePositions);
console.log("light now:", Puck.light());

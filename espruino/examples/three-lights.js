/* bthome-writable — three lights, and nothing but their position to tell them
 * apart.
 *
 * This is the claim of PROTOCOL.md §2.1 put on hardware. The device advertises
 * three `light` objects with the same object ID (`0x1E`). BTHome has no
 * per-instance identifier and this protocol invents none: what addresses the
 * second light is that it is *second in the packet*, and the declaration's
 * bitmask names positions rather than IDs.
 *
 * A write carries all three (§4.2, write-all in packet order), so the receiver
 * resends the two it is not changing. If positional addressing were wrong — if
 * the module sorted unstably, or the receiver counted from the wrong place —
 * the symptom would not be an error. It would be the wrong light switching,
 * which is why this is worth running rather than only unit-testing.
 *
 * Two of the three drive real LEDs, so a person in the room can see which one
 * moved. LED1 is left alone: `Puck.light()` reads through it, and an actuator
 * sharing a part with the sensor would make the test lie.
 *
 * Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/three-lights.js
 * Then:
 *   python -m tools.multi_instance --address <mac>
 */

var bw = require("BTHomeWritable");

// The third has no LED to drive: a Puck.js has three and one is the sensor.
// It is still a full participant in the packet, which is the point -- its
// position has to keep working with nothing physical behind it.
var lamps = [
  { on: false, pin: LED2 },
  { on: false, pin: LED3 },
  { on: false, pin: undefined },
];

function apply() {
  for (var i = 0; i < lamps.length; i++) {
    if (lamps[i].pin !== undefined) digitalWrite(lamps[i].pin, lamps[i].on);
  }
}

function entry(index) {
  return {
    type: "light",
    get: function () { return lamps[index].on; },
    set: function (v) {
      lamps[index].on = v;
      apply();
    },
  };
}

bw.setup({
  advertise: [
    { type: "battery", interval: 300000, get: function () { return E.getBattery(); } },
    entry(0),
    entry(1),
    entry(2),
  ],
  interval: 1000,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable positions:", bw.plan().writablePositions);
console.log("service data bytes:", bw.plan().serviceDataLength, "of", bw.plan().budget);

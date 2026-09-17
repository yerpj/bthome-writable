/* bthome-writable — three lights of one type, told apart by entry number.
 *
 * The declaration lists `0x1E` three times (PROTOCOL.md §2.1). BTHome has no
 * per-instance identifier and this protocol invents none: the second light is
 * entry 2, served on characteristic 2FAA0002, and a write to it touches nothing
 * else (§4.2).
 *
 * If the numbering were wrong the symptom would not be an error. It would be
 * the wrong light switching, which is why this is worth running on hardware
 * rather than only unit-testing.
 *
 * Two of the three drive real LEDs, so a person in the room can see which one
 * moved. LED1 is left alone: `Puck.light()` reads through it.
 *
 * Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/three-lights.js
 * Then:
 *   python -m tools.multi_instance --address <mac>
 */

var bw = require("BTHomeWritable");

// The third has no LED to drive: a Puck.js has three and one is the sensor. It
// still gets its entry and its characteristic, which is the point -- its number
// has to keep working with nothing physical behind it.
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
console.log("writable entries:", bw.plan().entryIds);
console.log("service data bytes:", bw.plan().serviceDataLength, "of", bw.plan().budget);

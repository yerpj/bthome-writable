/* bthome-writable — the light-loop device, encrypted.
 *
 * Same closed loop as light-loop.js: Home Assistant writes the light object,
 * the green LED switches, and the Puck's own light sensor reads brighter in the
 * next packet. The difference is that everything is sealed with BTHome v2's
 * AES-CCM (PROTOCOL.md §5), in both directions.
 *
 * Two consequences worth knowing before copying this:
 *
 * **There is much less room than the arithmetic suggests.** PROTOCOL.md §2.3
 * computes 24 bytes of service data; a Puck.js measured with tools/adv_budget.py
 * accepts 17, or 20 with `showName:false` (decisions.md D-030). Encryption then
 * spends 8 of those on the counter and MIC, leaving 11 for objects. That is why
 * this example drops the battery reading that light-loop.js carries: with it,
 * the packet is one byte over and the radio refuses it.
 *
 * **The key is the device's identity.** A receiver that does not have it sees
 * an undecodable BTHome device, not a plain one. The bindkey below is the one
 * from test-vectors.json, which is published — change it before using this for
 * anything real.
 *
 * Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/encrypted-light.js
 */

var bw = require("BTHomeWritable");

var lamp = { on: false };

function apply() {
  digitalWrite(LED2, lamp.on); // green; LED1 (red) is the sensor
}

/* BTHome illuminance, object 0x05: unsigned 24-bit, 0.01 lux per step. Through
 * the upstream module's `raw` escape hatch until its illuminance type is
 * published (spec/for-gordon.md §8). */
function illuminance() {
  var value = Math.round(Puck.light() * 1000 * 100);
  if (value < 0) value = 0;
  if (value > 0xffffff) value = 0xffffff;
  return [0x05, value & 255, (value >> 8) & 255, (value >> 16) & 255];
}

bw.setup({
  advertise: [
    // No battery object here: 11 bytes is what an encrypted packet has, and
    // packet id (2) + illuminance (4) + light (2) + declaration (2) is 10.
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
  interval: 1000,
  // Measured on this board, not assumed: see the header.
  maxServiceData: 20,
  showName: false,
  // From test-vectors.json, and therefore public. Change it.
  bindkey: "231d39c1d7cc1ab1aee224cd096db932",
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable positions:", bw.plan().writablePositions);
console.log("service data bytes:", bw.plan().serviceDataLength, "of", bw.plan().budget);

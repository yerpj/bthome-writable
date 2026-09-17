/* bthome-writable — the light-loop device, encrypted.
 *
 * Same closed loop as light-loop.js: Home Assistant writes the light entry, the
 * green LED switches, and the Puck's own light sensor reads brighter in the
 * next packet. The difference is that everything is sealed with BTHome v2's
 * AES-CCM (PROTOCOL.md §5): advertising, and the writes.
 *
 * Two consequences worth knowing before copying this:
 *
 * **There is much less room than the arithmetic suggests.** A Puck.js accepts
 * 17 bytes of service data, or 20 with `showName:false` (decisions.md D-030).
 * Encryption spends 8 of them on the counter and MIC. That is why this example
 * carries no battery reading.
 *
 * **The key is the device's identity.** A receiver that does not have it sees
 * an undecodable BTHome device, not a plain one. The bindkey below is the one
 * from test-vectors.json, which is published -- change it before using this
 * for anything real.
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

/* BTHome illuminance, object 0x05: unsigned 24-bit, 0.01 lux per step, through
 * the upstream module's `raw` escape hatch until its illuminance type is
 * published. */
function illuminance() {
  var value = Math.round(Puck.light() * 1000 * 100);
  if (value < 0) value = 0;
  if (value > 0xffffff) value = 0xffffff;
  return [0x05, value & 255, (value >> 8) & 255, (value >> 16) & 255];
}

bw.setup({
  advertise: [
    // packet id (2) + illuminance (4) + declaration (2) = 8, inside the 12 an
    // encrypted packet has on this board.
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
console.log("writable entries:", bw.plan().entryIds);
console.log("service data bytes:", bw.plan().serviceDataLength, "of", bw.plan().budget);

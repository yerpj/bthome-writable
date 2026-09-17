/* bthome-writable — a light that can also be switched on the device itself.
 *
 * Home Assistant writes the light entry; the Puck's button toggles the same
 * light locally. A receiver cannot know about the button press on its own, so
 * the entry has a `get` as well as a `set`: its characteristic becomes
 * readable, the device advertises BTHome's settings revision (0x65), and
 * bw.changed() bumps it after a local change so receivers read the light again
 * (PROTOCOL.md §3.2).
 *
 * Install with:
 *   python -m tools.espruino_deploy --address <mac> \
 *       --app espruino/examples/button-light.js
 * Then, after pressing the button:
 *   python -m tools.bthome_write --address <mac> --payload 1e01 --read
 */

var bw = require("BTHomeWritable");

var lamp = { on: false };

function apply() {
  digitalWrite(LED2, lamp.on);
}

// Called by the button, and callable from the console to simulate a press.
function toggle() {
  lamp.on = !lamp.on;
  apply();
  bw.changed();
}

bw.setup({
  advertise: [
    { type: "battery", interval: 300000, get: function () { return E.getBattery(); } },
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
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
});

setWatch(toggle, BTN, { edge: "rising", repeat: true, debounce: 50 });

apply();
console.log("advertising as", NRF.getAddress());
console.log("writable entries:", bw.plan().entryIds);

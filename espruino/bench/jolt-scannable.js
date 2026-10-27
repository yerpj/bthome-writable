/* bthome-writable — the board that reproduces the advertising-state bug.
 *
 * A Jolt.js is the only board on this bench whose firmware offers the coded
 * phy, and that is what latches `scannable` off for good: one call with
 * `phy:"coded"` or `extended:true` warns, clears the flag, and every later
 * advertising call that does not name `scannable` inherits the cleared state.
 * Connectable advertising with `scannable` off is a *directed* type, whose peer
 * address the firmware leaves NULL, so the radio refuses to be configured at
 * all and `NRF.setAdvertising` throws `ERR 0x10 (INVALID ADDR)` from a frame
 * that looks like the caller's fault (D-143, D-147, espruino#8024).
 *
 * `advOptions()` names `scannable:true` with the other five options, which is
 * what this sketch is here to exercise: call `poison()` and then anything that
 * republishes, and the module comes up where the five-option call throws.
 *
 * Nothing board-specific is assumed. `JOLTJS 2v28` reports
 * `MODULES=Flash,Storage,heatshrink,neopixel`, so there is no `AES` and a
 * sealed sketch would throw on its first packet; `E.getBattery()` is a Puck.js
 * function and there is no LED wired the way a Puck.js has one.
 *
 *   python -m tools.espruino_upload --port COM18 \
 *       espruino/dist/jolt-scannable-standalone.min.js
 */

var bw = require("BTHomeWritable");

var lamp = { on: false };
var n = 0;

bw.setup({
  advertise: [
    // Moves on every read, so every packet differs and a host that coalesces
    // identical advertisements still hears the rate.
    { type: "count", interval: 0, get: function () { n = (n + 1) & 0xff; return n; } },
    { type: "light", set: function (v) { lamp.on = v; } },
  ],
  interval: 1000,
  // The Jolt.js answers to "Jolt.js fa0b", 14 bytes of the 31 with its length
  // and type, and Espruino always adds its manufacturer id: 8 bytes of service
  // data then overflow the payload and the radio refuses the lot with
  // `ERR 0x9 (INVALID_LENGTH)`, measured here before this line existed.
  showName: false,
  onError: function (error) {
    console.log("rejected:", error.code, error.message);
  },
});

/* Arm the firmware's sticky flag, with the warning that comes with it.
 *
 * Both of these are the console's handles rather than this sketch's: it drives
 * nothing by itself, and a `var` the file never calls is an unused one to
 * `eslint` (which is what turned the Espruino job red from `e2c19d0` to
 * `d076546`). On `global` they are what D-147 ran, `poison()` then the five
 * options, and they lint. */
global.poison = function () {
  NRF.setAdvertising({}, { phy: "coded" });
};

/* The call the module used to make: five options, `scannable` not among them. */
global.fiveOptions = function () {
  NRF.setAdvertising(
    {},
    { interval: 1000, connectable: true, discoverable: true, whenConnected: true, showName: true }
  );
};

console.log("ready", NRF.getAddress(), bw.plan().entryIds);

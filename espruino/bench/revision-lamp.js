/* bthome-writable — a device whose settings revision moves on demand.
 *
 * The fixture D-130 needed and the bench did not have. Two writable entries
 * that are also readable, so the device advertises BTHome's settings revision
 * (§3.2) and a receiver re-reads them when it moves; and `bench.knob()`, which
 * moves a value locally and calls `bw.changed()` the way a physical knob would.
 * That is the sequence the fold is for: a local change owes the receiver a
 * read, and a command going out anyway can carry it.
 *
 * **Sealed or in clear, from the one constant below.** `BINDKEY` is null, which
 * is the device this bench ran until 2026-10-24: its firmware reported
 * `MODULES=timer,Flash,Storage,heatshrink,neopixel`, so `AES` was not defined
 * and a sealed sketch threw on its first packet. On a firmware that has
 * `crypto`, put the 32 hex characters the Home Assistant config entry holds
 * into BINDKEY and the same sketch advertises sealed and offers the counter
 * report of §5.6 -- which is what D-129's folded counter question has never
 * been measured against, for want of a sealed board that also moves its
 * revision.
 *
 * **Sealed, it fits with nothing to spare.** BTHome v2 spends 8 of the 20
 * service-data bytes this board accepts on the counter and the MIC, leaving 12,
 * and these three entries with the declaration and the revision are exactly 12.
 * Computed from the module's own `planPacket`, not estimated. Add an entry and
 * `setup()` throws `capacity_exceeded` before the first packet: drop the
 * temperature, which leaves 9 of 12.
 *
 * No LED is assumed -- a nice!nano has none wired the way a Puck.js does -- and
 * `E.getBattery()` is a Puck.js function, so the sensor is the nRF52's own die
 * temperature.
 *
 * Upload over USB, which keeps it in RAM:
 *   python -m tools.espruino_upload --port COM6 \
 *       espruino/dist/revision-lamp-standalone.min.js
 *
 * Then drive it from the console:
 *   bench.knob()      move the dimmer locally and call bw.changed()
 *   bench.conns()     how many centrals have connected since bench.reset()
 *   bench.reset()     put that counter back to zero
 *   bench.state()     what the entries hold
 */

var bw = require("BTHomeWritable");

/* null advertises in clear. A string of 32 hex characters seals everything and
   offers the counter report; it must be the key the receiver was given, or the
   receiver sees an undecodable BTHome device rather than a plain one. */
var BINDKEY = null;

var lamp = { on: false, level: 20 };
var conns = 0;

NRF.on("connect", function () {
  conns++;
});

var options = {
  advertise: [
    { type: "temperature", interval: 30000, get: function () { return E.getTemperature(); } },
    {
      type: "light",
      get: function () { return lamp.on; },
      set: function (v) { lamp.on = v; },
    },
    {
      type: "count",
      get: function () { return lamp.level; },
      set: function (v) { lamp.level = v; },
    },
  ],
  interval: 1000,
  // Measured on a nice!nano, not assumed: with its name in the packet the
  // radio takes almost nothing (D-046, D-049).
  showName: false,
  maxServiceData: 20,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
};

/* Set together, because the counter report is only offered with a key (§5.6)
   and a sealed device without it resumes ahead of the receiver on every reboot
   and then refuses writes in silence, which is D-078's first fault. */
if (BINDKEY) {
  options.bindkey = BINDKEY;
  options.counterReport = true;
}

bw.setup(options);

var bench = {
  knob: function () {
    lamp.level = (lamp.level + 37) & 255;
    bw.changed();
    return lamp.level;
  },
  conns: function () {
    return conns;
  },
  reset: function () {
    conns = 0;
    return conns;
  },
  state: function () {
    return "on=" + lamp.on + " level=" + lamp.level + " conns=" + conns;
  },
};

global.bench = bench;
console.log("advertising as", NRF.getAddress());
console.log("sealed:", BINDKEY ? "yes, counter report offered" : "no, in clear");
console.log("writable entries:", bw.plan().entryIds);
console.log("service data bytes:", bw.plan().serviceDataLength, "of", bw.plan().budget);

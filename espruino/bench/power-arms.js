/* bthome-writable — the sketch the current measurements of §23 are made on.
 *
 * One fixture for every arm of the power characterisation, because a figure
 * measured on a different sketch than the one next to it in the table is not
 * comparable with it. Four constants below select the arm; nothing else
 * changes, and nothing here needs a console once it is running -- which
 * matters, since a console is a connection and a connection is the thing being
 * measured.
 *
 * **Load it over the radio, not over the cable.** The board under the meter is
 * powered by the meter, so a USB cable would both supply it and keep a link
 * open. The Web IDE connects to an Espruino board over Bluetooth, which leaves
 * the sketch in RAM, costs the device nothing once the IDE disconnects, and
 * writes nothing to flash (`docs/shared-bench.md`).
 *
 *   over the radio: Web IDE > Connect > Web Bluetooth > this board, then send
 *                   espruino/dist/power-arms-standalone.min.js
 *   over the cable: python -m tools.espruino_upload --port COM6 \
 *                       espruino/dist/power-arms-standalone.min.js
 *
 * **MARK is what makes a trace readable.** Wire the pad named below to the
 * meter's digital input -- GPI1 on an Otii Arc Pro, D0 on a PPK2 -- and the
 * trace segments itself: the pin is high for exactly the connection a command
 * runs in, and for exactly the rebuild `bench.rebuild()` asks for.
 * `tools/power_charge.py` integrates those windows out of the export. With MARK
 * null the sketch behaves identically and the windows have to be cut by hand or
 * by current threshold.
 *
 * **SWEEP is the light measurement.** With a list of advertising intervals in
 * it the device walks them on its own, SWEEP_MS apart, pulsing the marker for a
 * second at each step: one recording, no central, no reload, and the steps are
 * the stretches between pulses. `tools/power_charge.py --gaps` reads exactly
 * those. That is the whole advertising dimension of the reference table in one
 * sitting.
 *
 * Then drive it, if the arm needs driving:
 *   bench.knob()      move the dimmer locally and call bw.changed()
 *   bench.rebuild()   one forced rebuild, inside the marker
 *   bench.interval(ms)  change the advertising interval by hand
 *   bench.state()     what the entries hold
 */

var bw = require("BTHomeWritable");

/* null advertises in clear; 32 hex characters seal everything and offer the
   counter report. Both arms matter: sealing is most of a rebuild (§8). */
var BINDKEY = "231d39c1d7cc1ab1aee224cd096db932";

/* The arm's idle advertising interval, in milliseconds. 2000 is the module's
   default, 1000 and 3200 are the ends of the range §16 measured for
   responsiveness, and this is the term that decides a coin cell's life. */
var ADV_INTERVAL = 2000;

/* null leaves Espruino's own adjustment in charge, which is every device as
   shipped; 7.5 pins the connection interval the way D-141 proposes. It only
   has an effect while a central is connected. */
var CONNECTION_INTERVAL = null;

/* A free pad wired to the meter's digital input: D1 on a Puck.js, D1 on a
   nice!nano. Tell the meter the board's logic level, or a 3 V marker read
   against a 5 V threshold never goes high. null disables the marker. */
var MARK = D1;

/* Advertising intervals the device steps through on its own, in
   milliseconds, or null for a single-interval run. SWEEP_MS is how long each
   step lasts and SWEEP_START_MS how long it waits first -- long enough for the
   Web IDE to let go and for the 30 s fast window that its disconnect opens to
   expire, so disconnect as soon as the sketch is loaded. */
var SWEEP = [100, 200, 500, 1000, 2000, 3200, 5000, 10000];
var SWEEP_MS = 120000;
var SWEEP_START_MS = 120000;

/* Milliseconds between re-reads of the one advertised sensor, or null for a
   device that advertises nothing it has to read -- which holds no timer at
   all, and is the floor every other arm is measured against. */
var SENSOR_INTERVAL = null;

var lamp = { on: false, level: 20 };

function mark(level) {
  if (MARK !== null) digitalWrite(MARK, level);
}

/* `digitalWrite` makes the pad an output on its own, so writing it low once
   is all the setup the marker needs. */
mark(0);

NRF.on("connect", function () {
  mark(1);
});

NRF.on("disconnect", function () {
  mark(0);
});

var entries = [
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
];

/* The nRF52's own die temperature, because `E.getBattery()` is a Puck.js
   function and the same sketch has to run on both boards. */
if (SENSOR_INTERVAL !== null) {
  entries.unshift({
    type: "temperature",
    interval: SENSOR_INTERVAL,
    get: function () { return E.getTemperature(); },
  });
}

var options = {
  advertise: entries,
  interval: ADV_INTERVAL,
  showName: false,
  maxServiceData: 20,
  onError: function (error) {
    console.log("write rejected:", error.code, error.message);
  },
};

if (BINDKEY) {
  options.bindkey = BINDKEY;
  options.counterReport = true;
}

bw.setup(options);

if (CONNECTION_INTERVAL !== null) NRF.setConnectionInterval(CONNECTION_INTERVAL);

/* One step: mark it, change the rate, and come back for the next one. The
   pulse lands inside its own step, so the stretch of trace that belongs to step
   k is the quiet between pulse k and pulse k+1. */
function sweepStep(index) {
  if (index >= SWEEP.length) {
    console.log("sweep: done");
    return;
  }
  mark(1);
  setTimeout(function () {
    mark(0);
  }, 1000);
  bw.setAdvertisingInterval(SWEEP[index]);
  console.log("sweep step", index + 1, "of", SWEEP.length, "at", SWEEP[index], "ms");
  setTimeout(function () {
    sweepStep(index + 1);
  }, SWEEP_MS);
}

if (SWEEP !== null) {
  setTimeout(function () {
    sweepStep(0);
  }, SWEEP_START_MS);
}

var bench = {
  knob: function () {
    lamp.level = (lamp.level + 37) & 255;
    bw.changed();
    return lamp.level;
  },
  /* One rebuild, inside the marker. `bw.changed()` cannot be marked this way:
     it returns at once and the work lands 250 ms later, outside any window a
     synchronous wrapper could raise. */
  rebuild: function () {
    mark(1);
    bw.update();
    mark(0);
    return "one rebuild";
  },
  interval: function (ms) {
    return bw.setAdvertisingInterval(ms);
  },
  state: function () {
    return "on=" + lamp.on + " level=" + lamp.level;
  },
};

global.bench = bench;
console.log("arm:", ADV_INTERVAL + " ms adv,", BINDKEY ? "sealed," : "in clear,",
  "connection interval", CONNECTION_INTERVAL === null ? "auto" : CONNECTION_INTERVAL,
  SENSOR_INTERVAL === null ? ", no sensor" : ", sensor at " + SENSOR_INTERVAL + " ms");
console.log("address:", NRF.getAddress());
console.log("service data bytes:", bw.plan().serviceDataLength, "of", bw.plan().budget);
console.log("marker pin:", MARK === null ? "none" : MARK);
if (SWEEP !== null) {
  console.log(
    "sweep:",
    SWEEP.join(" "),
    "ms,",
    SWEEP_MS / 1000 + " s each, starting in " + SWEEP_START_MS / 1000 + " s"
  );
}

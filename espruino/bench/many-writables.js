/* bthome-writable — @enaon's lamp, reduced to a board with nothing on its pins.
 *
 * A bench repro, not an example. In espruino#8024 on 2026-10-21 he reported
 * that a read of a writable entry fails intermittently: the read authenticates
 * and then carries the wrong object, `entry 1: read object 0x3C, expected
 * 0x1E`, and once `0xEA`. It happens only when `bw.changed()` is called from a
 * button handler while the lamp is doing its own work, and deferring the call
 * by 250 ms made it go away. The summary he forwarded blames the cost of
 * re-sealing every readable entry; that explains lateness, not wrongness, so
 * this exists to separate the variables before anything is changed.
 *
 * His `setup()`, posted the same day, is copied here entry for entry:
 *
 *   `battery` advertised at `interval: 300000`, three writable entries all
 *   with a `get` — `light` for the lamp, `light` for its PIR auto flag,
 *   `count` for the brightness as `getBri() * 255` — `interval: 1000`,
 *   `maxServiceData: 20`, `showName: false`, `counterReport: true`, a bindkey.
 *
 * Four things about that list are the experiment:
 *
 * * **it is exactly 12 bytes of service data, of the 12 a sealed packet has on
 *   this board** (D-049): info 1, packet id 2, battery 2, revision 2 and a
 *   three-entry declaration 5. A fourth writable entry would be refused.
 * * **`count` is object `0x09`, one byte**, encoded upstream as `[0x09, 0|e.v]`.
 *   So brightness 60 is `0x3C` and brightness 234 is `0xEA` — both of the bytes
 *   Home Assistant reported as objects are brightness values, and neither is an
 *   object his device declares. Kept as a float times 255, truncation included.
 * * **the brightness moves while the handler runs.** `fadeTo()` keeps mutating
 *   what the third entry's `get()` returns, during the very burst that stages
 *   all three reads. A spin loop would block the thread without that, and the
 *   difference may be the whole thing, so the fade is simulated here.
 * * **`counterReport: true`.** Its answer is sealed under the same direction
 *   byte as an entry read, so it authenticates as one, and its plaintext starts
 *   with a byte of the receiver's challenge — arbitrary, which is the other way
 *   a nonsense object id can appear. A receiver asks for it when the revision
 *   moves, which is what `changed()` does (coordinator.py, `_resync_counter`).
 *
 * Nothing here touches a pin: the lamp is three numbers.
 *
 * Install over USB, because this host cannot open a GATT connection to this
 * board:
 *   python -m tools.espruino_upload --port COM15 espruino/bench/many-writables.js
 *
 * Then drive it from the console, or let tools/repro_changed_race.py do it:
 *   bench.press()          one press: start a fade, then changed()
 *   bench.busy(ms)         how long the fade runs (150)
 *   bench.defer(ms)        0 calls changed() inline, >0 through setTimeout
 *   bench.fade(on)         false makes the busy work a plain spin instead
 *   bench.loop(n, gapMs)   n presses, spaced
 *   bench.stop()
 *   bench.report()
 */

/* exported bench */

var bw = require("BTHomeWritable");

/* Keep the console on USB.
 *
 * Espruino moves it to the BLE link whenever a central connects -- the
 * `-> Bluetooth` and `<- Bluetooth` lines -- and that swallows every print
 * this repro makes, during exactly the window the repro is about: the first
 * run of it recorded one `changed()` out of forty. It is also work on the one
 * thread, twice per connection, which is a confound of its own. */
try {
  E.setConsole("USB", { force: true });
} catch (e) {
  console.log("could not pin the console to USB:", e.message);
}

/* The two knobs the conditions are made of. tools/repro_changed_race.py
 * substitutes these two lines before it sends the file, because a condition
 * chosen at `setup()` time has to be in the file that runs: a board configured
 * afterwards over the console is a board in a state no line of the repro
 * describes. Edit them by hand and upload if you are driving it yourself. */
var SEALED = true;
var ENTRIES = 3;

/* The lamp, as numbers. `bri` is 0..1 like his `getBri()`. */
var lamp = { isOn: false, bri: 0, auto: false };

var cfg = { busy: 150, defer: 0, fade: true };
var stats = { presses: 0, errors: 0, last: 0, worst: 0 };
var timer;
var fading;

/* Block the single thread for `ms`, the way a fade written as a loop does. */
function burn(ms) {
  var until = getTime() * 1000 + ms;
  var spins = 0;
  while (getTime() * 1000 < until) spins++;
  return spins;
}

/* A fade that keeps moving the brightness while everything else happens.
 *
 * Synchronous on purpose, in steps, so that `getBri()` really does answer
 * differently at two points inside one burst of reads -- which is his lamp and
 * is not a spin loop. */
function fadeTo(target, ms) {
  var steps = 10;
  var step = ms / steps;
  var from = lamp.bri;
  for (var i = 1; i <= steps; i++) {
    lamp.bri = from + ((target - from) * i) / steps;
    burn(step);
  }
  lamp.bri = target;
}

function announce() {
  var started = getTime() * 1000;
  try {
    bw.changed();
  } catch (e) {
    stats.errors++;
    console.log("ERR", e.code, e.message);
  }
  stats.last = Math.round(getTime() * 1000 - started);
  if (stats.last > stats.worst) stats.worst = stats.last;
  console.log("CHANGED[" + stats.presses + "]", stats.last, "ms bri=" + lamp.bri.toFixed(2));
}

/* One simulated button press, in his order: the handler changes what the
 * device holds, the lamp does its own work, and `changed()` goes out from
 * inside that same callback. */
function press() {
  stats.presses++;
  lamp.isOn = !lamp.isOn;
  if (stats.presses % 3 === 0) lamp.auto = !lamp.auto;
  if (cfg.fade) fadeTo(lamp.isOn ? 0.2 + (stats.presses % 4) / 5 : 0, cfg.busy);
  else burn(cfg.busy);
  console.log(
    "PRESS[" + stats.presses + "] busy=" + cfg.busy,
    "defer=" + cfg.defer,
    "fade=" + cfg.fade
  );
  if (cfg.defer > 0) setTimeout(announce, cfg.defer);
  else announce();
}

function stop() {
  if (timer !== undefined) {
    clearInterval(timer);
    timer = undefined;
  }
  if (fading !== undefined) {
    clearInterval(fading);
    fading = undefined;
  }
  console.log("STOPPED after", stats.presses, "presses,", stats.errors, "errors");
}

function loop(n, gap) {
  if (timer !== undefined) clearInterval(timer);
  var left = n === undefined ? 10 : n;
  var every = gap === undefined ? 4000 : gap;
  console.log("LOOP", left, "presses every", every, "ms");
  timer = setInterval(function () {
    if (left <= 0) {
      stop();
      console.log("DONE");
      return;
    }
    left--;
    press();
  }, every);
}

function report() {
  console.log(
    "REPORT presses=" + stats.presses,
    "errors=" + stats.errors,
    "lastChanged=" + stats.last,
    "worstChanged=" + stats.worst,
    "busy=" + cfg.busy,
    "defer=" + cfg.defer,
    "fade=" + cfg.fade,
    "sealed=" + SEALED,
    "entries=" + ENTRIES
  );
}

var bench = {
  press: press,
  loop: loop,
  stop: stop,
  report: report,
  busy: function (ms) {
    cfg.busy = ms;
    console.log("BUSY", cfg.busy);
  },
  defer: function (ms) {
    cfg.defer = ms;
    console.log("DEFER", cfg.defer);
  },
  fade: function (on) {
    cfg.fade = on !== false;
    console.log("FADE", cfg.fade);
  },
};
global.bench = bench;

/* His three writable entries, in his order. Entry 1 is the one whose reads
 * came back wrong, so it stays entry 1. */
var candidates = [
  {
    // entry 1, object 0x1E: the lamp
    type: "light",
    get: function () {
      return lamp.isOn;
    },
    set: function (v) {
      lamp.isOn = v;
      if (cfg.fade) fadeTo(v ? 0.6 : 0, cfg.busy);
    },
  },
  {
    // entry 2, object 0x1E as well: his PIR auto flag. A mix-up between this
    // one and entry 1 shows as a wrong value, not an error.
    type: "light",
    get: function () {
      return lamp.auto;
    },
    set: function (v) {
      lamp.auto = v;
    },
  },
  {
    // entry 3, object 0x09: brightness, his `getBri() * 255`, float and all.
    // `0|e.v` upstream truncates it, and the byte that comes out is what Home
    // Assistant reported as an object id.
    type: "count",
    get: function () {
      return lamp.bri * 255;
    },
    set: function (v) {
      lamp.bri = v / 255;
    },
  },
];

var options = {
  advertise: [
    // Advertised, not writable, exactly as he has it. nice!nano has no
    // E.getBattery(), so this reads the supply voltage the same way
    // examples/mixed-controls.js does.
    {
      type: "battery",
      interval: 300000,
      get: function () {
        return Math.min(100, Math.round(NRF.getBattery() * 25));
      },
    },
  ].concat(candidates.slice(0, ENTRIES)),
  interval: 1000,
  // Measured on this board and this firmware, not assumed (D-049). Setting it
  // has setup() refuse a packet that does not fit rather than the radio.
  maxServiceData: 20,
  showName: false,
  onError: function (error) {
    stats.errors++;
    console.log("ERR", error.code, error.message);
  },
};

if (SEALED) {
  // From test-vectors.json, and therefore public. His is his own.
  options.bindkey = "231d39c1d7cc1ab1aee224cd096db932";
  options.counterReport = true;
}

bw.setup(options);

console.log("advertising as", NRF.getAddress());
console.log("writable entries:", bw.plan().entryIds);
console.log("service data bytes:", bw.plan().serviceDataLength, "of", bw.plan().budget);
report();

"use strict";

/* The generated bundles in dist/ are what actually gets flashed.
 *
 * They are produced by tools/build_espruino_bundle.py, which inlines the module
 * and — for the .min.js — strips comments, because Espruino keeps the source
 * text of every function in RAM and this module is comment-heavy on purpose.
 * Stripping comments without a JS parser is the kind of thing that works until
 * it silently does not, so every bundle is executed here against stubbed
 * Espruino globals, and the readable and stripped forms must behave the same.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const DIST = path.join(__dirname, "..", "dist");
const BUNDLES = fs
  .readdirSync(DIST)
  .filter((name) => name.endsWith(".js"))
  .sort();

/* Fixed stub readings, so the expected packets below are exact. */
const BATTERY = 90; // 0x5a
const LIGHT_LEVEL = 0.25; // -> 0.25 * 1000 * 100 = 25000 = a8 61 00 little-endian

/* What each example should put on the air at setup, and which pin it drives.
 * Keyed by the example's name, since dist/ holds two forms of each. */
const EXPECTED = {
  "single-light": {
    // 40 | 00 01 | 01 5a | 1e 00 | ff 04
    packet: "400001015a1e00ff04",
    pin: "LED1",
    interval: 1000,
    // 40 | 00 02 | 01 5a | 1e 01 | ff 04
    afterWrite: "400002015a1e01ff04",
  },
  "light-loop": {
    // 40 | 00 01 | 01 5a | 05 a8 61 00 | 1e 00 | ff 08
    packet: "400001015a05a861001e00ff08",
    pin: "LED2",
    interval: 2000,
    afterWrite: "400002015a05a861001e01ff08",
  },
};

function exampleOf(bundleName) {
  return bundleName.replace(/-standalone(\.min)?\.js$/, "");
}

/* Just enough of Espruino to let a bundle set itself up, plus recorders for
 * what it would have put on the air and on its pins. */
function run(source) {
  const advertised = [];
  const timers = [];
  const pins = {};
  let characteristics = null;

  const context = {
    console: { log() {} },
    setInterval(fn, ms) {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearInterval(handle) {
      if (handle !== undefined) timers.splice(handle - 1, 1);
    },
    NRF: {
      setAdvertising(data) {
        advertised.push(data[0xfcd2].slice());
      },
      setServices(services) {
        characteristics = services[Object.keys(services)[0]];
      },
      getAddress: () => "c8:80:32:ad:f7:b9",
    },
    E: { getBattery: () => BATTERY },
    Puck: { light: () => LIGHT_LEVEL },
    LED1: "LED1",
    LED2: "LED2",
    LED3: "LED3",
    digitalWrite(pin, value) {
      pins[pin] = value;
    },
    require(name) {
      if (name !== "BTHome") throw new Error(`unexpected require(${name})`);
      return {
        packetId: 0,
        getAdvertisement(devices) {
          const device = devices[0];
          let object;
          if (device.type === "battery") object = [0x01, Math.round(device.v)];
          else if (device.type === "raw") object = device.v;
          else object = [0x1e, device.v ? 1 : 0];
          return { 0xfcd2: [0x40, 0x00, 0x01].concat(object) };
        },
      };
    },
  };

  vm.createContext(context);
  vm.runInContext(source, context);

  return { advertised, timers, pins, characteristics };
}

function hex(bytes) {
  return bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
}

function load(name) {
  return fs.readFileSync(path.join(DIST, name), "utf8");
}

test("every example is built in both forms", () => {
  for (const example of Object.keys(EXPECTED)) {
    assert.ok(BUNDLES.includes(`${example}-standalone.js`), example);
    assert.ok(BUNDLES.includes(`${example}-standalone.min.js`), example);
  }
});

test("the stripped bundles are meaningfully smaller", () => {
  /* If this stops holding, the comment stripper silently stopped working. */
  for (const example of Object.keys(EXPECTED)) {
    const full = fs.statSync(path.join(DIST, `${example}-standalone.js`)).size;
    const min = fs.statSync(path.join(DIST, `${example}-standalone.min.js`)).size;
    assert.ok(min < full * 0.75, `${example}: ${min} vs ${full}`);
  }
});

for (const name of BUNDLES) {
  const expected = EXPECTED[exampleOf(name)];
  if (!expected) continue;

  test(`${name}: advertises the expected packet at setup`, () => {
    const result = run(load(name));
    assert.equal(result.advertised.length, 1, "setup should advertise once");
    assert.equal(hex(result.advertised[0]), expected.packet);
  });

  test(`${name}: a write drives the right pin and shows up in the packet`, () => {
    const result = run(load(name));
    const uuids = Object.keys(result.characteristics);
    assert.equal(uuids.length, 1);

    result.characteristics[uuids[0]].onWrite({ data: [0x1e, 0x01] });
    assert.equal(result.pins[expected.pin], true, `${expected.pin} should be on`);
    assert.equal(hex(result.advertised[1]), expected.afterWrite);

    result.characteristics[uuids[0]].onWrite({ data: [0x1e, 0x00] });
    assert.equal(result.pins[expected.pin], false);
  });

  test(`${name}: schedules a periodic refresh of the advertised values`, () => {
    /* Without it the packet is built once at setup and never again: sensor
     * values freeze at their boot readings and the packet id never changes,
     * which is what a receiver uses to tell a fresh advertisement from a
     * repeat. Caught on hardware, where four consecutive captures all carried
     * packet id 1. */
    const result = run(load(name));

    assert.equal(result.timers.length, 1, "setup should schedule one refresh");
    assert.equal(result.timers[0].ms, expected.interval);

    const before = result.advertised.length;
    result.timers[0].fn();
    assert.equal(result.advertised.length, before + 1);
    assert.notEqual(
      hex(result.advertised[before]),
      hex(result.advertised[before - 1])
    );
  });

  test(`${name}: does not advertise the 128-bit service UUID`, () => {
    /* It costs 18 of the 31 available bytes and buys nothing: the receiver
     * finds the device by its BTHome service data and discovers the service
     * after connecting (PROTOCOL.md §4.1). */
    assert.doesNotMatch(load(name), /advertise:\s*\[\s*SERVICE_UUID/);
  });
}

test("light-loop puts the sensor and the actuator on different LEDs", () => {
  /* Puck.light() reads through the red LED, so an actuator on LED1 would be
   * measuring itself in the most literal way. The whole point of the example is
   * that the measurement is independent of the command. */
  const source = load("light-loop-standalone.js");
  assert.match(source, /digitalWrite\(LED2/);
  assert.doesNotMatch(source, /digitalWrite\(LED1/);
});

test("light-loop reaches the illuminance object through the raw escape hatch", () => {
  /* The upstream BTHome module has no illuminance type. Its `raw` type emits
   * bytes verbatim -- object ID included, and with no length byte, which is
   * why `raw` must not be treated as length-prefixed. */
  const result = run(load("light-loop-standalone.js"));
  const packet = hex(result.advertised[0]);
  assert.match(packet, /05a86100/, "illuminance object 0x05, 25000 hundredths");
});

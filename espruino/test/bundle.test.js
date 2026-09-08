"use strict";

/* The generated bundles in dist/ are what actually gets flashed.
 *
 * They are produced by tools/build_espruino_bundle.py, which inlines the module
 * and — for the .min.js — strips comments, because Espruino keeps the source
 * text of every function in RAM and this module is comment-heavy on purpose.
 * Stripping comments without a JS parser is the kind of thing that works until
 * it silently does not, so both bundles are executed here against stubbed
 * Espruino globals and must behave identically.
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

/* Just enough of Espruino to let the bundle set itself up, plus a recorder for
 * what it would have put on the air. */
function run(source) {
  const advertised = [];
  let written = null;
  let led = null;

  const context = {
    console: { log() {} },
    NRF: {
      setAdvertising(data) {
        advertised.push(data[0xfcd2].slice());
      },
      setServices(services) {
        const uuid = Object.keys(services)[0];
        written = services[uuid];
      },
      getAddress: () => "c8:80:32:ad:f7:b9",
    },
    E: { getBattery: () => 90 },
    LED1: "LED1",
    digitalWrite(pin, value) {
      led = value;
    },
    require(name) {
      if (name !== "BTHome") throw new Error(`unexpected require(${name})`);
      return {
        packetId: 0,
        getAdvertisement(devices) {
          const device = devices[0];
          const object =
            device.type === "battery"
              ? [0x01, Math.round(device.v)]
              : [0x1e, device.v ? 1 : 0];
          return { 0xfcd2: [0x40, 0x00, 0x01].concat(object) };
        },
      };
    },
  };

  vm.createContext(context);
  vm.runInContext(source, context);

  return {
    context,
    advertised,
    characteristics: written,
    led: () => led,
  };
}

function hex(bytes) {
  return bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
}

test("both bundles exist", () => {
  assert.ok(BUNDLES.includes("single-light-standalone.js"));
  assert.ok(BUNDLES.includes("single-light-standalone.min.js"));
});

test("the stripped bundle is meaningfully smaller", () => {
  /* If this stops holding, the stripper silently stopped working. */
  const full = fs.statSync(path.join(DIST, "single-light-standalone.js")).size;
  const min = fs.statSync(path.join(DIST, "single-light-standalone.min.js")).size;
  assert.ok(min < full * 0.75, `${min} is not meaningfully smaller than ${full}`);
});

for (const name of BUNDLES) {
  test(`${name}: sets up and advertises the expected packet`, () => {
    const source = fs.readFileSync(path.join(DIST, name), "utf8");
    const result = run(source);

    assert.equal(result.advertised.length, 1, "setup should advertise once");
    // 40 | 00 01 (packet id) | 01 5a (battery 90) | 1e 00 (light off) | ff 04
    assert.equal(hex(result.advertised[0]), "400001015a1e00ff04");
  });

  test(`${name}: exposes the write characteristic, and a write drives the pin`, () => {
    const source = fs.readFileSync(path.join(DIST, name), "utf8");
    const result = run(source);

    const uuids = Object.keys(result.characteristics);
    assert.equal(uuids.length, 1);

    result.characteristics[uuids[0]].onWrite({ data: [0x1e, 0x01] });
    assert.equal(result.led(), true, "the light should be on");
    assert.equal(hex(result.advertised[1]), "400002015a1e01ff04");

    result.characteristics[uuids[0]].onWrite({ data: [0x1e, 0x00] });
    assert.equal(result.led(), false);
  });

  test(`${name}: does not advertise the 128-bit service UUID`, () => {
    /* It costs 18 of the 31 available bytes and buys nothing: the receiver
     * finds the device by its BTHome service data and discovers the service
     * after connecting (PROTOCOL.md §4.1). */
    const source = fs.readFileSync(path.join(DIST, name), "utf8");
    assert.doesNotMatch(source, /advertise:\s*\[\s*SERVICE_UUID/);
  });
}

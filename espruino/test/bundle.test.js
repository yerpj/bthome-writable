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
    // 40 | 00 01 | 01 5a | ff 1e -- the light is declared, its state is not advertised
    packet: "400001015aff1e",
    pin: "LED1",
  },
  "light-loop": {
    // 40 | 00 01 | 01 5a | 05 a8 61 00 | ff 1e
    packet: "400001015a05a86100ff1e",
    pin: "LED2",
  },
};

function exampleOf(bundleName) {
  return bundleName.replace(/-standalone(\.min)?\.js$/, "");
}

/* Just enough of Espruino to let a bundle set itself up, plus recorders for
 * what it would have put on the air and on its pins. */
function run(source) {
  const advertised = [];
  const options = [];
  const timers = [];
  const timeouts = [];
  const handlers = {};
  const pins = {};
  let characteristics = null;
  let serviceUuid = null;

  const context = {
    console: { log() {} },
    setInterval(fn, ms) {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearInterval(handle) {
      if (handle !== undefined) timers.splice(handle - 1, 1);
    },
    setTimeout(fn, ms) {
      timeouts.push({ fn, ms });
      return timeouts.length;
    },
    clearTimeout(handle) {
      if (handle !== undefined) timeouts[handle - 1] = { cancelled: true };
    },
    NRF: {
      on(event, fn) {
        handlers[event] = fn;
      },
      setAdvertising(data, opts) {
        advertised.push(data[0xfcd2].slice());
        options.push(opts);
      },
      setServices(services) {
        serviceUuid = Object.keys(services)[0];
        characteristics = services[serviceUuid];
      },
      updateServices() {},
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

  return {
    advertised,
    options,
    timers,
    timeouts,
    handlers,
    pins,
    get characteristics() {
      return characteristics;
    },
    get serviceUuid() {
      return serviceUuid;
    },
    context,
  };
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

  test(`${name}: a write to characteristic 1 drives the right pin`, () => {
    const result = run(load(name));
    assert.equal(result.serviceUuid, "2FAA0000-3B0B-4B1A-9E2A-B4C2952E62F2");
    assert.deepEqual(Object.keys(result.characteristics), [
      "2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2",
    ]);
    const light = result.characteristics["2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2"];

    light.onWrite({ data: [0x1e, 0x01] });
    assert.equal(result.pins[expected.pin], true, `${expected.pin} should be on`);
    light.onWrite({ data: [0x1e, 0x00] });
    assert.equal(result.pins[expected.pin], false);
  });

  test(`${name}: every write republishes at once`, () => {
    /* Advertising fast repeats the packet the device already has, so anything a
     * write changed that *is* advertised -- a sensor measuring the effect --
     * would otherwise wait for the next scheduled rebuild, which runs at the
     * idle interval. Measured at 18 s on a 10 s interval before this, against
     * one second for the write itself (D-050). The second write is the one that
     * matters: by then the device is already advertising fast, which is exactly
     * when the old code skipped the rebuild. */
    const result = run(load(name));
    const light = result.characteristics["2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2"];

    const before = result.advertised.length;
    light.onWrite({ data: [0x1e, 0x01] });
    assert.equal(result.advertised.length, before + 1);
    light.onWrite({ data: [0x1e, 0x00] });
    assert.equal(result.advertised.length, before + 2);
    // A rebuilt packet, not a repeat: the packet id moves every time.
    assert.notEqual(
      hex(result.advertised[before + 1]),
      hex(result.advertised[before])
    );
  });

  test(`${name}: the light's state never reaches the advertising`, () => {
    /* PROTOCOL.md §2.3: writable values are not advertised. */
    const result = run(load(name));
    const light = result.characteristics["2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2"];
    light.onWrite({ data: [0x1e, 0x01] });
    for (const packet of result.advertised) {
      assert.doesNotMatch(hex(packet), /1e01/);
    }
  });

  test(`${name}: a write of the wrong object type is refused`, () => {
    const result = run(load(name));
    const light = result.characteristics["2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2"];
    light.onWrite({ data: [0x53, 0x01, 0x41] });
    assert.notEqual(result.pins[expected.pin], true);
  });

  test(`${name}: schedules a periodic refresh of the advertised values`, () => {
    /* Without it the packet is built once at setup and never again: sensor
     * values freeze at their boot readings and the packet id never changes,
     * which is what a receiver uses to tell a fresh advertisement from a
     * repeat. Caught on hardware, where four consecutive captures all carried
     * packet id 1. */
    const result = run(load(name));

    assert.equal(result.timers.length, 1, "setup should schedule one refresh");
    /* Against the interval the bundle itself just advertised at, not a number
     * written here: an expectation that repeats a value living in the example
     * goes stale the day the example changes, and this one did. */
    assert.equal(result.timers[0].ms, result.options[0].interval);

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

test("advertising continues while a receiver is connected", () => {
  /* Without `whenConnected` the device goes silent exactly when a receiver most
   * wants to hear it — during and just after the write it is sending. The stack
   * switches the packets to non-connectable for the duration, which is what
   * puts the 100 ms floor on the fast interval. */
  const result = run(load("light-loop-standalone.js"));
  assert.equal(result.options[0].whenConnected, true);
});

test("a connection switches to the fast advertising interval", () => {
  /* A central can only begin a connection when it catches a connectable
   * advertising event, so the idle interval taxes every write. Real use comes
   * in bursts, so the device advertises fast from the moment a receiver
   * connects (decisions.md D-013). */
  const result = run(load("light-loop-standalone.js"));
  const idle = result.options[0].interval;

  result.handlers.connect("aa:bb:cc:dd:ee:ff");
  const fast = result.options[result.options.length - 1].interval;

  assert.ok(fast < idle, `${fast} should be faster than the idle ${idle}`);
  assert.ok(fast >= 100, "the BLE spec floors non-connectable advertising at 100 ms");
});

test("it stays fast for a while after the receiver goes away, then relaxes", () => {
  const result = run(load("light-loop-standalone.js"));
  const idle = result.options[0].interval;

  result.handlers.connect("aa:bb:cc:dd:ee:ff");
  result.handlers.disconnect(19);

  // Still fast: the disconnect only arms a timer.
  assert.ok(result.options[result.options.length - 1].interval < idle);

  const pending = result.timeouts.filter((t) => !t.cancelled);
  assert.equal(pending.length, 1, "one pending return-to-idle");
  pending[0].fn();

  assert.equal(result.options[result.options.length - 1].interval, idle);
});

test("a write keeps the device fast even without a connect event", () => {
  const result = run(load("light-loop-standalone.js"));
  const idle = result.options[0].interval;
  const uuid = Object.keys(result.characteristics)[0];

  result.characteristics[uuid].onWrite({ data: [0x1e, 0x01] });
  assert.ok(result.options[result.options.length - 1].interval < idle);
});

test("an advertising interval the radio cannot honour is refused at setup", () => {
  /* The firmware clamps anything outside 20-10000 ms silently, which is the
   * kind of thing that costs an afternoon. */
  const result = run(load("light-loop-standalone.js"));

  for (const bad of [5, 20000]) {
    assert.throws(
      () =>
        result.context.bw.setup({
          advertise: [{ type: "battery", get: () => 90 }],
          interval: bad,
        }),
      (error) => error.code === "interval_out_of_range",
      `${bad} ms should be refused`
    );
  }
});

test("the advertising interval can be changed without re-running setup", () => {
  /* This is the knob worth trying against a real receiver, and reflashing to
   * try a number is a poor way to find out. It moves the radio *and* the
   * rebuild timer, since in BTHome terms they are the same thing. */
  const result = run(load("light-loop-standalone.js"));
  result.options.length = 0;
  result.timers.length = 0;

  assert.equal(result.context.bw.setAdvertisingInterval(750), 750);
  assert.equal(result.options[result.options.length - 1].interval, 750);
  assert.equal(result.timers[result.timers.length - 1].ms, 750);
});

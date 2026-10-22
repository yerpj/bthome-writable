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
    // 40 | 00 01 | 01 5a | ff 01 1e -- the light is declared, its state is not advertised
    packet: "400001015aff011e",
    pin: "LED1",
  },
  "light-loop": {
    // 40 | 00 01 | 01 5a | 05 a8 61 00 | ff 01 1e
    packet: "400001015a05a86100ff011e",
    pin: "LED2",
    // Its light sensor measures what its own write did, which is the whole
    // point of the example -- and now the thing that asks for a rebuild.
    mirrors: true,
  },
};

function exampleOf(bundleName) {
  return bundleName.replace(/-standalone(\.min)?\.js$/, "");
}

/* Just enough of Espruino to let a bundle set itself up, plus recorders for
 * what it would have put on the air and on its pins. */
function fakeStorage(initial) {
  /* Espruino's Storage, as much of it as the module uses. `files` is handed
   * back so a test can read what was persisted and, by re-running with it,
   * stand in for a reboot. */
  const files = Object.assign({}, initial);
  return {
    files,
    readJSON(name) {
      return Object.prototype.hasOwnProperty.call(files, name)
        ? files[name]
        : undefined;
    },
    writeJSON(name, value) {
      files[name] = value;
    },
    list() {
      return Object.keys(files);
    },
  };
}

/* Not AES. The module's counter handling is what is under test here, and the
 * real cipher is covered against the shared vectors in ccm.test.js. */
const cipher = {
  encrypt(data) {
    return { data, mic: [0, 0, 0, 0] };
  },
  decrypt() {
    return null;
  },
};

function run(source, storedFiles) {
  const advertised = [];
  const options = [];
  const timers = [];
  const timeouts = [];
  const handlers = {};
  // How many times each event was subscribed to. The fake used to keep only
  // the latest handler, so a module stacking a second one looked identical
  // to one that did not (D-088).
  const subscriptions = {};
  // Set by a test to make the radio refuse a packet of a given size.
  let refuseAdvertising = null;
  const pins = {};
  let characteristics = null;
  let serviceUuid = null;

  /* What the fake sensors read. Mutable, because a rebuild now depends on a
   * reading having moved: a test that cannot move one cannot reach the case
   * (D-106). */
  const sensors = { battery: BATTERY, light: LIGHT_LEVEL };

  let clock = Date.now();
  const storage = fakeStorage(storedFiles);
  const context = {
    console: { log() {} },
    setInterval(fn, ms) {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearInterval(handle) {
      if (handle !== undefined) timers.splice(handle - 1, 1);
    },
    /* `name` is how a test tells the two timeouts the module holds apart: the
     * read timer is the named `wake`, the return to idle and the deferred
     * republications are arrows. Before D-109 the read timer was a
     * setInterval, which needed no telling apart. */
    setTimeout(fn, ms) {
      timeouts.push({ fn, ms, name: fn.name });
      return timeouts.length;
    },
    clearTimeout(handle) {
      if (handle !== undefined) timeouts[handle - 1] = { cancelled: true };
    },
    NRF: {
      on(event, fn) {
        handlers[event] = fn;
        subscriptions[event] = (subscriptions[event] || 0) + 1;
      },
      setAdvertising(data, opts) {
        const payload = data[0xfcd2];
        if (refuseAdvertising && refuseAdvertising(payload)) {
          throw new Error(`advertising data too long (${payload.length})`);
        }
        advertised.push(payload.slice());
        options.push(opts);
      },
      setServices(services) {
        serviceUuid = Object.keys(services)[0];
        characteristics = services[serviceUuid];
      },
      // Applied, not discarded. A no-op here meant nothing the module published
      // for a central to read was ever looked at by a test -- including a
      // publication that the real stack overwrites a moment later (D-092).
      updateServices(services) {
        const chars = services[serviceUuid] || {};
        for (const uuid of Object.keys(chars)) {
          if (!characteristics[uuid]) characteristics[uuid] = {};
          characteristics[uuid].value = chars[uuid].value;
        }
      },
      getAddress: () => "c8:80:32:ad:f7:b9",
    },
    /* Espruino's own clock, in seconds: the module uses it rather than
     * Date.now(), which costs 240 us a call against 162 (D-106). Held still
     * and moved by hand, so that a test can say what the device's clock did --
     * including going backwards, which froze every read (D-114). */
    getTime: () => clock / 1000,
    E: { getBattery: () => sensors.battery },
    // Physical, like the example it serves: the light sensor reads brighter
    // when the green LED is on, so a write to the light really does move an
    // advertised value.
    Puck: { light: () => (pins["LED2"] ? sensors.light * 2 : sensors.light) },
    LED1: "LED1",
    LED2: "LED2",
    LED3: "LED3",
    digitalWrite(pin, value) {
      pins[pin] = value;
    },
    require(name) {
      if (name === "Storage") return storage;
      if (name === "AESCCM") return cipher;
      if (name !== "BTHome") throw new Error(`unexpected require(${name})`);
      return {
        packetId: 0,
        getAdvertisement(devices) {
          const device = devices[0];
          let object;
          if (device.type === "battery") object = [0x01, Math.round(device.v)];
          else if (device.type === "raw") object = device.v;
          else if (device.type === "illuminance") {
            // Upstream encodes this as b24(5, e, 100): object 0x05, 24-bit
            // little endian, hundredths of a lux.
            const u = Math.round(device.v * 100);
            object = [0x05, u & 255, (u >> 8) & 255, (u >> 16) & 255];
          } else object = [0x1e, device.v ? 1 : 0];
          return { 0xfcd2: [0x40, 0x00, 0x01].concat(object) };
        },
      };
    },
  };

  vm.createContext(context);
  vm.runInContext(source, context);

  return {
    storage,
    advertised,
    /* Move the device's clock, in milliseconds. Negative goes backwards. */
    shiftClock(ms) {
      clock += ms;
    },
    /* The pending read timer, or undefined: at most one is ever armed. */
    get reads() {
      return timeouts.filter((t) => !t.cancelled && t.name === "wake").pop();
    },
    options,
    timers,
    timeouts,
    handlers,
    subscriptions,
    refuse(predicate) {
      refuseAdvertising = predicate;
    },
    /* A central writing to a characteristic, as Espruino really does it.
     *
     * The handler runs first and the written bytes land in the characteristic's
     * own value *after* it returns -- so anything the handler published there
     * is destroyed. The module's counter report was built around this, with a
     * setTimeout and a comment; the entry characteristics were not, and no test
     * could tell, because the fake neither applied updateServices() nor
     * reproduced the overwrite (D-092).
     */
    write(uuid, data) {
      const c = characteristics[uuid];
      if (!c) throw new Error(`no characteristic ${uuid}`);
      if (c.onWrite) c.onWrite({ data });
      c.value = data;
    },
    /* Run every timeout that is still pending, oldest first. */
    flush() {
      let pending = timeouts.filter((t) => !t.cancelled && !t.done);
      while (pending.length) {
        for (const t of pending) {
          t.done = true;
          t.fn();
        }
        pending = timeouts.filter((t) => !t.cancelled && !t.done);
      }
    },
    pins,
    sensors,
    get characteristics() {
      return characteristics;
    },
    get serviceUuid() {
      return serviceUuid;
    },
    context,
  };
}

/* The read timer's delay, to within the clock.

   schedule() reads the clock again after the entries have been read, so the
   delay it arms is the slack less however long that took -- 4 ms on the device,
   where a 30 100 ms deadline measured 30 104 between reads. Asserting it to the
   millisecond made this suite fail about one run in ten. */
function about(actual, expected, label) {
  assert.ok(
    Math.abs(actual - expected) <= 50,
    `${label}: ${actual} should be within 50 ms of ${expected}`
  );
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

  test(`${name}: a write republishes what it changed, and nothing else`, () => {
    /* Anything a write changed that *is* advertised -- a sensor measuring the
     * effect -- must not wait for the next schedule: measured at 18 s on a 10 s
     * interval before that was fixed, against one second for the write itself
     * (D-050). But a write that moved nothing advertised has nothing to
     * rebuild, and rebuilding anyway cost a packet per write (D-106).
     *
     * The second write is where the two part company. By then the device is
     * already advertising fast, so the rate cannot ask for a rebuild: only a
     * moved reading can.
     *
     * And what the first write publishes differs with the device. One whose
     * advertising mirrors the write rebuilds, so the packet is new. One whose
     * advertising does not is only changing its advertising rate, so the bytes
     * on air are handed back unchanged -- same packet id, same counter, which
     * is the repetition BTHome allows (D-108). */
    const result = run(load(name));
    const light = result.characteristics["2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2"];

    const before = result.advertised.length;
    light.onWrite({ data: [0x1e, 0x01] });
    assert.equal(result.advertised.length, before + 1, "the rate moved, if nothing else");
    light.onWrite({ data: [0x1e, 0x00] });
    assert.equal(
      result.advertised.length,
      before + (expected.mirrors ? 2 : 1),
      expected.mirrors
        ? "the light sensor moved with it, so the packet is rebuilt"
        : "nothing advertised moved, so the radio keeps repeating"
    );
    const last = hex(result.advertised[result.advertised.length - 1]);
    const previous = hex(result.advertised[before - 1]);
    if (expected.mirrors) assert.notEqual(last, previous, "a moved reading means a new packet");
    else assert.equal(last, previous, "a rate change means the same packet again");
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

  test(`${name}: the periodic tick rebuilds only when a reading moved`, () => {
    /* There has to be a tick at all: without one the packet is built at setup
     * and never again, and sensor values freeze at their boot readings.
     *
     * But it rebuilds only when a reading has moved. BTHome's own page says the
     * packet id "should be increased on every change in data", that a receiver
     * "should only process the advertisement if the packet id is different
     * compared to the previous one", and that this "allows you to send multiple
     * advertisements that are exactly the same". Rebuilding every interval
     * instead cost ~29 ms of the one thread every second, re-sealed with
     * AES-CCM when encrypted, and left a receiver unable to tell a new reading
     * from a repeat (D-106). */
    const result = run(load(name));

    const wake = result.reads;
    assert.ok(wake, "setup should arm one read timer");
    /* Against the interval the bundle itself just advertised at, not a number
     * written here: an expectation that repeats a value living in the example
     * goes stale the day the example changes, and this one did. Plus the slack
     * D-109 adds, so that the wake lands after the deadline rather than on it. */
    about(wake.ms, result.options[0].interval + 100, "the armed wake");

    const before = result.advertised.length;
    wake.fn();
    assert.equal(
      result.advertised.length,
      before,
      "nothing moved: the radio repeats the packet it holds"
    );

    if (!expected.mirrors) return; // nothing this example reads can move here
    result.sensors.light = 0.5;
    result.reads.fn();
    assert.equal(result.advertised.length, before + 1, "a moved reading is worth a packet");
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

test("a burst of writes rebuilds the packet once, not once per write", () => {
  /* 112 rebuilds for 100 writes, measured on a nice!nano: each one ~29 ms of
   * the single thread, re-sealed with AES-CCM on an encrypted device, and the
   * host never sees it because Espruino acknowledges a write before running
   * onWrite. @enaon reported it as a dimming burst "struggling every one sec"
   * (D-106).
   *
   * The first write moves the advertising rate, which is a real change. The
   * rest change nothing this device advertises, so there is nothing to
   * rebuild. */
  const result = run(load("single-light-standalone.js"));
  const light = result.characteristics["2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2"];

  const before = result.advertised.length;
  for (let i = 0; i < 20; i++) light.onWrite({ data: [0x1e, i % 2] });
  assert.equal(result.advertised.length, before + 1, "one rebuild for twenty writes");
});

test("light-loop puts the sensor and the actuator on different LEDs", () => {
  /* Puck.light() reads through the red LED, so an actuator on LED1 would be
   * measuring itself in the most literal way. The whole point of the example is
   * that the measurement is independent of the command. */
  const source = load("light-loop-standalone.js");
  assert.match(source, /digitalWrite\(LED2/);
  assert.doesNotMatch(source, /digitalWrite\(LED1/);
});

test("light-loop lets the upstream module encode the illuminance", () => {
  /* It used to pack object 0x05 by hand and pass it through the `raw` escape
   * hatch, because upstream had no illuminance type. It has one now, and the
   * examples said otherwise in a comment -- which nobody noticed because this
   * repository's own module cache had frozen the older copy (D-089). Same
   * bytes on the air, one fewer thing for a reader to copy. */
  const result = run(load("light-loop-standalone.js"));
  const packet = hex(result.advertised[0]);
  assert.match(packet, /05a86100/, "illuminance object 0x05, 25000 hundredths");
  assert.doesNotMatch(load("light-loop-standalone.js"), /type: "raw"/);
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

  // Not the read timer, which D-109 also holds as a timeout.
  const pending = result.timeouts.filter((t) => !t.cancelled && t.name !== "wake");
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

/* --- a rate change is not a new packet (D-108) ---------------------------- */

test("a connection changes the rate without building a new packet", () => {
  /* goFast() used to call refreshAdvertising(): a full re-read, re-encode and
   * -- on a sealed device -- a re-seal, 92 ms of the one thread, to alter one
   * field of the advertising options. The radio repeats whatever it was last
   * given, so the bytes already on air are the right bytes to hand back. */
  const result = run(load("single-light-standalone.js"));
  const before = result.advertised[result.advertised.length - 1];
  const idle = result.options[result.options.length - 1].interval;

  result.handlers.connect("aa:bb:cc:dd:ee:ff");

  const after = result.advertised[result.advertised.length - 1];
  assert.deepEqual(after, before, "the same bytes, packet id included");
  assert.ok(result.options[result.options.length - 1].interval < idle, "at the fast rate");
});

test("a sealed device's advertising counter does not move for a rate change", () => {
  /* The counter is inside the sealed payload, so identical bytes prove it did
   * not move -- and a counter that does not move cannot push bthome-ble's
   * _check_encryption_counter forward for an advertisement that says nothing
   * new. BTHome's format allows exactly this repetition. */
  const result = run(load("encrypted-light-standalone.js"));
  const before = result.advertised[result.advertised.length - 1];

  result.handlers.connect("aa:bb:cc:dd:ee:ff");

  assert.deepEqual(result.advertised[result.advertised.length - 1], before);
});

test("the return to idle republishes the same bytes as well", () => {
  const result = run(load("single-light-standalone.js"));
  result.handlers.connect("aa:bb:cc:dd:ee:ff");
  const fast = result.advertised[result.advertised.length - 1];
  const idle = result.options[0].interval;

  result.handlers.disconnect(19);
  const pending = result.timeouts.filter((t) => !t.cancelled);
  pending[pending.length - 1].fn();

  assert.deepEqual(result.advertised[result.advertised.length - 1], fast);
  assert.equal(result.options[result.options.length - 1].interval, idle);
});

test("changing the advertising interval does not build a packet either", () => {
  const result = run(load("single-light-standalone.js"));
  const before = result.advertised[result.advertised.length - 1];

  assert.equal(result.context.bw.setAdvertisingInterval(2500), 2500);

  assert.deepEqual(result.advertised[result.advertised.length - 1], before);
  assert.equal(result.options[result.options.length - 1].interval, 2500);
});

test("a write that moves an advertised value publishes once, at the new rate", () => {
  /* The write turns the light on, which the sensor really does see, so there
   * is a genuine rebuild to do. It must carry the fast rate itself rather than
   * be preceded by a republication of the old bytes: one advertisement, not
   * two (D-108). */
  const result = run(load("light-loop-standalone.js"));
  const idle = result.options[0].interval;
  const uuid = Object.keys(result.characteristics)[0];
  const before = result.advertised.length;

  result.characteristics[uuid].onWrite({ data: [0x1e, 0x01] });

  assert.equal(result.advertised.length, before + 1, "one advertisement");
  const last = result.advertised[result.advertised.length - 1];
  assert.notDeepEqual(last, result.advertised[before - 1], "and it is a new packet");
  assert.ok(result.options[result.options.length - 1].interval < idle, "at the fast rate");
});

test("a write that moves nothing advertised republishes the packet on air", () => {
  const result = run(load("single-light-standalone.js"));
  const idle = result.options[0].interval;
  const uuid = Object.keys(result.characteristics)[0];
  const before = result.advertised[result.advertised.length - 1];
  const count = result.advertised.length;

  result.characteristics[uuid].onWrite({ data: [0x1e, 0x01] });

  assert.equal(result.advertised.length, count + 1, "one advertisement");
  assert.deepEqual(result.advertised[result.advertised.length - 1], before);
  assert.ok(result.options[result.options.length - 1].interval < idle);
});

test("a write while already fast publishes nothing it does not have to", () => {
  const result = run(load("single-light-standalone.js"));
  const uuid = Object.keys(result.characteristics)[0];

  result.handlers.connect("aa:bb:cc:dd:ee:ff");
  const count = result.advertised.length;
  for (let i = 0; i < 5; i++) result.characteristics[uuid].onWrite({ data: [0x1e, i % 2] });

  assert.equal(result.advertised.length, count, "nothing advertised moved, and the rate was already fast");
});

/* --- what a central reads after writing (S4.3, D-092) --------------------- */

test("a write leaves the entry's own value readable, not the write itself", () => {
  /* S4.3: a readable characteristic returns the entry's *current* value. The
   * module published it from inside onWrite, where Espruino destroys it -- the
   * bytes the central wrote land in the characteristic's value after the
   * handler returns. Invisible in plaintext, where the two are usually the same
   * bytes; visible the moment the device does not store what it was sent, and
   * visible on the wire whenever the device is sealed, since a read is sealed
   * under a different direction byte than the write it would be echoing.
   *
   * The counter report at 2FAA1000 was built around this hazard, with a
   * setTimeout and a comment explaining it. The entry characteristics were not
   * (@enaon's report is what sent me looking). */
  const result = run(load("light-loop-standalone.js"));
  let charge = 90;
  result.context.bw.setup({
    advertise: [
      {
        type: "battery",
        set: (v) => {
          charge = Math.min(v, 50); // a device that clamps, which S4.3 allows
        },
        get: () => charge,
      },
    ],
    interval: 1000,
  });
  const uuid = Object.keys(result.characteristics).find((u) =>
    u.toUpperCase().startsWith("2FAA0001")
  );

  result.write(uuid, [0x01, 90]);
  result.flush();

  assert.deepEqual(
    Array.from(result.characteristics[uuid].value),
    [0x01, 50],
    "the characteristic must hold what the device now has, not what was written"
  );
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

  assert.equal(result.context.bw.setAdvertisingInterval(750), 750);
  assert.equal(result.options[result.options.length - 1].interval, 750);
  // The illuminance in this example has interval 0 -- read on every packet --
  // so the next wake follows the new advertising interval (D-109).
  about(result.reads.ms, 750 + 100, "the armed wake");
});

/* --- the read timer wakes for a reason, or not at all (D-109) ------------- */

test("an entry at five minutes does not wake the device every second", () => {
  /* @gfwilliams, merging #765: "`interval` is 1000, so it still wakes up every
   * 1000ms, just to run `tick` which does nothing 299 out of 300 times". It
   * does not any more: the wake is armed from whatever falls due soonest. */
  const result = run(load("single-light-standalone.js"));
  result.context.bw.setup({
    advertise: [{ type: "battery", interval: 300000, get: () => 61 }],
    interval: 1000,
  });

  about(result.reads.ms, 300000 + 100, "one wake per five minutes, not 300");
});

test("a device with nothing to read holds no timer at all", () => {
  /* Its advertising never changes by itself -- there is nothing in it that
   * could -- so a timer could only ever confirm that. */
  const result = run(load("single-light-standalone.js"));
  result.context.bw.setup({
    advertise: [{ type: "light", set: () => {} }],
    interval: 1000,
  });

  assert.equal(result.reads, undefined, "no read timer");
});

test("setup() twice leaves one read timer armed, not two", () => {
  /* `st` is rebuilt by every setup() call, so the previous run's timer handle
   * has to be taken before the assignment. The clearInterval() that used to do
   * it read the *new* state and so cleared nothing: a device being developed on
   * accumulated a timer per setup(), each one calling into whatever state was
   * current. Found by the test below, which expected no timer and found one. */
  const result = run(load("single-light-standalone.js"));
  result.context.bw.setup({
    advertise: [{ type: "battery", interval: 7000, get: () => 61 }],
    interval: 1000,
  });

  const armed = result.timeouts.filter((t) => !t.cancelled && t.name === "wake");
  assert.equal(armed.length, 1, "one read timer");
  about(armed[0].ms, 7100, "the new entry's, not the old one's");
});

test("each wake arms the next one from where the reads landed", () => {
  const result = run(load("single-light-standalone.js"));
  result.context.bw.setup({
    advertise: [{ type: "battery", interval: 4000, get: () => 61 }],
    interval: 1000,
  });

  const first = result.reads;
  about(first.ms, 4100, "the first wake");
  first.fn();
  const second = result.reads;
  assert.notEqual(second, first, "a new timer, not the spent one");
  about(second.ms, 4100, "armed again for the same entry");
});

test("the soonest of several entries is what sets the wake", () => {
  const result = run(load("single-light-standalone.js"));
  result.context.bw.setup({
    advertise: [
      { type: "battery", interval: 300000, get: () => 61 },
      { type: "temperature", interval: 30000, get: () => 21 },
      { type: "illuminance", interval: 0, get: () => 12 },
    ],
    interval: 2000,
  });

  // The illuminance asks to be read on every packet, so it is the soonest and
  // the advertising interval is its period (D-050).
  about(result.reads.ms, 2100, "the soonest entry's wake");
});

test("a write rearms the read timer rather than leaving it to drift", () => {
  const result = run(load("light-loop-standalone.js"));
  const uuid = Object.keys(result.characteristics)[0];
  const before = result.reads;

  result.characteristics[uuid].onWrite({ data: [0x1e, 0x01] });

  const after = result.reads;
  assert.notEqual(after, before, "the write re-read the entries, so the wake moved");
  about(after.ms, result.options[0].interval + 100, "the rearmed wake");
});

test("bw.update() rearms it as well", () => {
  const result = run(load("single-light-standalone.js"));
  const before = result.reads;

  result.context.bw.update();

  assert.notEqual(result.reads, before);
});

test("the fast window can be changed without re-running setup", () => {
  /* The counterpart of setAdvertisingInterval, and the knob a measurement needs:
   * every sample of a first command has to wait this window out before the
   * device is back on its idle interval (docs/measurements.md). */
  const result = run(load("light-loop-standalone.js"));
  const bw = result.context.bw;

  assert.equal(bw.setFastTimeout(3000), 3000);
  result.handlers.connect();
  result.handlers.disconnect();
  const scheduled = result.timeouts[result.timeouts.length - 1];
  assert.equal(scheduled.ms, 3000, "the new window is what gets scheduled");
});

/* --- the advertising counter, across a reboot (D-069) --------------------- */

function advCounterOf(result) {
  /* The counter as transmitted: the last four bytes before the MIC of the
   * sealed service data, little-endian. */
  const sd = result.advertised[result.advertised.length - 1];
  const bytes = sd.slice(sd.length - 8, sd.length - 4);
  return bytes.reduce((n, b, i) => n + b * Math.pow(256, i), 0);
}

test("a sealed device persists its advertising counter", () => {
  /* It used to start at 0 on every boot. Same key, same nonce, different
   * plaintext: the keystream is recoverable, for the whole of the advertising
   * and read directions. The write direction was safe only because the device
   * verifies those itself. */
  const result = run(load("encrypted-light-standalone.js"));

  const mark = result.storage.files[".bwctr"];
  assert.ok(mark, "setup must persist a mark for a keyed device");
  assert.ok(mark.a > 0, `advertising mark should be ahead of the counter, got ${mark.a}`);
  assert.ok(advCounterOf(result) < mark.a, "the counter starts below its mark");
});

test("a reboot resumes the advertising counter above everything it used", () => {
  const first = run(load("encrypted-light-standalone.js"));
  const used = advCounterOf(first);

  // The same flash, a fresh boot.
  const second = run(load("encrypted-light-standalone.js"), first.storage.files);

  assert.ok(
    advCounterOf(second) > used,
    `resumed at ${advCounterOf(second)}, which is not above the ${used} already sent`
  );
});

test("a mark written by earlier firmware still loads", () => {
  /* Before this, the file held the write mark as a bare number. A device being
   * upgraded must not fail to start, and must not resume its write counter
   * below what it had already accepted. */
  const result = run(load("encrypted-light-standalone.js"), { ".bwctr": 5000 });

  assert.equal(result.storage.files[".bwctr"].w, 5000, "the write mark survives");
  assert.ok(advCounterOf(result) >= 0);
});


/* --- the counter report (D-075), off unless asked for ---------------------- */

test("a device does not offer the counter report unless it is turned on", () => {
  /* It is a protocol addition still under discussion, and a device that does
   * not offer it loses nothing that worked before.
   *
   * Asked of `setup()` rather than of the shipped example, which now turns it
   * on deliberately (D-080) -- this test used to read the example's choice and
   * so stopped testing the default the moment that choice changed. */
  const result = run(load("encrypted-light-standalone.js"));
  result.context.bw.setup({
    advertise: [{ type: "light", set: () => {} }],
    interval: 1000,
    bindkey: "231d39c1d7cc1ab1aee224cd096db932",
  });
  const uuids = Object.keys(result.characteristics).map((u) => u.toUpperCase());

  assert.ok(
    !uuids.some((u) => u.startsWith("2FAA1000")),
    `no counter characteristic by default, got ${uuids.join(", ")}`
  );
  assert.ok(uuids.some((u) => u.startsWith("2FAA0001")), "but the entry is there");
});

test("the encrypted example offers the counter report, because it must", () => {
  /* Its device resumes up to 64 counters ahead of the receiver on every reboot
   * (D-078 fault 1), and the receiver now asks by default (D-080). An example
   * that did not answer would demonstrate the silent failure rather than the
   * mechanism. */
  const result = run(load("encrypted-light-standalone.js"));
  const uuids = Object.keys(result.characteristics).map((u) => u.toUpperCase());

  assert.ok(
    uuids.some((u) => u.startsWith("2FAA1000")),
    `expected a counter characteristic, got ${uuids.join(", ")}`
  );
});

test("turning the counter report on adds a characteristic past every entry", () => {
  /* The device answers the one question a receiver cannot answer for itself:
   * what counter am I at? Read back, the answer is sealed and bound to the
   * challenge the receiver just wrote (D-075). */
  const result = run(load("encrypted-light-standalone.js"));
  result.context.bw.setup({
    advertise: [{ type: "light", set: () => {} }],
    interval: 1000,
    bindkey: "231d39c1d7cc1ab1aee224cd096db932",
    counterReport: true,
  });
  const uuids = Object.keys(result.characteristics).map((u) => u.toUpperCase());

  assert.ok(
    uuids.some((u) => u.startsWith("2FAA1000")),
    `expected a counter characteristic, got ${uuids.join(", ")}`
  );
  assert.ok(
    uuids.some((u) => u.startsWith("2FAA0001")),
    "the entries are still there"
  );
});


/* --- what an audit found, and what it would have cost (D-114) ------------- */

test("a reading that throws does not stop the device reading for ever", () => {
  /* The worst of the lot. Under setInterval an exception in the wake was
   * survivable: the timer fired again regardless. A timeout that re-arms
   * itself from inside the work does not, so one throw -- a sensor not ready,
   * a packet the radio refused -- stopped every future read, silently, while
   * the radio went on repeating the last packet. */
  const result = run(load("single-light-standalone.js"));
  const seen = [];
  let broken = false;

  result.context.bw.setup({
    advertise: [
      {
        type: "battery",
        get: () => {
          if (broken) throw new Error("sensor not ready");
          return 61;
        },
      },
    ],
    interval: 1000,
    onError: (e) => seen.push(e.message),
  });

  const first = result.reads;
  broken = true;
  result.shiftClock(1100); // the entry falls due, so the wake really reads
  first.fn();

  assert.deepEqual(seen, ["sensor not ready"], "onError is told");
  assert.notEqual(result.reads, first, "and another wake is armed");
  about(result.reads.ms, 1100, "retried at the advertising interval");
});

test("a setup() that throws leaves the running device alone", () => {
  /* The new state is built before the old one's timers are disarmed, because
   * everything in it can throw: a packet that does not fit, an entry without a
   * length, an interval out of range. Disarming first left a device that was
   * working with no timer at all, still advertising, frozen. */
  const result = run(load("single-light-standalone.js"));
  const armed = result.reads;
  const entries = result.context.bw.plan().entryIds;

  assert.throws(
    () =>
      result.context.bw.setup({
        advertise: [{ id: 0x3a, set: () => {} }], // no length, and not variable
        interval: 1000,
      }),
    (error) => error.code === "writable_without_length"
  );

  assert.equal(result.reads, armed, "the old timer is still the armed one");
  assert.deepEqual(result.context.bw.plan().entryIds, entries, "and the old plan stands");
});

test("a clock that moves backwards does not stop the reads", () => {
  /* `getTime()` is the wall clock. A setTime() or an RTC resynchronising
   * leaves lastRead in the future, where nothing is ever due again and the
   * next wake is armed for the length of the jump. */
  const result = run(load("single-light-standalone.js"));
  const idle = result.options[0].interval;

  result.reads.fn(); // an ordinary wake, which stamps lastRead
  result.shiftClock(-900000); // a quarter of an hour backwards
  result.reads.fn();

  about(result.reads.ms, idle + 100, "one interval away, not one jump away");
});

test("a set() that throws is reported, not thrown into the Bluetooth stack", () => {
  /* Espruino has already acknowledged the write, so onError is the only place
   * a device's own failure can show. It was not being told: the exception went
   * up into the stack's own onWrite callback, taking the re-read with it and
   * leaving the characteristic holding the bytes the central wrote (D-092). */
  const result = run(load("single-light-standalone.js"));
  const seen = [];

  result.context.bw.setup({
    advertise: [
      {
        type: "light",
        get: () => false,
        set: () => {
          throw new Error("bus busy");
        },
      },
    ],
    interval: 1000,
    onError: (e) => seen.push(e.message),
  });

  const uuid = Object.keys(result.characteristics)[0];
  assert.doesNotThrow(() => result.characteristics[uuid].onWrite({ data: [0x1e, 0x01] }));
  assert.deepEqual(seen, ["bus busy"]);
});

test("a refused first packet still leaves a device that reads", () => {
  /* The fallback packet exists so that a device whose advertising was refused
   * can still be found and connected to (D-022, D-029). It was only half the
   * job: setup() threw before arming the timer, so the device that could be
   * reached would never read a sensor again. */
  const result = run(load("single-light-standalone.js"));
  result.refuse((payload) => payload.length > 4);

  assert.throws(
    () =>
      result.context.bw.setup({
        advertise: [{ type: "battery", get: () => 61 }],
        interval: 1000,
      }),
    (error) => error.code === "advertising_rejected"
  );

  assert.ok(result.reads, "a read timer is armed anyway");
  assert.equal(typeof result.handlers.connect, "function", "and a connection is still handled");
});

test("bw.update() re-reads every sensor, not only the ones that are due", () => {
  /* It publishes with a new packet id, which is what tells a receiver the data
   * is new. Skipping the entries whose interval had not elapsed meant
   * publishing values it had not re-read, under an id that says they are
   * fresh: worse than not publishing at all. */
  const result = run(load("single-light-standalone.js"));
  let battery = 90;

  result.context.bw.setup({
    advertise: [{ type: "battery", interval: 300000, get: () => battery }],
    interval: 1000,
  });

  const before = result.advertised.length;
  battery = 42;
  result.context.bw.update();

  assert.equal(result.advertised.length, before + 1, "it published");
  const last = result.advertised[result.advertised.length - 1];
  assert.ok(last.includes(42), `expected the value it just read, got ${hex(last)}`);
});

/* --- the same defects, on a sealed device ---------------------------------- */

/* The six above all run in clear, which proves the shared paths and nothing
   about the one mode where a stopped device is hardest to notice: a sealed
   device that froze goes on repeating a packet under a counter the receiver
   has already accepted, so there is no plaintext for anyone downstream to find
   stale. Five of the six are reachable with a key; the sixth is not, because
   the stub cipher here cannot open a write (decrypt() returns null by design),
   and the sealed write path is held to the shared vectors in ccm.test.js and
   vectors.test.js instead.

   The stub's encrypt() hands its plaintext back, which is what lets these
   tests read a value out of sealed service data. */

test("a sealed reading that throws does not stop the device reading for ever", () => {
  const result = run(load("encrypted-light-standalone.js"));
  const seen = [];
  let broken = false;

  result.context.bw.setup({
    advertise: [
      {
        type: "illuminance",
        get: () => {
          if (broken) throw new Error("sensor not ready");
          return 12;
        },
      },
      { type: "light", set: () => {} },
    ],
    interval: 1000,
    maxServiceData: 20,
    showName: false,
    bindkey: "231d39c1d7cc1ab1aee224cd096db932",
    onError: (e) => seen.push(e.message),
  });

  const first = result.reads;
  const spent = advCounterOf(result);
  broken = true;
  result.shiftClock(1100); // the entry falls due, so the wake really reads
  first.fn();

  assert.deepEqual(seen, ["sensor not ready"], "onError is told");
  assert.notEqual(result.reads, first, "and another wake is armed");
  about(result.reads.ms, 1100, "retried at the advertising interval");
  assert.equal(advCounterOf(result), spent, "no counter spent on a packet never built");
});

test("a sealed setup() that cannot fit leaves the running device alone", () => {
  /* Encryption is where this is likeliest: the counter and the MIC spend eight
     of the bytes, so an entry list that fits in clear is refused sealed, and
     S2.4 has that refused at setup rather than in the field. Which makes the
     sealed device the one most likely to meet the defect: disarming the old
     timers before the new plan was known to work left it advertising, frozen
     and with no timer at all. */
  const result = run(load("encrypted-light-standalone.js"));
  const armed = result.reads;
  const entries = result.context.bw.plan().entryIds;
  const tooBigSealed = {
    advertise: [
      { type: "illuminance", get: () => 12 },
      { type: "illuminance", get: () => 34 },
      { type: "light", set: () => {} },
    ],
    interval: 1000,
    maxServiceData: 20,
    showName: false,
  };

  assert.throws(
    () => result.context.bw.setup(Object.assign({ bindkey: "231d39c1d7cc1ab1aee224cd096db932" }, tooBigSealed)),
    (error) => error.code === "capacity_exceeded"
  );

  assert.equal(result.reads, armed, "the old timer is still the armed one");
  assert.deepEqual(result.context.bw.plan().entryIds, entries, "and the old plan stands");
  // The same entries in clear, where those eight bytes are not spent, fit:
  // the refusal above really is the encryption and not the entry list.
  assert.doesNotThrow(() => result.context.bw.setup(tooBigSealed));
});

test("a sealed device's clock moving backwards does not stop the reads", () => {
  /* The entry needs an interval of its own. The shipped example's is
     `interval: 0` -- read at the advertising rate -- and renderServiceData
     reads such an entry on every wake without asking whether it is due, which
     stamps lastRead back into the present and hides the whole case. An entry
     with an interval is the one that gets skipped, and so the one left with a
     lastRead in the future. */
  const result = run(load("encrypted-light-standalone.js"));
  result.context.bw.setup({
    advertise: [
      { type: "illuminance", interval: 300000, get: () => 12 },
      { type: "light", set: () => {} },
    ],
    interval: 1000,
    maxServiceData: 20,
    showName: false,
    bindkey: "231d39c1d7cc1ab1aee224cd096db932",
  });

  result.reads.fn(); // an ordinary wake, which stamps lastRead
  result.shiftClock(-900000); // a quarter of an hour backwards
  result.reads.fn();

  about(result.reads.ms, 300100, "one interval away, not one jump away");
});

test("a sealed device whose first packet is refused still reads", () => {
  /* The fallback is sealed (see the next section), so the device can be found
     and connected to. It also has to be a device that still works. */
  const result = run(load("encrypted-light-standalone.js"));
  result.refuse((payload) => payload.length > 14);

  assert.throws(
    () =>
      result.context.bw.setup({
        advertise: [
          { type: "illuminance", get: () => 12 },
          { type: "light", set: () => {} },
        ],
        interval: 1000,
        maxServiceData: 20,
        showName: false,
        bindkey: "231d39c1d7cc1ab1aee224cd096db932",
      }),
    (error) => error.code === "advertising_rejected"
  );

  assert.ok(result.reads, "a read timer is armed anyway");
  assert.equal(typeof result.handlers.connect, "function", "and a connection is still handled");
  const published = result.advertised[result.advertised.length - 1];
  assert.equal(published[0] & 1, 1, "and what went out instead is still sealed");
});

test("bw.update() on a sealed device re-reads and spends a new counter", () => {
  /* A new packet id under a new counter says, as loudly as BTHome can, that
     these values are new. Publishing values it had not re-read made that a
     lie no receiver can detect. */
  const result = run(load("encrypted-light-standalone.js"));
  let lux = 90;

  result.context.bw.setup({
    advertise: [
      { type: "illuminance", interval: 300000, get: () => lux },
      { type: "light", set: () => {} },
    ],
    interval: 1000,
    maxServiceData: 20,
    showName: false,
    bindkey: "231d39c1d7cc1ab1aee224cd096db932",
  });

  const spent = advCounterOf(result);
  lux = 42;
  result.context.bw.update();

  const published = hex(result.advertised[result.advertised.length - 1]);
  assert.ok(advCounterOf(result) > spent, "a counter it had not used before");
  // illuminance is 0x05 and hundredths of a lux, little-endian: 4200 = 0x1068.
  assert.ok(published.includes("05681000"), `expected 42 lux, got ${published}`);
  assert.ok(!published.includes("05282300"), `still carrying 90 lux: ${published}`);
});

/* --- the safety net, and the stack we subscribe to (D-088) ----------------- */

test("the fallback packet is sealed when the device has a key", () => {
  /* When the radio refuses the real packet the module publishes a tiny one
   * instead, because a device that is not advertising cannot be connected to
   * and so cannot be fixed over the air. That packet kept the "encrypted" bit
   * of the device-information byte while carrying plaintext, so every receiver
   * failed to authenticate it and concluded the key was wrong -- and Home
   * Assistant now asks the user to re-enter a key that was never at fault. */
  const result = run(load("encrypted-light-standalone.js"));
  const before = result.advertised.length;

  // Refuse anything but a short packet, which is the situation the net is for.
  result.refuse((payload) => payload.length > 14);
  // It publishes the fallback and then re-throws, so the caller learns its
  // real packet did not fit.
  assert.throws(() => result.context.bw.update(), { code: "advertising_rejected" });

  const published = result.advertised[result.advertised.length - 1];
  assert.ok(result.advertised.length > before, "something was still published");
  assert.ok(published.length > 3, `sealed, got ${published.length} bytes`);
  assert.equal(published[0] & 1, 1, "and still says it is encrypted");
});

test("a plain device's fallback packet stays plain", () => {
  const result = run(load("single-light-standalone.js"));
  const before = result.advertised.length;

  result.refuse((payload) => payload.length > 6);
  assert.throws(() => result.context.bw.update(), { code: "advertising_rejected" });

  const published = result.advertised[result.advertised.length - 1];
  assert.ok(result.advertised.length > before);
  assert.equal(published.length, 3, "device info, packet id, and nothing else");
  assert.equal(published[0] & 1, 0);
});

test("setup() twice subscribes to the radio once", () => {
  /* A device being developed on is a device whose setup() runs again and
   * again. Each run used to stack another reaction onto every connection. */
  const result = run(load("single-light-standalone.js"));
  assert.equal(result.subscriptions.connect, 1);

  result.context.bw.setup({
    advertise: [{ type: "light", set: () => {} }],
    interval: 1000,
  });

  assert.equal(result.subscriptions.connect, 1, "not two");
  assert.equal(result.subscriptions.disconnect, 1);
});

test("a write to an entry the current setup() does not declare is refused", () => {
  /* D-114. setup() declares the GATT service only when the new plan has a
   * writable entry, so a run that has none leaves the previous run's
   * characteristics registered, with an onWrite that still captures the entry
   * number. The write then found no entry and the *error path itself* threw a
   * TypeError on `w.readable`, inside the Bluetooth stack's own callback. */
  const result = run(load("single-light-standalone.js"));
  const uuid = Object.keys(result.characteristics)[0];
  const seen = [];

  result.context.bw.setup({
    advertise: [{ type: "light", get: () => false }], // nothing writable now
    interval: 1000,
    onError: (e) => seen.push(e.code),
  });

  assert.doesNotThrow(() => result.write(uuid, [0x1e, 0x01]));
  assert.deepEqual(seen, ["entry_not_declared"]);
});

test("a bindkey given as an array is checked for length, like the hex form", () => {
  /* D-114. `[1,2,3]` was accepted, and every receiver then reported a key that
   * is not at fault -- the false diagnosis D-088 exists to remove. */
  const result = run(load("single-light-standalone.js"));

  assert.throws(
    () =>
      result.context.bw.setup({
        advertise: [{ type: "light", set: () => {} }],
        interval: 1000,
        bindkey: [1, 2, 3],
      }),
    { code: "bindkey_length" }
  );
});

test("a bindkey of the right length that is not hexadecimal is refused", () => {
  /* `parseInt` stops at the first character it cannot read rather than failing,
   * so "2z" is 2 and a key with a typo in it was silently a different key. Every
   * receiver then reported a key that is not at fault, which is the same false
   * diagnosis D-088 and D-114 were written to remove. */
  const result = run(load("single-light-standalone.js"));

  assert.throws(
    () =>
      result.context.bw.setup({
        advertise: [{ type: "light", set: () => {} }],
        interval: 1000,
        bindkey: "231d39c1d7cc1ab1aee224cd096db9zz",
      }),
    { code: "bindkey_not_hex" }
  );
  // And the 32 characters that are hexadecimal still are, upper case included.
  result.context.bw.setup({
    advertise: [{ type: "light", set: () => {} }],
    interval: 1000,
    bindkey: "231D39C1D7CC1AB1AEE224CD096DB932",
  });
});

test("a connection whose advertising is refused does not throw into the stack", () => {
  /* goFast() rebuilds the advertising, and that can fail. The failure used to
   * land inside the Bluetooth stack's own callback, where nothing is prepared
   * to catch it; it belongs in the device's own onError. */
  const seen = [];
  const result = run(load("single-light-standalone.js"));
  result.context.bw.setup({
    advertise: [{ type: "light", set: () => {} }],
    interval: 1000,
    onError: (e) => seen.push(e.code),
  });

  // Refuse the real packet but not the fallback, which is the case the net is
  // for -- refusing both leaves the module nothing to report but the radio's
  // own error.
  result.refuse((payload) => payload.length > 4);
  assert.doesNotThrow(() => result.handlers.connect("aa:bb:cc:dd:ee:ff"));
  assert.deepEqual(seen, ["advertising_rejected"]);
});

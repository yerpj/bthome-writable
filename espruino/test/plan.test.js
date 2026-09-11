"use strict";

/* T1.1 — the module's packet planning and write handling, without hardware.
 *
 * `planPacket` and `renderServiceData` take the object encoder as an argument
 * precisely so this file can supply a fake one: the real encoder wraps the
 * upstream BTHome module, which needs Espruino. The fake mirrors that module's
 * encodings for the three types the MVP uses.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const bw = require("../BTHomeWritable.js");

const FIXTURES = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "spec", "advertising-fixtures.json"),
    "utf8"
  )
).fixtures;

/* Stands in for the upstream BTHome module's encoding tables. */
function fakeEncodeOne(entry, value) {
  switch (entry.type) {
    case "battery":
      return [0x01, Math.round(value)];
    case "light":
      return [0x1e, value ? 1 : 0];
    case "temperature": {
      const v = Math.round(value * 100);
      return [0x02, v & 255, (v >> 8) & 255];
    }
    case "text": {
      const text = "" + value;
      const bytes = [0x53, text.length];
      for (let i = 0; i < text.length; i++) bytes.push(text.charCodeAt(i));
      return bytes;
    }
    default:
      throw new Error("unknown type " + entry.type);
  }
}

function bytesToHex(bytes) {
  return bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
}

function fixture(name) {
  return FIXTURES.find((f) => f.name === name);
}

test("an entry is writable iff it has set()", () => {
  const entries = [
    { type: "battery", get: () => 97 },
    { type: "light", get: () => true, set: () => {} },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);

  // Position 0 is the packet id, so the light sits at position 2.
  assert.deepEqual(plan.writablePositions, [2]);
  assert.deepEqual(plan.layout, [{ id: 0x1e, length: 1, entryIndex: 1 }]);
});

test("the module reproduces the espruino-single-light fixture byte for byte", () => {
  const expected = fixture("espruino-single-light");
  const entries = [
    { type: "battery", get: () => 97 },
    { type: "light", get: () => true, set: () => {} },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  const serviceData = bw.renderServiceData(plan, 9, fakeEncodeOne, entries);

  assert.equal(bytesToHex(serviceData), expected.service_data);
  assert.deepEqual(plan.writablePositions, expected.declaration.writable_positions);
});

test("the module reproduces the espruino-multi-instance fixture", () => {
  const expected = fixture("espruino-multi-instance");
  const states = [true, false, true];
  const entries = [{ type: "battery", get: () => 97 }].concat(
    states.map((on, index) => ({
      type: "light",
      get: () => states[index],
      set: (v) => {
        states[index] = v;
      },
    }))
  );

  const plan = bw.planPacket(entries, fakeEncodeOne);
  const serviceData = bw.renderServiceData(plan, 10, fakeEncodeOne, entries);

  assert.equal(bytesToHex(serviceData), expected.service_data);
  assert.deepEqual(plan.writablePositions, [2, 3, 4]);
});

test("equal object IDs keep their declared order through the sort", () => {
  /* Multi-instance is the whole reason the sort must be stable: the declared
   * order IS the addressing scheme (§2.1). An unstable sort would silently
   * permute which light a bit refers to. */
  const marks = [];
  const entries = [];
  for (let i = 0; i < 5; i++) {
    entries.push({
      type: "light",
      get: () => i % 2 === 0,
      set: () => marks.push(i),
    });
  }
  const plan = bw.planPacket(entries, fakeEncodeOne);
  assert.deepEqual(
    plan.layout.map((l) => l.entryIndex),
    [0, 1, 2, 3, 4]
  );
});

test("objects are sorted into ascending object-ID order", () => {
  /* bthome-ble warns at WARNING level otherwise, and the declaration must end
   * up last, which ascending order gives for free since 0xFF is the highest. */
  const entries = [
    { type: "text", writeOnly: true, set: () => {} },
    { type: "light", get: () => true, set: () => {} },
    { type: "battery", get: () => 97 },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  const serviceData = bw.renderServiceData(plan, 1, fakeEncodeOne, entries);

  // 40 | 00 01 | 01 61 | 1e 01 | 53 00 | ff <mask>
  assert.equal(bytesToHex(serviceData), "40000101611e015300ff0c");
  assert.equal(serviceData[serviceData.length - 2], bw.DECLARATION_OBJECT_ID);
});

test("a write-only object advertises an empty placeholder, never its value", () => {
  /* §3: the device does not advertise what was written. */
  let displayed = null;
  const entries = [
    { type: "battery", get: () => 88 },
    {
      type: "text",
      writeOnly: true,
      set: (t) => {
        displayed = t;
      },
    },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);

  const before = bw.renderServiceData(plan, 1, fakeEncodeOne, entries);
  entries[1].set("hello");
  const after = bw.renderServiceData(plan, 1, fakeEncodeOne, entries);

  assert.equal(displayed, "hello");
  assert.equal(bytesToHex(before), bytesToHex(after));
  assert.ok(bytesToHex(after).includes("5300"), "the placeholder stays empty");
});

test("more than eight writable objects is refused at setup", () => {
  const entries = [];
  for (let i = 0; i < 9; i++) {
    entries.push({ type: "light", get: () => false, set: () => {} });
  }
  assert.throws(
    () => bw.planPacket(entries, fakeEncodeOne),
    (error) => error.code === "too_many_writable"
  );
});

test("an over-budget packet is refused at setup, not at write time", () => {
  /* §2.3: a device that discovers this while deployed is a device in the
   * field. Eleven temperature objects are 33 bytes on their own. */
  const entries = [];
  for (let i = 0; i < 11; i++) {
    entries.push({ type: "temperature", get: () => 22.1 });
  }
  assert.throws(
    () => bw.planPacket(entries, fakeEncodeOne),
    (error) => error.code === "capacity_exceeded"
  );
});

test("set() without get() is write-only, without having to say so", () => {
  /* Gordon's rule from espruino#8013: an entry that can be written but not read
   * has nothing to advertise, so the module should not make the sketch declare
   * what it can see. Before this, such an entry threw a TypeError on the
   * missing get(). */
  const entries = [{ type: "text", set: () => {} }];
  const plan = bw.planPacket(entries, fakeEncodeOne);

  assert.equal(plan.ordered[0].writeOnly, true);
  // 40 | 00 01 | 53 00 | ff 02 -- a zero-length placeholder, not a value.
  assert.equal(
    bytesToHex(bw.renderServiceData(plan, 1, fakeEncodeOne, entries)),
    "4000015300ff02"
  );
});

test("an explicit writeOnly still hides a value the device could report", () => {
  /* The derivation covers "cannot be read"; the flag stays for "could be read
   * but should not be" -- a display whose contents are nobody else's business. */
  const entries = [{ type: "text", writeOnly: true, get: () => "secret", set: () => {} }];
  const plan = bw.planPacket(entries, fakeEncodeOne);

  assert.equal(plan.ordered[0].writeOnly, true);
  assert.equal(
    bytesToHex(bw.renderServiceData(plan, 1, fakeEncodeOne, entries)),
    "4000015300ff02"
  );
});

test("writeOnly without set() is a configuration error", () => {
  assert.throws(
    () => bw.planPacket([{ type: "text", writeOnly: true }], fakeEncodeOne),
    (error) => error.code === "write_only_without_set"
  );
});

test("an entry with neither get() nor set() is a configuration error", () => {
  assert.throws(
    () => bw.planPacket([{ type: "battery" }], fakeEncodeOne),
    (error) => error.code === "entry_without_accessor"
  );
});

test("a device with nothing writable advertises no declaration", () => {
  const entries = [{ type: "battery", get: () => 97 }];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  const serviceData = bw.renderServiceData(plan, 3, fakeEncodeOne, entries);

  assert.deepEqual(plan.writablePositions, []);
  assert.equal(bytesToHex(serviceData), "4000030161");
  assert.ok(!serviceData.includes(bw.DECLARATION_OBJECT_ID));
});

test("a write applies its values and the packet then reflects them", () => {
  /* The round trip the whole protocol exists for. */
  const expected = fixture("espruino-single-light");
  let on = true;
  const entries = [
    { type: "battery", get: () => 97 },
    {
      type: "light",
      get: () => on,
      set: (v) => {
        on = v;
      },
    },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  const write = expected.writes[0];

  const payload = [];
  for (let i = 0; i < write.payload.length; i += 2) {
    payload.push(parseInt(write.payload.substr(i, 2), 16));
  }

  const parsed = bw.parseWrite(payload, plan.layout);
  entries[plan.layout[0].entryIndex].set(parsed[0].value[0] !== 0);

  assert.equal(on, false);
  const after = bw.renderServiceData(plan, 10, fakeEncodeOne, entries);
  assert.equal(bytesToHex(after), "40000a01611e00ff04");
});

test("get() returning a value that changes the object ID is caught", () => {
  /* A packet whose layout shifts under the receiver would silently redirect
   * every subsequent write. Better to fail loudly. */
  const entries = [{ type: "light", get: () => true, set: () => {} }];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  entries[0].type = "battery";

  assert.throws(
    () => bw.renderServiceData(plan, 1, fakeEncodeOne, entries),
    (error) => error.code === "layout_drift"
  );
});

test("each entry can be read on its own schedule", () => {
  /* The advertising interval is the ceiling on how often anything can be
   * perceived to change; a slow sensor need not be read that often. A battery
   * does not need re-measuring as often as a light sensor, and on some devices
   * a reading costs real power. */
  const reads = { battery: 0, light: 0 };
  const entries = [
    {
      type: "battery",
      interval: 60000,
      get: () => {
        reads.battery += 1;
        return 90;
      },
    },
    {
      type: "temperature",
      get: () => {
        reads.light += 1;
        return 22.1;
      },
    },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  reads.battery = 0;
  reads.light = 0;

  // Six advertising intervals of 2 s each. planPacket already took one
  // reading of each, so within the battery's minute nothing is re-read.
  for (let t = 0; t <= 10000; t += 2000) {
    bw.renderServiceData(plan, 1, fakeEncodeOne, entries, t);
  }
  assert.equal(reads.light, 6, "no interval means read on every packet");
  assert.equal(reads.battery, 0, "still inside its interval");

  bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 60000);
  assert.equal(reads.battery, 1, "and read again once the minute is up");
});

test("a cached reading still goes out in every packet", () => {
  /* Skipping the read must not skip the object: a receiver has to keep seeing
   * the value, just not a fresher one. */
  const entries = [{ type: "battery", interval: 60000, get: () => 90 }];
  const plan = bw.planPacket(entries, fakeEncodeOne);

  const first = bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 0);
  const later = bw.renderServiceData(plan, 2, fakeEncodeOne, entries, 5000);

  // Same battery object either side; only the packet id moves.
  assert.equal(bytesToHex(first), "4000010" + "15a");
  assert.equal(bytesToHex(later), "4000020" + "15a");
});

test("a writable entry ignores any read interval", () => {
  /* Otherwise a write could be confirmed with a value read before it, which
   * would look exactly like the device refusing the write. */
  let reads = 0;
  let on = false;
  const entries = [
    {
      type: "light",
      interval: 60000,
      get: () => {
        reads += 1;
        return on;
      },
      set: (v) => {
        on = v;
      },
    },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  reads = 0;

  bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 0);
  on = true;
  const after = bw.renderServiceData(plan, 2, fakeEncodeOne, entries, 10);

  assert.equal(reads, 2, "read every time despite the interval");
  assert.ok(bytesToHex(after).endsWith("ff02"), "declaration still last");
  assert.ok(bytesToHex(after).includes("1e01"), "the new value is advertised");
});

test("an entry with no interval follows the advertising interval", () => {
  /* The default is inheritance, not "read every time": a sensor should not be
   * read more often than its value could possibly be perceived, and the extra
   * packet build that follows a write must not drag a slow sensor with it. */
  let reads = 0;
  const entries = [
    {
      type: "battery",
      get: () => {
        reads += 1;
        return 90;
      },
    },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne, 2000);
  reads = 0;

  // The extra build right after a write, well inside the interval.
  bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 100);
  assert.equal(reads, 0, "a write must not trigger a sensor read");

  bw.renderServiceData(plan, 2, fakeEncodeOne, entries, 2000);
  assert.equal(reads, 1, "but the advertising interval does");
});

test("interval 0 means read on every build, including after a write", () => {
  /* Worth it only for a value that must be fresh in the confirmation and is
   * cheap enough to read there -- which is exactly the light-loop example. */
  let reads = 0;
  const entries = [
    {
      type: "battery",
      interval: 0,
      get: () => {
        reads += 1;
        return 90;
      },
    },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne, 2000);
  reads = 0;

  bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 100);
  bw.renderServiceData(plan, 2, fakeEncodeOne, entries, 150);
  assert.equal(reads, 2);
});

test("a named interval is not overridden by the advertising interval", () => {
  let reads = 0;
  const entries = [
    {
      type: "battery",
      interval: 60000,
      get: () => {
        reads += 1;
        return 90;
      },
    },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne, 500);
  reads = 0;

  for (let t = 500; t <= 10000; t += 500) {
    bw.renderServiceData(plan, 1, fakeEncodeOne, entries, t);
  }
  assert.equal(reads, 0, "a minute has not passed");
});

test("an encrypted plan advertises 0x41 and pays for it in budget", () => {
  /* §5.3: the counter and MIC come out of the same 24 service-data bytes, so an
   * encrypted device has 8 fewer for objects. Checked at setup rather than on
   * the air, as §2.3 requires. */
  const entries = [
    { type: "battery", get: () => 97 },
    { type: "light", get: () => true, set: () => {} },
  ];
  const plain = bw.planPacket(entries, fakeEncodeOne, 0, false);
  const sealed = bw.planPacket(entries, fakeEncodeOne, 0, true);

  assert.equal(plain.info, bw.DEVICE_INFO_PLAIN);
  assert.equal(sealed.info, bw.DEVICE_INFO_ENCRYPTED);
  assert.equal(plain.budget - sealed.budget, 8);
});

test("a packet that fits in the clear can be too big once encrypted", () => {
  /* The failure this guards against is a device that works unencrypted, has a
   * bindkey added, and starts truncating its own layout on the air. */
  // 8 two-byte objects plus the packet id and the device-info byte: 19 bytes,
  // comfortable in the clear and over the 16 an encrypted device has.
  const entries = [];
  for (let i = 0; i < 8; i++) {
    entries.push({ type: "battery", get: () => 97 });
  }
  assert.doesNotThrow(() => bw.planPacket(entries, fakeEncodeOne, 0, false));
  assert.throws(
    () => bw.planPacket(entries, fakeEncodeOne, 0, true),
    (error) => error.code === "capacity_exceeded"
  );
});

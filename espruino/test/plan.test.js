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

"use strict";

/* The module's packet planning, writable entries and value decoding, without
 * hardware (PROTOCOL.md v2).
 *
 * `planPacket` and `renderServiceData` take the object encoder as an argument
 * precisely so this file can supply a fake one: the real encoder wraps the
 * upstream BTHome module, which needs Espruino. The fake mirrors that module's
 * encodings, including how it wraps negative numbers.
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

/* The upstream module's helper: round, then take the low bytes. Negative values
 * wrap the same way whatever the object's signedness, which is why the module
 * cannot be probed for sign. */
function le(id, value, factor, bytes) {
  const v = Math.round(value * factor);
  const out = [id];
  for (let i = 0; i < bytes; i++) out.push((v >> (8 * i)) & 255);
  return out;
}

/* Stands in for the upstream BTHome module's encoding tables. */
function fakeEncodeOne(entry, value) {
  switch (entry.type) {
    case "battery":
      return [0x01, Math.round(value)];
    case "temperature":
      return le(0x02, value, 100, 2);
    case "power":
      return [0x10, value ? 1 : 0];
    case "moisture":
      return le(0x14, value, 100, 2);
    case "light":
      return [0x1e, value ? 1 : 0];
    case "temperature8":
      return le(0x57, value, 1, 1);
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

const noop = () => {};

test("get only is a sensor; set makes an entry writable", () => {
  const plan = bw.planPacket(
    [
      { type: "battery", get: () => 97 },
      { type: "light", set: noop },
    ],
    fakeEncodeOne
  );
  assert.equal(plan.ordered.length, 1);
  assert.deepEqual(plan.entryIds, [0x1e]);
  assert.equal(plan.writable[0].entry, 1);
  assert.equal(plan.writable[0].readable, false);
  assert.equal(plan.settingsRevision, false);
});

test("the module reproduces the single-light fixture byte for byte", () => {
  const plan = bw.planPacket(
    [
      { type: "battery", get: () => 97 },
      { type: "light", set: noop },
    ],
    fakeEncodeOne
  );
  const built = bw.renderServiceData(plan, 9, null);
  assert.equal(bytesToHex(built), fixture("single-light").service_data);
});

test("the module reproduces the two-lights-and-display fixture", () => {
  const plan = bw.planPacket(
    [
      { type: "light", set: noop },
      { type: "light", set: noop },
      { type: "text", set: noop },
    ],
    fakeEncodeOne
  );
  const built = bw.renderServiceData(plan, 9, null);
  assert.equal(bytesToHex(built), fixture("two-lights-and-display").service_data);
});

test("the module reproduces the thermostat fixture, settings revision included", () => {
  /* A measured temperature, and two writable entries that can change by
   * themselves: `get` makes them readable, and that makes the device advertise
   * its settings revision (PROTOCOL.md §3.2). */
  const plan = bw.planPacket(
    [
      { type: "temperature", get: () => 25.0 },
      { type: "power", get: () => true, set: noop },
      { type: "temperature8", get: () => 20, set: noop },
    ],
    fakeEncodeOne
  );
  assert.equal(plan.settingsRevision, true);
  const built = bw.renderServiceData(plan, 9, null, null, 0, 3);
  assert.equal(bytesToHex(built), fixture("thermostat").service_data);
});

test("a writable value is never advertised, whatever it is set to", () => {
  /* §2.3: state is not in the packet. Only the packet id moves. */
  let on = false;
  const entries = [
    { type: "battery", get: () => 90 },
    { type: "light", get: () => on, set: (v) => { on = v; } },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  const before = bytesToHex(bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 0, 5));
  on = true;
  const after = bytesToHex(bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 0, 5));
  assert.equal(before, after);
  assert.ok(!after.includes("1e01"), "the light's state must not be in the packet");
});

test("characteristics are numbered from 1 in entry order, in hexadecimal", () => {
  /* §4.1: entry 10 is 2FAA000A, not 2FAA0010. */
  assert.equal(bw.characteristicUuid(1), "2FAA0001-3B0B-4B1A-9E2A-B4C2952E62F2");
  assert.equal(bw.characteristicUuid(10), "2FAA000A-3B0B-4B1A-9E2A-B4C2952E62F2");
  assert.equal(bw.SERVICE_UUID, "2FAA0000-3B0B-4B1A-9E2A-B4C2952E62F2");

  const plan = bw.planPacket(
    Array.from({ length: 12 }, () => ({ type: "light", set: noop })),
    fakeEncodeOne
  );
  assert.equal(plan.writable[9].uuid, bw.characteristicUuid(10));
  const expected = fixture("twelve-lights").declaration.characteristics;
  plan.writable.forEach((w, i) => assert.equal(w.uuid.toLowerCase(), expected[i].uuid));
});

test("the module reproduces the twelve-lights fixture: no eight-entry limit", () => {
  const plan = bw.planPacket(
    Array.from({ length: 12 }, () => ({ type: "light", set: noop })),
    fakeEncodeOne
  );
  assert.equal(bytesToHex(bw.renderServiceData(plan, 1, null)), fixture("twelve-lights").service_data);
});

test("sensor objects sort ascending, equal IDs keep their order, declaration last", () => {
  const entries = [
    { type: "light", get: () => true },
    { type: "battery", get: () => 50 },
    { type: "light", get: () => false },
    { type: "power", set: noop },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  // 40 | 00 01 | 01 32 | 1e 01 | 1e 00 | ff 10
  assert.equal(bytesToHex(bw.renderServiceData(plan, 1, null)), "4000010132" + "1e011e00" + "ff10");
});

test("the settings revision sorts into place before the declaration", () => {
  const entries = [
    { type: "moisture", get: () => 42.5 },
    { type: "light", get: () => false, set: noop },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  // 40 | 00 01 | 14 9a 10 | 65 07 | ff 1e
  assert.equal(bytesToHex(bw.renderServiceData(plan, 1, null, null, 0, 7)), "400001149a106507ff1e");
});

test("a device with nothing writable advertises no declaration", () => {
  const plan = bw.planPacket([{ type: "battery", get: () => 60 }], fakeEncodeOne);
  assert.equal(bytesToHex(bw.renderServiceData(plan, 1, null)), "40000101" + "3c");
});

test("writable specs: binary, signed and unsigned numbers, text, explicit events", () => {
  const light = bw.writableSpec({ type: "light" }, fakeEncodeOne, 1);
  assert.deepEqual([light.id, light.length, light.codec], [0x1e, 1, "binary"]);

  const temperature = bw.writableSpec({ type: "temperature" }, fakeEncodeOne, 1);
  assert.deepEqual(
    [temperature.id, temperature.length, temperature.codec, temperature.scale, temperature.signed],
    [0x02, 2, "number", 100, true]
  );

  const moisture = bw.writableSpec({ type: "moisture" }, fakeEncodeOne, 1);
  assert.equal(moisture.signed, false, "unsigned, even though the encoder wraps negatives");

  const target = bw.writableSpec({ type: "temperature8" }, fakeEncodeOne, 1);
  assert.deepEqual([target.id, target.scale, target.signed], [0x57, 1, true]);

  const text = bw.writableSpec({ type: "text" }, fakeEncodeOne, 1);
  assert.deepEqual([text.id, text.variable, text.codec], [0x53, true, "text"]);

  const button = bw.writableSpec({ id: 0x3a, length: 1 }, fakeEncodeOne, 1);
  assert.deepEqual([button.id, button.length, button.codec], [0x3a, 1, "event"]);
});

test("an entry's own `signed` overrides the table", () => {
  assert.equal(bw.writableSpec({ type: "moisture", signed: true }, fakeEncodeOne, 1).signed, true);
});

test("decoding a write gives set() the value in its own units", () => {
  const spec = (e) => bw.writableSpec(e, fakeEncodeOne, 1);
  assert.equal(bw.decodeValue([0x01], spec({ type: "light" })), true);
  assert.equal(bw.decodeValue([0x00], spec({ type: "light" })), false);
  assert.equal(bw.decodeValue([0x6a, 0xff], spec({ type: "temperature" })), -1.5);
  assert.equal(bw.decodeValue([0x70, 0x17], spec({ type: "moisture" })), 60);
  assert.equal(bw.decodeValue([0x40, 0x9c], spec({ type: "moisture" })), 400, "above half range stays positive");
  assert.equal(bw.decodeValue([0x16], spec({ type: "temperature8" })), 22);
  assert.equal(bw.decodeValue([0x05, 72, 101, 108, 108, 111], spec({ type: "text" })), "Hello");
  assert.equal(bw.decodeValue([0x04], spec({ id: 0x3a, length: 1 })), 4);
});

test("a type the encoder does not know must be declared by id", () => {
  assert.throws(
    () => bw.planPacket([{ type: "button", set: noop }], fakeEncodeOne),
    (error) => error.code === "unsupported_writable_type"
  );
  assert.doesNotThrow(() => bw.planPacket([{ id: 0x3a, length: 1, set: noop }], fakeEncodeOne));
});

test("a forbidden entry is refused at setup", () => {
  /* §2.1: the packet id cannot be written. */
  assert.throws(
    () => bw.planPacket([{ id: 0x00, length: 1, set: noop }], fakeEncodeOne),
    (error) => error.code === "forbidden_entry"
  );
});

test("an entry with neither get() nor set() is a configuration error", () => {
  assert.throws(
    () => bw.planPacket([{ type: "light" }], fakeEncodeOne),
    (error) => error.code === "entry_without_accessor"
  );
});

test("an over-budget packet is refused at setup, not at write time", () => {
  const entries = Array.from({ length: 25 }, () => ({ type: "light", set: noop }));
  assert.throws(
    () => bw.planPacket(entries, fakeEncodeOne),
    (error) => error.code === "capacity_exceeded"
  );
});

test("get() returning a value that changes the object ID is caught", () => {
  let type = "battery";
  const entries = [{ get type() { return type; }, get: () => 50 }];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  type = "temperature";
  assert.throws(
    () => bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 100000),
    (error) => error.code === "layout_drift"
  );
});

test("each sensor can be read on its own schedule", () => {
  /* The advertising interval is the ceiling on how often anything can be
   * perceived to change; a slow sensor need not be read that often. */
  const reads = { battery: 0, temperature: 0 };
  const entries = [
    { type: "battery", interval: 60000, get: () => { reads.battery += 1; return 90; } },
    { type: "temperature", get: () => { reads.temperature += 1; return 22.1; } },
  ];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  reads.battery = 0;
  reads.temperature = 0;

  for (let t = 0; t <= 10000; t += 2000) {
    bw.renderServiceData(plan, 1, fakeEncodeOne, entries, t);
  }
  assert.equal(reads.temperature, 6, "no interval means read on every packet");
  assert.equal(reads.battery, 0, "still inside its interval");

  bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 60000);
  assert.equal(reads.battery, 1, "and read again once the minute is up");
});

test("a cached reading still goes out in every packet", () => {
  const entries = [{ type: "battery", interval: 60000, get: () => 90 }];
  const plan = bw.planPacket(entries, fakeEncodeOne);
  assert.equal(bytesToHex(bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 0)), "400001015a");
  assert.equal(bytesToHex(bw.renderServiceData(plan, 2, fakeEncodeOne, entries, 5000)), "400002015a");
});

test("a sensor with no interval follows the advertising interval", () => {
  let reads = 0;
  const entries = [{ type: "battery", get: () => { reads += 1; return 90; } }];
  const plan = bw.planPacket(entries, fakeEncodeOne, 2000);
  reads = 0;

  bw.renderServiceData(plan, 1, fakeEncodeOne, entries, 100);
  assert.equal(reads, 0);
  bw.renderServiceData(plan, 2, fakeEncodeOne, entries, 2000);
  assert.equal(reads, 1);
});

test("a named interval is not overridden by the advertising interval", () => {
  let reads = 0;
  const entries = [{ type: "battery", interval: 60000, get: () => { reads += 1; return 90; } }];
  const plan = bw.planPacket(entries, fakeEncodeOne, 500);
  reads = 0;
  for (let t = 500; t <= 10000; t += 500) {
    bw.renderServiceData(plan, 1, fakeEncodeOne, entries, t);
  }
  assert.equal(reads, 0, "a minute has not passed");
});

test("an encrypted plan advertises 0x41 and pays for it in budget", () => {
  /* §5.2: counter and MIC come out of the same bytes, checked at setup. */
  const entries = [
    { type: "battery", get: () => 97 },
    { type: "light", set: noop },
  ];
  const plain = bw.planPacket(entries, fakeEncodeOne, 0, false);
  const sealed = bw.planPacket(entries, fakeEncodeOne, 0, true);
  assert.equal(plain.info, bw.DEVICE_INFO_PLAIN);
  assert.equal(sealed.info, bw.DEVICE_INFO_ENCRYPTED);
  assert.equal(plain.budget - sealed.budget, 8);
});

test("a packet that fits in the clear can be too big once encrypted", () => {
  const entries = Array.from({ length: 8 }, () => ({ type: "battery", get: () => 97 }));
  assert.doesNotThrow(() => bw.planPacket(entries, fakeEncodeOne, 0, false));
  assert.throws(
    () => bw.planPacket(entries, fakeEncodeOne, 0, true),
    (error) => error.code === "capacity_exceeded"
  );
});

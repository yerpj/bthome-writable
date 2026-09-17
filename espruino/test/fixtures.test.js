"use strict";

/* The JS half of the advertising-fixture contract (PROTOCOL.md v2).
 *
 * Every valid fixture is rebuilt from its objects and entries with the codec and
 * must come out byte-identical to the payload the Python side verified against
 * the real BTHome parser. Every write and read is then fed through the device's
 * own write parser for its entry. If the two implementations ever diverge, this
 * fails.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const bw = require("../BTHomeWritable.js");

const DOCUMENT = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "spec", "advertising-fixtures.json"),
    "utf8"
  )
);
const FIXTURES = DOCUMENT.fixtures;
const LENGTH_PREFIXED = new Set([0x53, 0x54]);

function hexToBytes(hex) {
  const bytes = [];
  for (let i = 0; i < hex.length; i += 2) bytes.push(parseInt(hex.substr(i, 2), 16));
  return bytes;
}

function bytesToHex(bytes) {
  return bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
}

function sensorObjects(fixture) {
  return fixture.objects
    .filter((o) => o.object_id !== "ff")
    .map((o) => ({ id: parseInt(o.object_id, 16), value: hexToBytes(o.value) }));
}

function entryIds(fixture) {
  return fixture.declaration ? fixture.declaration.entries.map((e) => parseInt(e, 16)) : null;
}

/* The spec the device holds for entry `k`, as its setup would derive it. */
function specFor(fixture, access) {
  const id = parseInt(fixture.declaration.entries[access.entry - 1], 16);
  if (LENGTH_PREFIXED.has(id)) return { id, variable: true, entry: access.entry };
  return { id, length: hexToBytes(access.object.value).length, entry: access.entry };
}

test("the budget the codec enforces is the one the fixtures were built to", () => {
  assert.equal(bw.SERVICE_DATA_BUDGET, DOCUMENT.budget.service_data_budget);
});

for (const fixture of FIXTURES) {
  if (!fixture.valid) continue;

  test(`${fixture.name}: the codec rebuilds the advertised service data`, () => {
    const built = bw.buildServiceData(
      parseInt(fixture.device_info_byte, 16),
      sensorObjects(fixture),
      entryIds(fixture)
    );
    assert.equal(bytesToHex(built), fixture.service_data);
  });

  for (const access of (fixture.writes || []).concat(fixture.reads || [])) {
    test(`${fixture.name} / ${access.name}: one object, accepted on entry ${access.entry}`, () => {
      assert.equal(access.uuid, bw.characteristicUuid(access.entry).toLowerCase());
      const value = bw.parseWrite(hexToBytes(access.payload), specFor(fixture, access));
      assert.equal(bytesToHex(value), access.object.value);
    });
  }
}

test("declaration-not-last cannot be produced: the codec always appends it", () => {
  const built = bw.buildServiceData(0x40, [{ id: 0x01, value: [97] }], [0x1e]);
  assert.deepEqual(built.slice(-2), [bw.DECLARATION_OBJECT_ID, 0x1e]);
});

test("forbidden-entry is refused when built through the codec", () => {
  const fixture = FIXTURES.find((f) => f.violates === "forbidden_entry");
  assert.throws(
    () => bw.buildServiceData(0x40, sensorObjects(fixture), entryIds(fixture)),
    (error) => error.code === "forbidden_entry"
  );
});

test("capacity-overflow is refused rather than truncated", () => {
  const fixture = FIXTURES.find((f) => f.violates === "capacity_exceeded");
  assert.throws(
    () => bw.buildServiceData(0x40, sensorObjects(fixture), entryIds(fixture)),
    (error) => error.code === "capacity_exceeded"
  );
});

test("a write aimed at a layout the device no longer has is refused", () => {
  /* The desync guard of §4.2: a receiver still holding old firmware's layout
   * sends a light to what is now a text entry. */
  const fixture = FIXTURES.find((f) => f.name === "two-lights-and-display");
  const lightOff = fixture.writes.find((w) => w.name === "second-light-off");
  assert.throws(
    () => bw.parseWrite(hexToBytes(lightOff.payload), { id: 0x53, variable: true, entry: 3 }),
    (error) => error.code === "objectid_mismatch"
  );
});

test("a truncated write is refused", () => {
  const fixture = FIXTURES.find((f) => f.name === "two-lights-and-display");
  const hello = fixture.writes.find((w) => w.name === "display-hello");
  assert.throws(
    () => bw.parseWrite(hexToBytes(hello.payload).slice(0, -1), specFor(fixture, hello)),
    (error) => error.code === "truncated"
  );
});

test("a write carrying two objects is refused", () => {
  /* §4.2: exactly one object per write. Version 1's write-all shape must not be
   * accepted by accident. */
  const fixture = FIXTURES.find((f) => f.name === "single-light");
  const on = fixture.writes[0];
  const doubled = hexToBytes(on.payload).concat(hexToBytes(on.payload));
  assert.throws(
    () => bw.parseWrite(doubled, specFor(fixture, on)),
    (error) => error.code === "trailing_bytes"
  );
});

test("an empty write is refused", () => {
  assert.throws(
    () => bw.parseWrite([], { id: 0x1e, length: 1, entry: 1 }),
    (error) => error.code === "truncated"
  );
});

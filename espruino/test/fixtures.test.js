"use strict";

/* The JS half of the advertising-fixture contract (T0.4).
 *
 * Every valid fixture is rebuilt from its object list with the codec and must
 * come out byte-identical to the payload the Python side verified against the
 * real BTHome parser. Every write payload is then fed back through the device's
 * own write parser. If the two implementations ever diverge, this fails.
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

function hexToBytes(hex) {
  const bytes = [];
  for (let i = 0; i < hex.length; i += 2) bytes.push(parseInt(hex.substr(i, 2), 16));
  return bytes;
}

function bytesToHex(bytes) {
  return bytes.map((b) => b.toString(16).padStart(2, "0")).join("");
}

/* The objects a fixture declares writable, minus the declaration itself. */
function writableObjects(fixture) {
  return fixture.declaration.writable_positions
    .filter((p) => p < fixture.objects.length)
    .map((p) => fixture.objects[p])
    .filter((o) => o.object_id !== "ff");
}

/* Turn a fixture's writable objects into the layout the device holds. */
function layoutFor(fixture) {
  return writableObjects(fixture).map((o) => {
    const id = parseInt(o.object_id, 16);
    // 0x53 is BTHome's text object: a length byte followed by that many bytes.
    if (id === 0x53) return { id, variable: true };
    return { id, length: hexToBytes(o.value).length };
  });
}

test("the budget the codec enforces is the one the fixtures were built to", () => {
  assert.equal(bw.SERVICE_DATA_BUDGET, DOCUMENT.budget.service_data_budget);
});

for (const fixture of FIXTURES) {
  if (!fixture.valid) continue;

  test(`${fixture.name}: the codec rebuilds the advertised service data`, () => {
    const objects = fixture.objects
      .filter((o) => o.object_id !== "ff")
      .map((o) => ({ id: parseInt(o.object_id, 16), value: hexToBytes(o.value) }));
    const positions = fixture.declaration
      ? fixture.declaration.writable_positions
      : null;

    const built = bw.buildServiceData(
      parseInt(fixture.device_info_byte, 16),
      objects,
      fixture.declaration ? positions : null
    );
    assert.equal(bytesToHex(built), fixture.service_data);
  });

  for (const entry of fixture.writes || []) {
    test(`${fixture.name} / ${entry.name}: the device accepts the write`, () => {
      const parsed = bw.parseWrite(hexToBytes(entry.payload), layoutFor(fixture));

      // Every writable object came back, in order, with its ID intact.
      assert.equal(parsed.length, entry.objects.length);
      parsed.forEach((got, index) => {
        assert.equal(got.id, parseInt(entry.objects[index].object_id, 16));
        assert.equal(bytesToHex(got.value), entry.objects[index].value);
      });
    });
  }
}

test("declaration-not-last is rejected when built through the codec", () => {
  /* The codec cannot produce it at all: it always appends the declaration.
   * This test states that as an invariant rather than leaving it implicit. */
  const built = bw.buildServiceData(
    0x40,
    [
      { id: 0x01, value: [97] },
      { id: 0x1e, value: [1] },
    ],
    [1]
  );
  assert.equal(built[built.length - 2], bw.DECLARATION_OBJECT_ID);
});

test("capacity-overflow is refused rather than truncated", () => {
  const fixture = FIXTURES.find((f) => f.violates === "capacity_exceeded");
  const objects = fixture.objects
    .filter((o) => o.object_id !== "ff")
    .map((o) => ({ id: parseInt(o.object_id, 16), value: hexToBytes(o.value) }));

  assert.throws(
    () =>
      bw.buildServiceData(0x40, objects, fixture.declaration.writable_positions),
    (error) => error.code === "capacity_exceeded"
  );
});

test("a bitmask addressing a missing object is refused at build time", () => {
  assert.throws(
    () => bw.buildServiceData(0x40, [{ id: 0x01, value: [97] }], [5]),
    (error) => error.code === "position_addresses_missing_object"
  );
});

test("a stale layout is caught by the object-ID check", () => {
  /* Risk #8: the device was reflashed with a different layout while the
   * receiver still holds the old one. The redundant object IDs exist for
   * exactly this. */
  const fixture = FIXTURES.find((f) => f.name === "multi-instance-and-display");
  const entry = fixture.writes.find((w) => w.name === "second-light-off");

  // The device now expects a text object where the receiver sends a light.
  const staleLayout = layoutFor(fixture);
  staleLayout[0] = { id: 0x53, variable: true };

  assert.throws(
    () => bw.parseWrite(hexToBytes(entry.payload), staleLayout),
    (error) => error.code === "objectid_mismatch"
  );
});

test("a truncated write is rejected", () => {
  const fixture = FIXTURES.find((f) => f.name === "multi-instance-and-display");
  const entry = fixture.writes.find((w) => w.name === "second-light-off");
  const truncated = hexToBytes(entry.payload).slice(0, -2);

  assert.throws(
    () => bw.parseWrite(truncated, layoutFor(fixture)),
    (error) => error.code === "truncated"
  );
});

test("trailing bytes are rejected", () => {
  /* §4.2: unlike advertising, a write is a closed format. A permissive parser
   * here is what would let a replayed advertisement apply its objects. */
  const fixture = FIXTURES.find((f) => f.name === "single-light");
  const entry = fixture.writes[0];
  const extended = hexToBytes(entry.payload).concat([0xff, 0x02]);

  assert.throws(
    () => bw.parseWrite(extended, layoutFor(fixture)),
    (error) => error.code === "trailing_bytes"
  );
});

test("the length-0 no-op is recognised on a text object", () => {
  const fixture = FIXTURES.find((f) => f.name === "write-only-display");
  const noop = fixture.writes.find((w) => w.name === "display-noop");
  const layout = layoutFor(fixture);
  const parsed = bw.parseWrite(hexToBytes(noop.payload), layout);

  assert.equal(bw.isNoOp(parsed[0], layout[0]), true);

  const real = fixture.writes.find((w) => w.name === "display-hello");
  const parsedReal = bw.parseWrite(hexToBytes(real.payload), layout);
  assert.equal(bw.isNoOp(parsedReal[0], layout[0]), false);
});

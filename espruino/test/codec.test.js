"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const codec = require("../codec.js");

test("declaration element is <0xFF> <bitmask>", () => {
  assert.deepEqual(codec.encodeDeclaration([1]), [0xFF, 0b10]);
  assert.deepEqual(codec.encodeDeclaration([0]), [0xFF, 0b1]);
  assert.deepEqual(codec.encodeDeclaration([1, 2, 3]), [0xFF, 0b1110]);
});

test("Gordon's single-light example encodes to FF02", () => {
  // packet: 40 0161 1E01 FF02 -- battery is object 0, the light is object 1.
  assert.deepEqual(codec.encodeDeclaration([1]), [0xFF, 0x02]);
});

test("encode and decode round-trip", () => {
  for (const positions of [[], [0], [7], [0, 3, 7], [0, 1, 2, 3, 4, 5, 6, 7]]) {
    const mask = codec.encodeDeclaration(positions)[1];
    assert.deepEqual(codec.decodeDeclaration(mask), positions);
  }
});

test("a position beyond the one-byte bitmask is rejected", () => {
  assert.throws(() => codec.encodeDeclaration([8]), /out of range/);
});

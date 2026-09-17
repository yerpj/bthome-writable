"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const bw = require("../BTHomeWritable.js");

test("the declaration is 0xFF followed by the entries' object IDs", () => {
  assert.deepEqual(bw.encodeDeclaration([0x1e]), [0xff, 0x1e]);
  assert.deepEqual(bw.encodeDeclaration([0x10, 0x57]), [0xff, 0x10, 0x57]);
  assert.deepEqual(bw.encodeDeclaration([0x1e, 0x1e, 0x53]), [0xff, 0x1e, 0x1e, 0x53]);
});

test("an empty declaration is just the object ID", () => {
  assert.deepEqual(bw.encodeDeclaration([]), [0xff]);
});

test("the packet id, the declaration and device information are not entries", () => {
  for (const id of [0x00, 0xff, 0xf0, 0xf1, 0xf2]) {
    assert.throws(
      () => bw.encodeDeclaration([0x1e, id]),
      (error) => error.code === "forbidden_entry",
      `0x${id.toString(16)} should be refused`
    );
  }
});

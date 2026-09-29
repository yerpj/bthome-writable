"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const bw = require("../BTHomeWritable.js");

test("the declaration is 0xFF, a count, then the entries' object IDs", () => {
  /* The count makes it self-delimiting like every other variable-length BTHome
   * object, so a parser that does not know 0xFF can step over it instead of
   * having to stop (D-073). */
  assert.deepEqual(bw.encodeDeclaration([0x1e]), [0xff, 1, 0x1e]);
  assert.deepEqual(bw.encodeDeclaration([0x10, 0x57]), [0xff, 2, 0x10, 0x57]);
  assert.deepEqual(bw.encodeDeclaration([0x1e, 0x1e, 0x53]), [0xff, 3, 0x1e, 0x1e, 0x53]);
});

test("an empty declaration is the object ID and a zero count", () => {
  assert.deepEqual(bw.encodeDeclaration([]), [0xff, 0]);
});

test("the settings revision cannot be an entry either", () => {
  /* 0x65 is how the device says its own state moved (S3.2); a receiver able to
   * write it would be driving the signal meant to inform it (D-072). */
  assert.throws(
    () => bw.encodeDeclaration([0x1e, 0x65]),
    (error) => error.code === "forbidden_entry"
  );
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

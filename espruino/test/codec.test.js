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


/* --- the write-counter window (S5.3, agreed with Gordon in espruino#8024) --- */

const AHEAD = bw.COUNTER_WINDOW; // 0x80000000

test("a counter must be strictly ahead, never equal or behind", () => {
  assert.ok(bw.counterIsAhead(6, 5));
  assert.ok(!bw.counterIsAhead(5, 5), "the same counter is a replay");
  assert.ok(!bw.counterIsAhead(4, 5), "a lower counter is a replay");
  assert.ok(!bw.counterIsAhead(0, 5));
});

test("a forward jump is accepted, which is what makes resynchronisation work", () => {
  /* A receiver that lost its place cannot guess the device's counter. This
   * project's resynchronisation moves by 100000, and a config entry created
   * afresh seeds from the clock -- about 1.8 billion. A narrow window would
   * have refused both, silently, which is the bug D-063 found. */
  assert.ok(bw.counterIsAhead(100000, 0));
  assert.ok(bw.counterIsAhead(1790000000, 100135));
  assert.ok(bw.counterIsAhead(AHEAD, 0), "the far edge of the window is inside it");
  assert.ok(!bw.counterIsAhead(AHEAD + 1, 0), "one past it is not");
});

test("wrap-around is an ordinary step forward, not a step back", () => {
  /* 0xFFFFFFFF -> 0 is +1. Without the circular comparison a device would
   * refuse every write for ever once its counter rolled over. */
  assert.ok(bw.counterIsAhead(0, 0xffffffff));
  assert.ok(bw.counterIsAhead(9, 0xfffffffb));
  assert.ok(!bw.counterIsAhead(0xfffffffb, 9), "and the reverse is still a replay");
});

test("a captured write stays refused for half the counter space", () => {
  /* The security the window gives up, stated as a number: a replay of counter 5
   * is accepted again only once the device has passed 5 + 2^31, which is 68
   * years at one write a second. */
  assert.ok(!bw.counterIsAhead(5, 5 + 1000));
  assert.ok(!bw.counterIsAhead(5, 5 + AHEAD - 1));
  assert.ok(bw.counterIsAhead(5, (5 + AHEAD) >>> 0), "and only then");
});

test("0x3B command: the argument length is framing, and both shapes are accepted", () => {
  // The receiver encodes a bare opcode as <0><opcode> and a stepped one as
  // <1><opcode><step> (PROTOCOL.md §2.1). Neither `length` nor `variable` can
  // describe both, which is why every one of these writes used to be refused
  // with trailing_bytes (D-081).
  const spec = bw.writableSpec({ id: 0x3B, set: () => {} }, null, 1);
  assert.equal(spec.command, true);
  assert.equal(spec.codec, "command");

  const bare = bw.parseWrite([0x3B, 0x00, 0x01], spec);
  assert.deepEqual(Array.from(bare), [0x00, 0x01]);
  assert.equal(bw.decodeValue(bare, spec), 0x01, "set() gets the opcode alone");

  const stepped = bw.parseWrite([0x3B, 0x01, 0x03, 0x01], spec);
  assert.deepEqual(Array.from(stepped), [0x01, 0x03, 0x01]);
  assert.deepEqual(
    Array.from(bw.decodeValue(stepped, spec)),
    [0x03, 0x01],
    "and the opcode with its arguments when there are any"
  );
});

test("0x3B command: only the low five bits of the argument length count", () => {
  // The upper three are reserved by BTHome. Reading all eight would make a
  // reserved bit look like hundreds of missing argument bytes.
  const spec = bw.writableSpec({ id: 0x3B, set: () => {} }, null, 1);

  assert.deepEqual(
    Array.from(bw.parseWrite([0x3B, 0xE1, 0x03, 0x07], spec)),
    [0xE1, 0x03, 0x07]
  );
});

test("0x3B command: a short or an over-long write is still refused", () => {
  const spec = bw.writableSpec({ id: 0x3B, set: () => {} }, null, 1);

  assert.throws(() => bw.parseWrite([0x3B], spec), { code: "truncated" });
  assert.throws(() => bw.parseWrite([0x3B, 0x01, 0x03], spec), { code: "truncated" });
  assert.throws(
    () => bw.parseWrite([0x3B, 0x00, 0x01, 0x99], spec),
    { code: "trailing_bytes" }
  );
});

test("0x3B command: a declared length cannot narrow it", () => {
  // Honouring one would accept the opcodes that happen to fit and refuse the
  // rest, which is harder to diagnose than refusing all of them.
  const spec = bw.writableSpec({ id: 0x3B, length: 2, set: () => {} }, null, 1);

  assert.equal(spec.command, true);
  assert.deepEqual(Array.from(bw.parseWrite([0x3B, 0x01, 0x03, 0x01], spec)), [0x01, 0x03, 0x01]);
});

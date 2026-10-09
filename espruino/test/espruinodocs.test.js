"use strict";

/* The generated EspruinoDocs copies parse and behave.
 *
 * `tools/tests/test_espruinodocs_module.py` proves the stronger thing -- that
 * the generated code is byte-for-byte the code tested here, with only comments
 * removed. What it cannot prove is that the file still *parses*: a comment
 * removed badly can end inside an expression and leave something that compares
 * equal after stripping but will not load. That needs an engine, so it lives
 * here.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const PUBLISHED = path.join(__dirname, "..", "dist", "espruinodocs");

const FIXTURES = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "spec", "advertising-fixtures.json"),
    "utf8"
  )
).fixtures;

const VECTORS = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "test-vectors", "test-vectors.json"),
    "utf8"
  )
);

const hex = (bytes) =>
  Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");

/* The upstream module's encodings, as plan.test.js supplies them. */
function fakeEncodeOne(entry, value) {
  switch (entry.type) {
    case "battery":
      return [0x01, Math.round(value)];
    case "light":
      return [0x1e, value ? 1 : 0];
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

test("the published BTHomeWritable loads and builds the fixtures", () => {
  const bw = require(path.join(PUBLISHED, "BTHomeWritable.js"));
  const noop = () => {};

  const single = bw.planPacket(
    [
      { type: "battery", get: () => 97 },
      { type: "light", set: noop },
    ],
    fakeEncodeOne
  );
  assert.equal(
    hex(bw.renderServiceData(single, 9, null)),
    FIXTURES.find((f) => f.name === "single-light").service_data
  );

  const pair = bw.planPacket(
    [
      { type: "light", set: noop },
      { type: "light", set: noop },
      { type: "text", set: noop },
    ],
    fakeEncodeOne
  );
  assert.equal(
    hex(bw.renderServiceData(pair, 9, null)),
    FIXTURES.find((f) => f.name === "two-lights-and-display").service_data
  );
});

test("the published AESCCM loads and passes the shared vectors", () => {
  const before = global.AES;
  global.AES = {
    encrypt(data, key, options) {
      const mode = options.mode === "CBC" ? "aes-128-cbc" : "aes-128-ecb";
      const iv = options.mode === "CBC" ? Buffer.from(options.iv) : Buffer.alloc(0);
      const cipher = crypto.createCipheriv(mode, Buffer.from(key), iv);
      cipher.setAutoPadding(false);
      return Buffer.concat([cipher.update(Buffer.from(data)), cipher.final()]);
    },
  };
  try {
    const ccm = require(path.join(PUBLISHED, "AESCCM.js"));
    assert.equal(ccm.usingNative(), false, "no native CCM in this stand-in");
    let checked = 0;
    for (const v of VECTORS.vectors) {
      if (v.mic_valid !== "True" && v.mic_valid !== true) continue;
      const r = ccm.encrypt(
        Buffer.from(v.plaintext, "hex"),
        Buffer.from(v.bindkey, "hex"),
        Buffer.from(v.nonce, "hex"),
        VECTORS.constants.mic_length
      );
      assert.equal(hex(r.data), v.ciphertext, v.name);
      assert.equal(hex(r.mic), v.mic, v.name + " (mic)");
      checked += 1;
    }
    assert.ok(checked > 10, `only ${checked} vectors ran`);
  } finally {
    global.AES = before;
  }
});

test("the published copies name where they came from", () => {
  for (const name of ["BTHomeWritable.js", "AESCCM.js"]) {
    const text = fs.readFileSync(path.join(PUBLISHED, name), "utf8");
    assert.match(text, /bthome-writable/, name);
    assert.match(text, /not yet assigned by BTHome/, name);
  }
});

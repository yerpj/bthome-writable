"use strict";

/* AESCCM.js against the shared test vectors (spec/PROTOCOL.md §5.4).
 *
 * The module is written for Espruino's native `AES`, which Node does not have,
 * so the AES itself is supplied here by OpenSSL. That is not a weakening of the
 * test: what is under test is the CCM construction -- B0, the counter blocks,
 * the CBC-MAC, the tag masking -- and those are exactly what the vectors pin
 * down. tools/ccm_bench.py runs the same construction on a real board.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

/* Espruino's AES, as far as this module uses it: raw block modes, no padding. */
global.AES = {
  encrypt(data, key, options) {
    const mode = options.mode === "CBC" ? "aes-128-cbc" : "aes-128-ecb";
    const iv = options.mode === "CBC" ? Buffer.from(options.iv) : Buffer.alloc(0);
    const cipher = crypto.createCipheriv(mode, Buffer.from(key), iv);
    cipher.setAutoPadding(false);
    return Buffer.concat([cipher.update(Buffer.from(data)), cipher.final()]);
  },
};

const ccm = require("../AESCCM.js");

const DOCUMENT = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "test-vectors", "test-vectors.json"),
    "utf8"
  )
);
const MIC_LENGTH = DOCUMENT.constants.mic_length;

const hex = (buffer) => Buffer.from(buffer).toString("hex");

/* Both directions share this framing; advertising merely carries a leading
 * device-information byte that a write leaves implicit (§5.3). */
function split(vector) {
  let payload = Buffer.from(vector.payload, "hex");
  if (vector.direction === "advertising") payload = payload.subarray(1);
  return {
    ciphertext: payload.subarray(0, payload.length - 4 - MIC_LENGTH),
    mic: payload.subarray(payload.length - MIC_LENGTH),
  };
}

for (const vector of DOCUMENT.vectors) {
  const key = Buffer.from(vector.bindkey, "hex");
  const nonce = Buffer.from(vector.nonce, "hex");

  if (vector.mic_valid) {
    test(`${vector.name}: encrypts to the vector's bytes`, () => {
      const plaintext = Buffer.from(vector.plaintext, "hex");
      const result = ccm.encrypt(plaintext, key, nonce, MIC_LENGTH);
      assert.equal(hex(result.data), vector.ciphertext);
      assert.equal(hex(result.mic), vector.mic);
    });

    test(`${vector.name}: decrypts back, MIC accepted`, () => {
      const { ciphertext, mic } = split(vector);
      const plaintext = ccm.decrypt(ciphertext, key, nonce, mic);
      assert.notEqual(plaintext, null, "a valid MIC must not be rejected");
      assert.equal(hex(plaintext), vector.plaintext);
    });
  } else {
    test(`${vector.name}: MIC rejected (${vector.reject_reason})`, () => {
      const { ciphertext, mic } = split(vector);
      assert.equal(ccm.decrypt(ciphertext, key, nonce, mic), null);
    });
  }
}

test("a tampered MIC is rejected even when the ciphertext is untouched", () => {
  const vector = DOCUMENT.vectors.find((v) => v.mic_valid && v.direction === "write");
  const key = Buffer.from(vector.bindkey, "hex");
  const nonce = Buffer.from(vector.nonce, "hex");
  const { ciphertext, mic } = split(vector);

  for (let i = 0; i < mic.length; i++) {
    const broken = Buffer.from(mic);
    broken[i] ^= 0x01;
    assert.equal(ccm.decrypt(ciphertext, key, nonce, broken), null, `byte ${i}`);
  }
});

test("the counter is what separates two otherwise identical writes", () => {
  /* §5.2: the same plaintext under a different counter is a different nonce and
   * therefore different bytes. Without that, a replay would be undetectable at
   * the crypto layer and the counter rule would be doing all the work. */
  const key = Buffer.from(DOCUMENT.vectors[0].bindkey, "hex");
  const base = Buffer.from("a4c1388e1f2bd2fcff01000000", "hex");
  const other = Buffer.from(base);
  other.writeUInt32LE(2, 9);

  const plaintext = Buffer.from("1e00", "hex");
  const a = ccm.encrypt(plaintext, key, base, MIC_LENGTH);
  const b = ccm.encrypt(plaintext, key, other, MIC_LENGTH);
  assert.notEqual(hex(a.data), hex(b.data));
  assert.notEqual(hex(a.mic), hex(b.mic));
});

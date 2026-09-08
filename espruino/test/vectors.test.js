"use strict";

/* The JS half of the test-vector contract (spec/PROTOCOL.md §5.4).
 *
 * The Python suite verifies the same file with two independent AES-CCM
 * implementations; this one adds a third, OpenSSL's via Node. Three agreeing
 * implementations is the bar for a file that both codebases treat as normative.
 *
 * The framing and nonce checks here need no crypto at all, and are the ones the
 * Espruino module itself has to get right.
 */

const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const DOCUMENT = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "..", "..", "test-vectors", "test-vectors.json"),
    "utf8"
  )
);
const VECTORS = DOCUMENT.vectors;
const MIC_LENGTH = DOCUMENT.constants.mic_length;

/* Split an on-the-wire payload into ciphertext, counter and MIC.
 * Both directions share this framing (D-008); advertising merely carries a
 * leading device-information byte that a write leaves implicit. */
function splitPayload(vector) {
  let payload = Buffer.from(vector.payload, "hex");
  if (vector.direction === "advertising") payload = payload.subarray(1);
  return {
    ciphertext: payload.subarray(0, payload.length - 8),
    counter: payload.readUInt32LE(payload.length - 8),
    mic: payload.subarray(payload.length - MIC_LENGTH),
  };
}

function decrypt(key, nonce, ciphertext, mic) {
  const decipher = crypto.createDecipheriv("aes-128-ccm", key, nonce, {
    authTagLength: MIC_LENGTH,
  });
  decipher.setAuthTag(mic);
  decipher.setAAD(Buffer.alloc(0), { plaintextLength: ciphertext.length });
  const plaintext = decipher.update(ciphertext);
  try {
    decipher.final();
  } catch {
    return null; // MIC did not verify
  }
  return plaintext;
}

test("the vector file is the one this suite expects", () => {
  assert.ok(VECTORS.length >= 10);
  assert.equal(DOCUMENT.constants.device_info_byte_advertising, "41");
  assert.equal(DOCUMENT.constants.device_info_byte_write, "ff");
});

for (const vector of VECTORS) {
  test(`${vector.name}: nonce is built as the spec says`, () => {
    const expected = Buffer.concat([
      Buffer.from(vector.mac.replace(/:/g, ""), "hex"),
      Buffer.from(DOCUMENT.constants.uuid16, "hex"),
      Buffer.from(vector.device_info_byte, "hex"),
      (() => {
        const b = Buffer.alloc(4);
        b.writeUInt32LE(vector.counter);
        return b;
      })(),
    ]);
    assert.equal(expected.length, 13);
    assert.equal(Buffer.from(vector.nonce, "hex").toString("hex"), expected.toString("hex"));
  });

  test(`${vector.name}: payload framing is ciphertext || counter || mic`, () => {
    const { counter, mic, ciphertext } = splitPayload(vector);
    assert.equal(mic.length, MIC_LENGTH);
    assert.equal(counter, vector.counter);
    if (vector.mic_valid) {
      assert.equal(ciphertext.toString("hex"), vector.ciphertext);
      assert.equal(mic.toString("hex"), vector.mic);
    }
  });

  test(`${vector.name}: OpenSSL reaches the same verdict`, () => {
    const key = Buffer.from(vector.bindkey, "hex");
    const nonce = Buffer.from(vector.nonce, "hex");
    const { ciphertext, mic } = splitPayload(vector);
    const plaintext = decrypt(key, nonce, ciphertext, mic);

    if (vector.mic_valid) {
      assert.notEqual(plaintext, null, "expected the MIC to verify");
      assert.equal(plaintext.toString("hex"), vector.plaintext);
    } else {
      assert.equal(plaintext, null, "expected the MIC to fail");
    }
  });
}

test("a counter rejection is policy, not crypto", () => {
  /* The trap this guards: a device that only checks the MIC happily accepts a
   * byte-perfect replay of an old write. These vectors decrypt cleanly and must
   * still be refused. */
  const policyRejections = VECTORS.filter(
    (v) => v.reject_reason === "counter_not_increasing"
  );
  assert.ok(policyRejections.length > 0);

  for (const vector of policyRejections) {
    assert.equal(vector.mic_valid, true);
    assert.ok(vector.counter <= vector.last_accepted_counter);

    const { ciphertext, mic } = splitPayload(vector);
    const plaintext = decrypt(
      Buffer.from(vector.bindkey, "hex"),
      Buffer.from(vector.nonce, "hex"),
      ciphertext,
      mic
    );
    assert.notEqual(plaintext, null, "the replay decrypts -- that is the point");
  }
});

test("cross-direction replay fails on the nonce alone", () => {
  /* The captured bytes are authentic. They verify perfectly under the nonce
   * that produced them, and fail only because the device-information byte
   * differs -- so the defence is the nonce split of §5.1, nothing else. */
  const replayed = VECTORS.find((v) => v.name === "replay-advertisement-as-write");
  const original = VECTORS.find((v) => v.name === "adv-single-light");
  const key = Buffer.from(replayed.bindkey, "hex");
  const { ciphertext, mic } = splitPayload(replayed);

  assert.equal(decrypt(key, Buffer.from(replayed.nonce, "hex"), ciphertext, mic), null);

  const recovered = decrypt(key, Buffer.from(original.nonce, "hex"), ciphertext, mic);
  assert.notEqual(recovered, null);
  assert.equal(recovered.toString("hex"), original.plaintext);
});

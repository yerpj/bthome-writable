"use strict";

/* The native path: firmwares built with USE_AES_CCM do CCM themselves.
 *
 * @enaon's nice!nano has `AES.ccmEncrypt` and no `AES.encrypt`, so the
 * construction in AESCCM.js cannot run there at all (issue #1). The module now
 * prefers the firmware's own CCM where it exists.
 *
 * No board here has USE_AES_CCM, so what can be tested is everything except
 * the firmware: that the adapter calls it with the right arguments, accepts
 * the shape it is documented to return, and produces the vectors. OpenSSL's
 * AES-CCM stands in for the firmware -- which also means the shared vectors
 * are now checked against a second, independent CCM implementation rather
 * than only against our own.
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
const MIC_LENGTH = DOCUMENT.constants.mic_length;
const hex = (buffer) => Buffer.from(buffer).toString("hex");

/* A firmware that implements CCM, built on OpenSSL. `tag` is the spelling
 * @enaon's board returns; `mic` is checked separately below. */
function firmware(tagName) {
  return {
    ccmEncrypt(pt, key, nonce, M) {
      const cipher = crypto.createCipheriv(
        "aes-128-ccm", Buffer.from(key), Buffer.from(nonce),
        { authTagLength: M }
      );
      cipher.setAAD(Buffer.alloc(0), { plaintextLength: pt.length });
      const data = Buffer.concat([cipher.update(Buffer.from(pt)), cipher.final()]);
      const out = { data: new Uint8Array(data) };
      out[tagName] = new Uint8Array(cipher.getAuthTag());
      return out;
    },
    ccmDecrypt(ct, key, nonce, mic) {
      const decipher = crypto.createDecipheriv(
        "aes-128-ccm", Buffer.from(key), Buffer.from(nonce),
        { authTagLength: mic.length }
      );
      decipher.setAuthTag(Buffer.from(mic));
      decipher.setAAD(Buffer.alloc(0), { plaintextLength: ct.length });
      const pt = decipher.update(Buffer.from(ct));
      try {
        decipher.final();
      } catch {
        return null; // the MIC did not match
      }
      return new Uint8Array(pt);
    },
  };
}

/* The generic AES this module falls back to, as the other CCM test supplies
 * it -- present here so the two paths can be compared in one process. */
const GENERIC = {
  encrypt(data, key, options) {
    const mode = options.mode === "CBC" ? "aes-128-cbc" : "aes-128-ecb";
    const iv = options.mode === "CBC" ? Buffer.from(options.iv) : Buffer.alloc(0);
    const cipher = crypto.createCipheriv(mode, Buffer.from(key), iv);
    cipher.setAutoPadding(false);
    return Buffer.concat([cipher.update(Buffer.from(data)), cipher.final()]);
  },
};

const ccm = require("../AESCCM.js");

function withFirmware(aes, body) {
  const before = global.AES;
  global.AES = aes;
  try {
    body();
  } finally {
    global.AES = before;
  }
}

function vectors() {
  // Only the ones that are meant to authenticate: a deliberately broken MIC
  // has no plaintext to compare against.
  return DOCUMENT.vectors.filter((v) => v.mic_valid === "True" || v.mic_valid === true);
}

function parts(vector) {
  return {
    plaintext: Buffer.from(vector.plaintext, "hex"),
    key: Buffer.from(vector.bindkey, "hex"),
    nonce: Buffer.from(vector.nonce, "hex"),
    ciphertext: Buffer.from(vector.ciphertext, "hex"),
    mic: Buffer.from(vector.mic, "hex"),
  };
}

test("the vectors pass through the firmware's own CCM", () => {
  withFirmware(firmware("tag"), () => {
    assert.equal(ccm.usingNative(), true, "the native path must be the one taken");
    for (const vector of vectors()) {
      const v = parts(vector);
      const r = ccm.encrypt(v.plaintext, v.key, v.nonce, MIC_LENGTH);
      assert.equal(hex(r.data), hex(v.ciphertext), vector.name);
      assert.equal(hex(r.mic), hex(v.mic), vector.name + " (mic)");

      const back = ccm.decrypt(v.ciphertext, v.key, v.nonce, v.mic);
      assert.equal(hex(back), hex(v.plaintext), vector.name + " (decrypt)");
    }
  });
});

test("a firmware that calls the tag `mic` is understood too", () => {
  /* Which name comes back is not something this project can verify, so both
   * are accepted rather than guessed at. */
  withFirmware(firmware("mic"), () => {
    const v = parts(vectors()[0]);
    const r = ccm.encrypt(v.plaintext, v.key, v.nonce, MIC_LENGTH);
    assert.equal(hex(r.mic), hex(v.mic));
  });
});

test("an unexpected shape says what it actually got", () => {
  /* The person who meets this has the board and we do not, so the message has
   * to carry the evidence. */
  withFirmware(
    {
      ccmEncrypt: () => ({ ciphertext: [1, 2, 3] }),
      ccmDecrypt: () => null,
    },
    () => {
      assert.throws(
        () => ccm.encrypt(new Uint8Array([1]), new Uint8Array(16), new Uint8Array(13), 4),
        /ciphertext/,
        "the error must quote what the firmware returned"
      );
    }
  );
});

test("a bad MIC is null from the firmware path too", () => {
  withFirmware(firmware("tag"), () => {
    const v = parts(vectors()[0]);
    const wrong = Buffer.from(v.mic);
    wrong[0] ^= 1;
    assert.equal(ccm.decrypt(v.ciphertext, v.key, v.nonce, wrong), null);
  });
});

test("without USE_AES_CCM the construction here is used instead", () => {
  withFirmware(GENERIC, () => {
    assert.equal(ccm.usingNative(), false);
    const v = parts(vectors()[0]);
    const r = ccm.encrypt(v.plaintext, v.key, v.nonce, MIC_LENGTH);
    assert.equal(hex(r.data), hex(v.ciphertext), "the fallback still passes");
    assert.equal(hex(r.mic), hex(v.mic));
  });
});

test("both paths agree, vector by vector", () => {
  /* The point of having two: a device may run either and the bytes on the air
   * must not depend on which. */
  for (const vector of vectors()) {
    const v = parts(vector);
    let fromFirmware, fromHere;
    withFirmware(firmware("tag"), () => {
      fromFirmware = ccm.encrypt(v.plaintext, v.key, v.nonce, MIC_LENGTH);
    });
    withFirmware(GENERIC, () => {
      fromHere = ccm.encrypt(v.plaintext, v.key, v.nonce, MIC_LENGTH);
    });
    assert.equal(hex(fromFirmware.data), hex(fromHere.data), vector.name);
    assert.equal(hex(fromFirmware.mic), hex(fromHere.mic), vector.name + " (mic)");
  }
});

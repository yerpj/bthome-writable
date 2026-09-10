/*
AES-CCM authenticated encryption, built from Espruino's native AES.

Some builds expose `AES.ccmEncrypt`/`AES.ccmDecrypt` directly (guarded by
USE_AES_CCM); Puck.js is not one of them. This gives the same thing on any build
that has AES at all.

  var ccm = require("AESCCM");
  var r = ccm.encrypt(plaintext, key, nonce, 4);   // -> {data, mic}
  var pt = ccm.decrypt(r.data, key, nonce, r.mic); // -> Uint8Array, or null

`key` is 16 bytes, `nonce` 7 to 13, and the MIC length is even, 4 to 16. No
associated data: CCM allows it, this does not implement it.

CCM is a CBC-MAC for the tag and a counter-mode keystream for the data:

  B0 = flags || nonce || length, CBC-MACed with a zero IV over B0 || plaintext
  A_i = (L-1) || nonce || i, keystream = E(A_1) || E(A_2) || ...
  ciphertext = plaintext XOR keystream, tag = CBC-MAC XOR E(A_0)

Two things about this firmware shape the implementation, both measured
(spec/decisions.md D-026, D-028):

**Work in small pieces.** `AES.encrypt` allocates its result as one contiguous
block, and fails -- returning `undefined`, reporting "Not enough memory for
result" -- when the heap has no run that long, which happens well before memory
runs out. On a Puck.js running an ordinary sketch, 128- and 64-byte calls fail
while 32-byte ones succeed. So nothing here asks for more than 32 bytes at a
time, and the buffer it builds them in is allocated once, at load, while the
heap is still clean. CBC chains across calls through its IV, so splitting the
MAC costs nothing but the call.

**Not CTR**, which would be the obvious way to make the keystream: this
firmware ignores CTR's `iv` and always starts from a zero counter block (D-027),
so it would be silently, catastrophically wrong. ECB encrypts each block
independently, which is all the keystream needs.
*/

var CHUNK = 32; // bytes per AES call: two blocks, small enough to be reliable
var buf = new Uint8Array(CHUNK); // built once, while the heap is unfragmented
var ZERO = new Uint8Array(16);

/* One AES call, with the failure the docs do not mention made explicit. */
function aes(data, key, options) {
  var r = AES.encrypt(data, key, options);
  if (r === undefined) throw new Error("AES returned nothing: no contiguous memory");
  return new Uint8Array(r);
}

/* Fill `slot` of the scratch buffer with block `index` of B0 || plaintext. */
function macBlock(slot, index, pt, nonce, M, L) {
  var at = slot * 16, i;
  buf.fill(0, at, at + 16); // native: a JS loop over 16 bytes costs more than the AES
  if (index === 0) {
    buf[at] = ((M - 2) / 2) << 3 | (L - 1);
    buf.set(nonce, at + 1);
    for (i = 0; i < L; i++) buf[at + 15 - i] = (pt.length >> (8 * i)) & 255;
  } else {
    var start = (index - 1) * 16;
    buf.set(pt.subarray(start, Math.min(start + 16, pt.length)), at);
  }
}

/* The CBC-MAC over B0 || padded plaintext, in chunks, chaining through the IV. */
function tagOf(key, pt, nonce, M, L) {
  var total = Math.ceil(pt.length / 16) + 1;
  var carry = ZERO, index = 0;
  while (index < total) {
    var count = Math.min(2, total - index);
    for (var slot = 0; slot < count; slot++) {
      macBlock(slot, index + slot, pt, nonce, M, L);
    }
    var out = aes(buf.subarray(0, count * 16), key, {iv: carry, mode: "CBC"});
    carry = out.subarray(out.length - 16);
    index += count;
  }
  return carry;
}

/* E(A_index) .. E(A_index+count-1), the keystream blocks, via ECB. */
function counters(key, nonce, L, index, count) {
  for (var slot = 0; slot < count; slot++) {
    var at = slot * 16, i;
    buf.fill(0, at, at + 16);
    buf[at] = L - 1;
    buf.set(nonce, at + 1);
    for (i = 0; i < L; i++) buf[at + 15 - i] = ((index + slot) >> (8 * i)) & 255;
  }
  return aes(buf.subarray(0, count * 16), key, {mode: "ECB"});
}

/* XOR the keystream over `data`, and hand back E(A_0) for the tag mask. */
function stream(data, source, key, nonce, L) {
  var blocks = Math.ceil(source.length / 16), s0 = null, index = 0;
  while (index <= blocks) {
    var count = Math.min(2, blocks + 1 - index);
    var s = counters(key, nonce, L, index, count);
    for (var slot = 0; slot < count; slot++) {
      if (index + slot === 0) { s0 = s.subarray(0, 16); continue; }
      var start = (index + slot - 1) * 16;
      var end = Math.min(start + 16, source.length);
      for (var j = start; j < end; j++) data[j] = source[j] ^ s[slot * 16 + j - start];
    }
    index += count;
  }
  return s0;
}

exports.encrypt = function (pt, key, nonce, M) {
  if (M === undefined) M = 4;
  var L = 15 - nonce.length;
  var tag = tagOf(key, pt, nonce, M, L);
  var data = new Uint8Array(pt.length);
  var s0 = stream(data, pt, key, nonce, L);
  var mic = new Uint8Array(M);
  for (var i = 0; i < M; i++) mic[i] = tag[i] ^ s0[i];
  return { data: data, mic: mic };
};

/* Returns the plaintext, or null if the MIC does not match. Null rather than a
   throw because a bad MIC is an expected event -- a wrong key, or someone
   trying it on -- not a mistake by the caller. */
exports.decrypt = function (ct, key, nonce, mic) {
  var M = mic.length, L = 15 - nonce.length, i;
  // The keystream does not depend on the plaintext, so the message can be
  // recovered before the tag is known to be right.
  var pt = new Uint8Array(ct.length);
  var s0 = stream(pt, ct, key, nonce, L);
  var tag = tagOf(key, pt, nonce, M, L);
  // Accumulate rather than return early: how long this takes should not say how
  // much of the tag was correct.
  var diff = 0;
  for (i = 0; i < M; i++) diff |= (tag[i] ^ s0[i]) ^ mic[i];
  return diff ? null : pt;
};

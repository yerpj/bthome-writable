/* bthome-writable — pure-JS protocol codec.
 *
 * No NRF / hardware calls live in this file: it is the part that runs under
 * plain Node for the unit tests and under Espruino unchanged. See
 * spec/PROTOCOL.md; BTHomeWritable.js is the thin Espruino layer on top.
 */

// Object ID carrying the writability declaration inside the BTHome service
// data. Must be the last element of the payload -- see spec/decisions.md D-005.
var DECLARATION_OBJECT_ID = 0xFF;

// Maximum writable objects addressable by a one-byte bitmask (v1 of the spec).
var MAX_WRITABLE = 8;

/* Build the declaration element for a list of packet positions.
 * Bit n of the bitmask = the n-th BTHome object in this same packet is
 * writable, bit 0 being the first object (spec open decision 2).
 * Returns [DECLARATION_OBJECT_ID, bitmask]. */
function encodeDeclaration(positions) {
  var mask = 0;
  for (var i = 0; i < positions.length; i++) {
    var pos = positions[i];
    if (pos < 0 || pos >= MAX_WRITABLE) {
      throw new Error("writable position " + pos + " out of range (0.." + (MAX_WRITABLE - 1) + ")");
    }
    mask |= 1 << pos;
  }
  return [DECLARATION_OBJECT_ID, mask];
}

/* Inverse of encodeDeclaration: bitmask byte -> ascending packet positions. */
function decodeDeclaration(bitmask) {
  var positions = [];
  for (var i = 0; i < MAX_WRITABLE; i++) {
    if (bitmask & (1 << i)) positions.push(i);
  }
  return positions;
}

exports.DECLARATION_OBJECT_ID = DECLARATION_OBJECT_ID;
exports.MAX_WRITABLE = MAX_WRITABLE;
exports.encodeDeclaration = encodeDeclaration;
exports.decodeDeclaration = decodeDeclaration;

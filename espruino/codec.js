/* bthome-writable — pure-JS protocol codec.
 *
 * No NRF or hardware calls live in this file: it runs under plain Node for the
 * unit tests and under Espruino unchanged. BTHomeWritable.js is the thin
 * Espruino layer on top. See spec/PROTOCOL.md.
 *
 * Written in the Espruino dialect: var, no destructuring, no Array methods
 * beyond the ES5 set, byte arrays as plain Arrays.
 */

// Object ID carrying the writability declaration. MUST be the last element of
// the service data -- see spec/PROTOCOL.md §2.2 and spec/decisions.md D-005.
var DECLARATION_OBJECT_ID = 0xFF;

// A one-byte bitmask addresses at most eight writable objects (§2.4).
var MAX_WRITABLE = 8;

// Advertising budget arithmetic (§2.3). A legacy advertising payload is 31
// bytes, but the Flags AD structure and the Service Data header come out of it
// before any BTHome object does.
var ADV_PAYLOAD_BYTES = 31;
var AD_FLAGS_BYTES = 3;
var AD_SERVICE_DATA_HEADER_BYTES = 4;
var SERVICE_DATA_BUDGET =
  ADV_PAYLOAD_BYTES - AD_FLAGS_BYTES - AD_SERVICE_DATA_HEADER_BYTES;

/* Errors carry a `code` so callers can branch without matching on prose.
 * The device rejects the whole write on any of them (§4.2). */
function codecError(code, message) {
  var error = new Error(message);
  error.code = code;
  return error;
}

/* Build the declaration element for a list of packet positions.
 * Bit n = the n-th BTHome object of this same packet is writable, bit 0 being
 * the first object. Returns [0xFF, bitmask]. */
function encodeDeclaration(positions) {
  var mask = 0;
  for (var i = 0; i < positions.length; i++) {
    var pos = positions[i];
    if (pos < 0 || pos >= MAX_WRITABLE) {
      throw codecError(
        "position_out_of_range",
        "writable position " + pos + " out of range (0.." + (MAX_WRITABLE - 1) + ")"
      );
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

/* Assemble the BTHome service data for the declaration packet.
 *
 *   deviceInfo          the BTHome device-information byte (0x40 unencrypted)
 *   objects             [{id: 0x01, value: [0x61]}, ...] in packet order
 *   writablePositions   indices into `objects`, or null for no declaration
 *
 * Returns a plain byte array. Throws rather than truncate (§2.3): a device that
 * silently drops an object would advertise a layout its own write parser does
 * not expect. */
function buildServiceData(deviceInfo, objects, writablePositions) {
  var bytes = [deviceInfo];
  var i;

  for (i = 0; i < objects.length; i++) {
    bytes.push(objects[i].id);
    var value = objects[i].value;
    for (var j = 0; j < value.length; j++) bytes.push(value[j]);
  }

  if (writablePositions) {
    for (i = 0; i < writablePositions.length; i++) {
      if (writablePositions[i] >= objects.length) {
        throw codecError(
          "position_addresses_missing_object",
          "writable position " +
            writablePositions[i] +
            " addresses no object (packet holds " +
            objects.length +
            ")"
        );
      }
    }
    var declaration = encodeDeclaration(writablePositions);
    bytes.push(declaration[0]);
    bytes.push(declaration[1]);
  }

  if (bytes.length > SERVICE_DATA_BUDGET) {
    throw codecError(
      "capacity_exceeded",
      "BTHome service data needs " +
        bytes.length +
        " bytes but only " +
        SERVICE_DATA_BUDGET +
        " are available in an advertising payload"
    );
  }
  return bytes;
}

/* Parse a write payload against the layout this device advertised.
 *
 *   payload   plain byte array, the plaintext of §4.2
 *   layout    [{id: 0x1E, length: 1}, {id: 0x53, variable: true}, ...] --
 *             the writable objects, in packet order
 *
 * Returns [{id, value: [...]}] in the same order. Throws on any deviation: a
 * write is a closed format, and strictness here is a safety property (§4.2). */
function parseWrite(payload, layout) {
  var values = [];
  var offset = 0;

  for (var i = 0; i < layout.length; i++) {
    var expected = layout[i];

    if (offset >= payload.length) {
      throw codecError(
        "truncated",
        "write ended after " + i + " objects, expected " + layout.length
      );
    }

    // The object ID is redundant given the position, and that redundancy is
    // the point: it catches a receiver writing against a stale layout.
    if (payload[offset] !== expected.id) {
      throw codecError(
        "objectid_mismatch",
        "object ID 0x" +
          payload[offset].toString(16) +
          " at position " +
          i +
          ", expected 0x" +
          expected.id.toString(16)
      );
    }
    offset++;

    var length;
    if (expected.variable) {
      if (offset >= payload.length) {
        throw codecError(
          "truncated",
          "missing length byte for variable-length object at position " + i
        );
      }
      length = payload[offset];
      offset++;
    } else {
      length = expected.length;
    }

    if (offset + length > payload.length) {
      throw codecError(
        "truncated",
        "object at position " + i + " needs " + length + " value bytes"
      );
    }

    var value = [];
    if (expected.variable) value.push(length);
    for (var j = 0; j < length; j++) value.push(payload[offset + j]);
    offset += length;

    values.push({ id: expected.id, value: value });
  }

  if (offset !== payload.length) {
    throw codecError(
      "trailing_bytes",
      payload.length - offset + " unexpected trailing bytes"
    );
  }
  return values;
}

/* True when a parsed value is the "do not modify" no-op of §4.3.
 * Variable-length objects use length 0; event-class objects use BTHome's own
 * "none" event value, 0x00. */
function isNoOp(entry, layoutEntry) {
  if (layoutEntry.variable) return entry.value.length > 0 && entry.value[0] === 0;
  if (layoutEntry.event) return entry.value.length > 0 && entry.value[0] === 0;
  return false;
}

exports.DECLARATION_OBJECT_ID = DECLARATION_OBJECT_ID;
exports.MAX_WRITABLE = MAX_WRITABLE;
exports.SERVICE_DATA_BUDGET = SERVICE_DATA_BUDGET;
exports.encodeDeclaration = encodeDeclaration;
exports.decodeDeclaration = decodeDeclaration;
exports.buildServiceData = buildServiceData;
exports.parseWrite = parseWrite;
exports.isNoOp = isNoOp;

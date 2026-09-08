"""An independent AES-CCM implementation, built from AES-ECB only.

Two purposes:

1. **Cross-check.** The test vectors of `test-vectors/test-vectors.json` are
   produced with `cryptography`'s `AESCCM` and verified against this one, so a
   bug in either does not silently become the contract.
2. **Reference for the device side.** Espruino's `crypto` module exposes AES but
   not necessarily CCM, in which case the module has to assemble CTR + CBC-MAC
   itself. This is that assembly, written to be transliterated: no slicing
   tricks, no library beyond a single-block AES encryption.

RFC 3610, with the parameters BTHome uses: 13-byte nonce (so L = 2), 4-byte MIC
(M = 4), no associated data.
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

NONCE_LENGTH = 13
MIC_LENGTH = 4
_L = 15 - NONCE_LENGTH  # length field size, 2 bytes
BLOCK = 16


def _aes_encrypt_block(key: bytes, block: bytes) -> bytes:
    """The single primitive this module is allowed to use."""
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


def _pad(data: bytes) -> bytes:
    """Zero-pad to a whole number of AES blocks."""
    remainder = len(data) % BLOCK
    return data if remainder == 0 else data + bytes(BLOCK - remainder)


def _cbc_mac(key: bytes, nonce: bytes, message: bytes) -> bytes:
    """The authentication tag T, before encryption. RFC 3610 §2.2."""
    # B_0 = flags || nonce || l(m). With no associated data, the Adata bit is 0.
    flags = 8 * ((MIC_LENGTH - 2) // 2) + (_L - 1)
    b0 = bytes([flags]) + nonce + len(message).to_bytes(_L, "big")

    state = bytes(BLOCK)
    for offset in range(0, len(b0 + _pad(message)), BLOCK):
        block = (b0 + _pad(message))[offset : offset + BLOCK]
        state = _aes_encrypt_block(key, _xor(state, block))
    return state[:MIC_LENGTH]


def _counter_block(nonce: bytes, index: int) -> bytes:
    """A_i = flags || nonce || i. RFC 3610 §2.3."""
    return bytes([_L - 1]) + nonce + index.to_bytes(_L, "big")


def _ctr_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Keystream S_1 || S_2 || ... , used to encrypt the message itself."""
    stream = b""
    index = 1
    while len(stream) < length:
        stream += _aes_encrypt_block(key, _counter_block(nonce, index))
        index += 1
    return stream[:length]


def encrypt(key: bytes, nonce: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Return (ciphertext, mic). No associated data, as in BTHome v2."""
    if len(nonce) != NONCE_LENGTH:
        raise ValueError(f"nonce must be {NONCE_LENGTH} bytes, got {len(nonce)}")

    tag = _cbc_mac(key, nonce, plaintext)
    s0 = _aes_encrypt_block(key, _counter_block(nonce, 0))
    mic = _xor(tag, s0[:MIC_LENGTH])
    ciphertext = _xor(plaintext, _ctr_keystream(key, nonce, len(plaintext)))
    return ciphertext, mic


def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, mic: bytes) -> bytes | None:
    """Return the plaintext, or None if the MIC does not verify."""
    if len(nonce) != NONCE_LENGTH:
        raise ValueError(f"nonce must be {NONCE_LENGTH} bytes, got {len(nonce)}")

    plaintext = _xor(ciphertext, _ctr_keystream(key, nonce, len(ciphertext)))
    _, expected_mic = encrypt(key, nonce, plaintext)

    # Constant-time comparison: this code is meant to be transliterated onto a
    # device, and a device that leaks MIC comparison timing leaks the MIC.
    difference = 0
    for a, b in zip(expected_mic, mic, strict=False):
        difference |= a ^ b
    if difference != 0 or len(mic) != MIC_LENGTH:
        return None
    return plaintext

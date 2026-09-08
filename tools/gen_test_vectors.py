"""Generate `test-vectors/test-vectors.json` — the contract between codebases.

Every vector is produced with `cryptography`'s AES-CCM and independently
re-derived with `tools/ccm_reference.py` before being written out, so a bug in
either implementation cannot silently become the specification.

Run with no arguments to regenerate the file:

    python tools/gen_test_vectors.py

The output is deterministic: rerunning it on an unchanged spec must produce a
byte-identical file, so an accidental change shows up as a diff.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from tools import ccm_reference as ref

OUTPUT = Path(__file__).resolve().parent.parent / "test-vectors" / "test-vectors.json"

SPEC_VERSION = "1.0-draft.1"

UUID16 = bytes.fromhex("d2fc")
DEVICE_INFO_ADVERTISING = 0x41  # BTHome v2, encrypted
DEVICE_INFO_WRITE = 0xFF  # PROTOCOL.md §5.1
MIC_LENGTH = 4

BINDKEY = bytes.fromhex("231d39c1d7cc1ab1aee224cd096db932")
WRONG_BINDKEY = bytes.fromhex("00112233445566778899aabbccddeeff")
MAC = "A4:C1:38:8E:1F:2B"

UINT32_MAX = 0xFFFFFFFF


def mac_bytes(mac: str) -> bytes:
    """MAC in natural order, as BTHome's nonce uses it."""
    return bytes.fromhex(mac.replace(":", ""))


def nonce(mac: str, device_info: int, counter: int) -> bytes:
    """PROTOCOL.md §5.1: MAC(6) || 0xD2 0xFC || device-info || counter u32 LE."""
    return (
        mac_bytes(mac) + UUID16 + bytes([device_info]) + counter.to_bytes(4, "little")
    )


def seal(key: bytes, mac: str, device_info: int, counter: int, plaintext: bytes):
    """Encrypt, then check the result against the independent implementation."""
    n = nonce(mac, device_info, counter)
    sealed = AESCCM(key, tag_length=MIC_LENGTH).encrypt(n, plaintext, None)
    ciphertext, mic = sealed[:-MIC_LENGTH], sealed[-MIC_LENGTH:]

    ref_ciphertext, ref_mic = ref.encrypt(key, n, plaintext)
    if (ref_ciphertext, ref_mic) != (ciphertext, mic):
        raise AssertionError(
            "AES-CCM implementations disagree — refusing to emit a vector. "
            f"library={sealed.hex()} reference={(ref_ciphertext + ref_mic).hex()}"
        )
    return n, ciphertext, mic


def advertising_payload(device_info: int, ciphertext: bytes, counter: int, mic: bytes):
    """BTHome's encrypted service data: device-info || ct || counter || MIC."""
    return bytes([device_info]) + ciphertext + counter.to_bytes(4, "little") + mic


def write_payload(ciphertext: bytes, counter: int, mic: bytes) -> bytes:
    """PROTOCOL.md §5.3: ct || counter || MIC. No device-info byte on the wire."""
    return ciphertext + counter.to_bytes(4, "little") + mic


def vector(
    name: str,
    description: str,
    direction: str,
    counter: int,
    plaintext: bytes,
    *,
    key: bytes = BINDKEY,
    mac: str = MAC,
    expect: str = "accept",
    reject_reason: str | None = None,
    mic_valid: bool = True,
    last_accepted_counter: int | None = None,
    payload_override: bytes | None = None,
    verify_key: bytes | None = None,
) -> dict[str, Any]:
    """Build one vector.

    `payload_override` carries the negative cases whose bytes do not come from
    encrypting `plaintext` under `key` — a replayed advertisement presented as a
    write, a tampered ciphertext. `verify_key` is the key the *receiver* would
    use, which differs from `key` in the wrong-bindkey case.
    """
    device_info = (
        DEVICE_INFO_ADVERTISING if direction == "advertising" else DEVICE_INFO_WRITE
    )
    n, ciphertext, mic = seal(key, mac, device_info, counter, plaintext)

    if payload_override is not None:
        payload = payload_override
    elif direction == "advertising":
        payload = advertising_payload(device_info, ciphertext, counter, mic)
    else:
        payload = write_payload(ciphertext, counter, mic)

    entry: dict[str, Any] = {
        "name": name,
        "description": description,
        "direction": direction,
        "expect": expect,
        "bindkey": (verify_key or key).hex(),
        "mac": mac,
        "device_info_byte": f"{device_info:02x}",
        "counter": counter,
        "nonce": n.hex(),
        "payload": payload.hex(),
        "mic_valid": mic_valid,
    }
    if expect == "accept" or mic_valid:
        entry["plaintext"] = plaintext.hex()
        entry["ciphertext"] = ciphertext.hex()
        entry["mic"] = mic.hex()
    if reject_reason is not None:
        entry["reject_reason"] = reject_reason
    if last_accepted_counter is not None:
        entry["last_accepted_counter"] = last_accepted_counter
    return entry


# --- Plaintexts, mirroring the worked examples of PROTOCOL.md §8 -------------

# Advertising: packet id, battery 97 %, light on, declaration (position 1).
ADV_SINGLE_LIGHT = (
    bytes.fromhex("0009")
    + bytes.fromhex("0161")
    + bytes.fromhex("1e01")
    + bytes.fromhex("ff02")
)

# Advertising: three light instances plus a write-only text placeholder.
ADV_MULTI = (
    bytes.fromhex("000a")
    + bytes.fromhex("0161")
    + bytes.fromhex("1e01")
    + bytes.fromhex("1e00")
    + bytes.fromhex("1e01")
    + bytes.fromhex("5300")
    + bytes.fromhex("ff1e")
)

# Writes (§4.2): every writable object, in packet order.
WRITE_LIGHT_OFF = bytes.fromhex("1e00")
WRITE_MULTI_SECOND_OFF = (
    bytes.fromhex("1e01")
    + bytes.fromhex("1e00")
    + bytes.fromhex("1e01")
    + bytes.fromhex("5300")
)
WRITE_LONG_TEXT = (
    bytes.fromhex("53") + bytes([28]) + b"the quick brown fox jumps ove"[:28]
)


def build_vectors() -> list[dict[str, Any]]:
    vectors: list[dict[str, Any]] = []

    # --- Advertising direction, positive --------------------------------
    vectors.append(
        vector(
            "adv-single-light",
            "PROTOCOL.md §8.1 encrypted: battery, light on, declaration.",
            "advertising",
            1,
            ADV_SINGLE_LIGHT,
        )
    )
    vectors.append(
        vector(
            "adv-multi-instance",
            "PROTOCOL.md §8.2 encrypted: three lights and a write-only text.",
            "advertising",
            2,
            ADV_MULTI,
        )
    )
    vectors.append(
        vector(
            "adv-counter-zero",
            "Edge: the lowest counter value a device can advertise.",
            "advertising",
            0,
            ADV_SINGLE_LIGHT,
        )
    )
    vectors.append(
        vector(
            "adv-counter-max",
            "Edge: the highest u32 counter, immediately before wraparound.",
            "advertising",
            UINT32_MAX,
            ADV_SINGLE_LIGHT,
        )
    )

    # --- Write direction, positive --------------------------------------
    vectors.append(
        vector(
            "write-light-off",
            "PROTOCOL.md §8.1: switch the single light off.",
            "write",
            1,
            WRITE_LIGHT_OFF,
        )
    )
    vectors.append(
        vector(
            "write-multi-instance-no-op-text",
            "PROTOCOL.md §8.2: second light off, text carries the length-0 no-op.",
            "write",
            2,
            WRITE_MULTI_SECOND_OFF,
        )
    )
    vectors.append(
        vector(
            "write-long-text",
            "A 30-byte write: exceeds the 20-byte default-MTU budget of §4.4.",
            "write",
            3,
            WRITE_LONG_TEXT,
        )
    )
    vectors.append(
        vector(
            "write-counter-zero",
            "Edge: counter 0, which a freshly provisioned receiver may send.",
            "write",
            0,
            WRITE_LIGHT_OFF,
        )
    )
    vectors.append(
        vector(
            "write-counter-max",
            "Edge: the highest u32 counter.",
            "write",
            UINT32_MAX,
            WRITE_LIGHT_OFF,
        )
    )
    vectors.append(
        vector(
            "write-forward-jump",
            "§5.2: a large forward jump MUST be accepted (receiver reinstall).",
            "write",
            100000,
            WRITE_LIGHT_OFF,
            last_accepted_counter=7,
        )
    )

    # --- Negative: cross-direction replay -------------------------------
    # An attacker captures the encrypted advertisement of `adv-single-light`,
    # strips the device-information byte and presents the rest as a write.
    _, adv_ct, adv_mic = seal(
        BINDKEY, MAC, DEVICE_INFO_ADVERTISING, 1, ADV_SINGLE_LIGHT
    )
    vectors.append(
        vector(
            "replay-advertisement-as-write",
            "§5.1: an encrypted advertisement replayed as a write. The nonce's "
            "device-info byte differs (0x41 vs 0xFF), so the MIC cannot verify.",
            "write",
            1,
            ADV_SINGLE_LIGHT,
            expect="reject",
            reject_reason="mic_mismatch_cross_direction",
            mic_valid=False,
            payload_override=write_payload(adv_ct, 1, adv_mic),
        )
    )

    # And the mirror image: a captured write presented as advertising.
    _, wr_ct, wr_mic = seal(BINDKEY, MAC, DEVICE_INFO_WRITE, 1, WRITE_LIGHT_OFF)
    vectors.append(
        vector(
            "replay-write-as-advertisement",
            "§5.1, the other direction: a captured write replayed as an "
            "advertisement also fails, for the same reason.",
            "advertising",
            1,
            WRITE_LIGHT_OFF,
            expect="reject",
            reject_reason="mic_mismatch_cross_direction",
            mic_valid=False,
            payload_override=advertising_payload(
                DEVICE_INFO_ADVERTISING, wr_ct, 1, wr_mic
            ),
        )
    )

    # --- Negative: counter policy (MIC is valid, policy rejects) ---------
    vectors.append(
        vector(
            "write-counter-replayed-equal",
            "§5.2: a byte-perfect replay of an accepted write. The MIC verifies; "
            "the device MUST still reject it, because counter <= last accepted.",
            "write",
            42,
            WRITE_LIGHT_OFF,
            expect="reject",
            reject_reason="counter_not_increasing",
            last_accepted_counter=42,
        )
    )
    vectors.append(
        vector(
            "write-counter-below-last",
            "§5.2: an older write replayed. MIC valid, counter below the last "
            "accepted — reject.",
            "write",
            41,
            WRITE_LIGHT_OFF,
            expect="reject",
            reject_reason="counter_not_increasing",
            last_accepted_counter=42,
        )
    )

    # --- Negative: key and integrity ------------------------------------
    vectors.append(
        vector(
            "write-wrong-bindkey",
            "A write sealed with a different bindkey than the device holds.",
            "write",
            5,
            WRITE_LIGHT_OFF,
            key=WRONG_BINDKEY,
            verify_key=BINDKEY,
            expect="reject",
            reject_reason="mic_mismatch_wrong_key",
            mic_valid=False,
        )
    )

    _, tam_ct, tam_mic = seal(BINDKEY, MAC, DEVICE_INFO_WRITE, 6, WRITE_LIGHT_OFF)
    tampered = bytes([tam_ct[0] ^ 0x01]) + tam_ct[1:]
    vectors.append(
        vector(
            "write-tampered-ciphertext",
            "One bit flipped in the ciphertext: the MIC must catch it.",
            "write",
            6,
            WRITE_LIGHT_OFF,
            expect="reject",
            reject_reason="mic_mismatch_tampered",
            mic_valid=False,
            payload_override=write_payload(tampered, 6, tam_mic),
        )
    )

    return vectors


def main() -> None:
    document = {
        "spec_version": SPEC_VERSION,
        "generated_by": "tools/gen_test_vectors.py",
        "description": (
            "AES-CCM test vectors for bthome-writable. This file is the contract "
            "between the Espruino and Home Assistant implementations: both test "
            "suites consume it, and changing it is a change to the specification "
            "(see spec/PROTOCOL.md §5.4)."
        ),
        "constants": {
            "uuid16": UUID16.hex(),
            "device_info_byte_advertising": f"{DEVICE_INFO_ADVERTISING:02x}",
            "device_info_byte_write": f"{DEVICE_INFO_WRITE:02x}",
            "mic_length": MIC_LENGTH,
            "nonce": "mac(6, natural order) || uuid16 || device_info || counter u32 LE",
            "advertising_payload": "device_info || ciphertext || counter u32 LE || mic",
            "write_payload": "ciphertext || counter u32 LE || mic",
        },
        "field_notes": {
            "bindkey": "The key the RECEIVER uses to verify. For the "
            "wrong-bindkey vector this is deliberately not the key that "
            "sealed the payload.",
            "mic_valid": "Whether the MIC verifies. A rejected vector with "
            "mic_valid true is rejected by policy (counter), not by crypto.",
            "last_accepted_counter": "The counter state the device is assumed "
            "to hold before processing this vector.",
            "payload": "The bytes on the wire for this direction.",
        },
        "vectors": build_vectors(),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    accepted = sum(1 for v in document["vectors"] if v["expect"] == "accept")
    rejected = len(document["vectors"]) - accepted
    print(
        f"wrote {OUTPUT} — {len(document['vectors'])} vectors "
        f"({accepted} accept, {rejected} reject)"
    )


if __name__ == "__main__":
    main()

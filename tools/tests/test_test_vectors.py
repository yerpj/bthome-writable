"""T0.3 — verify `test-vectors/test-vectors.json` against both AES-CCM paths.

This is the Python half of the contract check. The Espruino suite consumes the
same file and must reach the same verdicts; see spec/PROTOCOL.md §5.4.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
import pytest

from tools import ccm_reference as ref
from tools.gen_test_vectors import OUTPUT

MIC_LENGTH = 4

DOCUMENT: dict[str, Any] = json.loads(OUTPUT.read_text(encoding="utf-8"))
VECTORS: list[dict[str, Any]] = DOCUMENT["vectors"]


def split_payload(vector: dict[str, Any]) -> tuple[bytes, int, bytes]:
    """Split an on-the-wire payload into (ciphertext, counter, mic).

    Both directions share this framing — that is the point of D-008. The only
    difference is the leading device-information byte, present in advertising
    and implicit in a write.
    """
    payload = bytes.fromhex(vector["payload"])
    if vector["direction"] == "advertising":
        payload = payload[1:]
    ciphertext = payload[:-8]
    counter = int.from_bytes(payload[-8:-4], "little")
    mic = payload[-MIC_LENGTH:]
    return ciphertext, counter, mic


def library_decrypt(key: bytes, nonce: bytes, ct: bytes, mic: bytes) -> bytes | None:
    try:
        return AESCCM(key, tag_length=MIC_LENGTH).decrypt(nonce, ct + mic, None)
    except InvalidTag:
        return None


def ids(vectors: list[dict[str, Any]]) -> list[str]:
    return [v["name"] for v in vectors]


def test_the_file_covers_what_the_spec_promises() -> None:
    """§5.4 requires both directions, ten or more vectors, and replay negatives."""
    assert len(VECTORS) >= 10
    directions = {v["direction"] for v in VECTORS}
    assert directions == {"advertising", "write"}
    reasons = {v.get("reject_reason") for v in VECTORS}
    assert "mic_mismatch_cross_direction" in reasons
    assert "counter_not_increasing" in reasons
    assert {v["name"] for v in VECTORS} == {v["name"] for v in VECTORS}


@pytest.mark.parametrize("vector", VECTORS, ids=ids(VECTORS))
def test_nonce_matches_the_specified_construction(vector: dict[str, Any]) -> None:
    """§5.1: MAC || 0xD2 0xFC || device-info || counter u32 LE."""
    expected = (
        bytes.fromhex(vector["mac"].replace(":", ""))
        + bytes.fromhex(DOCUMENT["constants"]["uuid16"])
        + bytes.fromhex(vector["device_info_byte"])
        + vector["counter"].to_bytes(4, "little")
    )
    assert bytes.fromhex(vector["nonce"]) == expected
    assert len(expected) == 13


@pytest.mark.parametrize("vector", VECTORS, ids=ids(VECTORS))
def test_device_info_byte_matches_direction(vector: dict[str, Any]) -> None:
    """§5.1: 0x41 for advertising, 0xFF for writes. This is the replay defence."""
    constants = DOCUMENT["constants"]
    expected = (
        constants["device_info_byte_advertising"]
        if vector["direction"] == "advertising"
        else constants["device_info_byte_write"]
    )
    assert vector["device_info_byte"] == expected


@pytest.mark.parametrize("vector", VECTORS, ids=ids(VECTORS))
def test_payload_framing(vector: dict[str, Any]) -> None:
    """§5.3 / D-008: ciphertext || counter || MIC, in both directions."""
    ciphertext, counter, mic = split_payload(vector)
    assert len(mic) == MIC_LENGTH
    assert counter == vector["counter"]
    if vector["mic_valid"]:
        assert ciphertext.hex() == vector["ciphertext"]
        assert mic.hex() == vector["mic"]


@pytest.mark.parametrize("vector", VECTORS, ids=ids(VECTORS))
def test_both_implementations_agree(vector: dict[str, Any]) -> None:
    """The whole point of the cross-check: library and reference must match."""
    key = bytes.fromhex(vector["bindkey"])
    nonce = bytes.fromhex(vector["nonce"])
    ciphertext, _, mic = split_payload(vector)

    from_library = library_decrypt(key, nonce, ciphertext, mic)
    from_reference = ref.decrypt(key, nonce, ciphertext, mic)
    assert from_library == from_reference

    if vector["mic_valid"]:
        assert from_library is not None
        assert from_library.hex() == vector["plaintext"]
    else:
        assert from_library is None


@pytest.mark.parametrize(
    "vector",
    [v for v in VECTORS if v["expect"] == "accept"],
    ids=ids([v for v in VECTORS if v["expect"] == "accept"]),
)
def test_accepted_vectors_pass_the_counter_policy(vector: dict[str, Any]) -> None:
    """§5.2: an accepted write is strictly above the last accepted counter."""
    last = vector.get("last_accepted_counter")
    if last is not None:
        assert vector["counter"] > last


@pytest.mark.parametrize(
    "vector",
    [v for v in VECTORS if v.get("reject_reason") == "counter_not_increasing"],
    ids=ids([v for v in VECTORS if v.get("reject_reason") == "counter_not_increasing"]),
)
def test_counter_rejections_are_policy_not_crypto(vector: dict[str, Any]) -> None:
    """These are the subtle ones: the MIC verifies, and they must still fail.

    A device that only checks the MIC would accept a byte-perfect replay of an
    old write. The counter check is what closes it.
    """
    assert vector["mic_valid"] is True
    assert vector["counter"] <= vector["last_accepted_counter"]

    key = bytes.fromhex(vector["bindkey"])
    nonce = bytes.fromhex(vector["nonce"])
    ciphertext, _, mic = split_payload(vector)
    assert ref.decrypt(key, nonce, ciphertext, mic) is not None


def test_cross_direction_replay_only_fails_on_the_nonce() -> None:
    """Pin down *why* the cross-direction replay fails.

    The captured bytes are authentic; they verify perfectly under the nonce that
    produced them. It is solely the device-information byte in the nonce that
    makes them fail in the other direction — so the defence is the nonce split
    (§5.1) and nothing else.
    """
    replayed = next(v for v in VECTORS if v["name"] == "replay-advertisement-as-write")
    original = next(v for v in VECTORS if v["name"] == "adv-single-light")

    key = bytes.fromhex(replayed["bindkey"])
    ciphertext, _, mic = split_payload(replayed)

    # Under the write nonce (device-info 0xFF): rejected.
    assert ref.decrypt(key, bytes.fromhex(replayed["nonce"]), ciphertext, mic) is None

    # The very same bytes under the advertising nonce (0x41): accepted.
    recovered = ref.decrypt(key, bytes.fromhex(original["nonce"]), ciphertext, mic)
    assert recovered is not None
    assert recovered.hex() == original["plaintext"]


def test_generator_is_deterministic() -> None:
    """Regenerating on an unchanged spec must leave the file byte-identical.

    Otherwise a stray regeneration produces a diff that reviewers learn to
    ignore, and a real change to the contract hides in the noise.
    """
    before = OUTPUT.read_bytes()
    subprocess.run(
        [sys.executable, "-m", "tools.gen_test_vectors"],
        check=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert OUTPUT.read_bytes() == before

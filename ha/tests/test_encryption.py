"""The receiver half of §5: encrypted advertising, sealed writes, counters.

The acceptance criterion names the cases, and they are the ones that matter
because each fails silently on a real device: a wrong key looks like a device
that has nothing to offer, and a counter that goes backwards looks like a
control that has stopped working.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.core import HomeAssistant
import pytest

from custom_components.bthome_writable.const import (
    CONF_BINDKEY,
    CONF_WRITE_COUNTER,
    COUNTER_STRIDE,
    DEVICE_INFO_BYTE_ADVERTISING,
    DEVICE_INFO_BYTE_WRITE,
)
from custom_components.bthome_writable.coordinator import BTHomeWritableCoordinator
from custom_components.bthome_writable.protocol import (
    decrypt_advertising,
    is_encrypted,
    nonce,
    seal_write,
    split_sealed,
)

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "test-vectors" / "test-vectors.json"
    ).read_text(encoding="utf-8")
)["vectors"]

ADVERTISING = [v for v in VECTORS if v["direction"] == "advertising"]
WRITES = [v for v in VECTORS if v["direction"] == "write"]


@pytest.mark.parametrize("vector", ADVERTISING, ids=lambda v: v["name"])
def test_advertising_vectors(vector) -> None:
    """The shared contract of §5.4, from the receiver's side."""
    key = bytes.fromhex(vector["bindkey"])
    payload = bytes.fromhex(vector["payload"])
    got = decrypt_advertising(payload, key, vector["mac"])

    if vector["mic_valid"]:
        assert got == bytes.fromhex(vector["plaintext"])
    else:
        # `replay-write-as-advertisement`: the nonce's device-info byte differs,
        # so the MIC cannot verify. That is §5.1 doing its whole job.
        assert got is None


@pytest.mark.parametrize(
    "vector", [v for v in WRITES if v.get("mic_valid")], ids=lambda v: v["name"]
)
def test_write_vectors(vector) -> None:
    key = bytes.fromhex(vector["bindkey"])
    sealed = seal_write(
        bytes.fromhex(vector["plaintext"]), key, vector["mac"], vector["counter"]
    )
    assert sealed.hex() == vector["payload"]


def test_a_write_and_an_advertisement_never_share_a_nonce() -> None:
    """§5.1's entire mechanism, stated as a property rather than a vector: the
    direction is in the nonce, so neither recording can be replayed as the
    other, and nothing extra travels on the wire to say so."""
    address = "A4:C1:38:8E:1F:2B"
    assert nonce(address, DEVICE_INFO_BYTE_ADVERTISING, 7) != nonce(
        address, DEVICE_INFO_BYTE_WRITE, 7
    )


def test_a_captured_advertisement_does_not_authenticate_as_a_write() -> None:
    """The concrete form of the same thing, and the reason §4.2's strictness is
    not on its own a defence: a permissive parser would have applied this."""
    vector = next(v for v in ADVERTISING if v["mic_valid"])
    key = bytes.fromhex(vector["bindkey"])
    payload = bytes.fromhex(vector["payload"])
    ciphertext, counter, _mic = split_sealed(payload[1:])

    # Re-sealing the same plaintext as a *write* gives different bytes entirely.
    as_write = seal_write(
        bytes.fromhex(vector["plaintext"]), key, vector["mac"], counter
    )
    assert as_write[: len(ciphertext)] != ciphertext


def test_encrypted_service_data_is_recognised_without_the_key() -> None:
    """The device-information byte is the only thing readable unsealed, which is
    why the config flow can ask for a key before it knows anything else."""
    vector = ADVERTISING[0]
    assert is_encrypted(bytes.fromhex(vector["payload"]))
    assert not is_encrypted(bytes.fromhex("4000090161"))


def test_a_wrong_key_reads_as_nothing_rather_than_as_garbage(
    hass: HomeAssistant,
) -> None:
    """A mistyped key must not produce a plausible-looking declaration. It
    produces None, which the flow turns into an error the user can act on."""
    vector = next(v for v in ADVERTISING if v["mic_valid"])
    wrong = bytes(16)
    assert (
        decrypt_advertising(bytes.fromhex(vector["payload"]), wrong, vector["mac"])
        is None
    )


def test_the_counter_never_repeats_across_a_restart(hass: HomeAssistant) -> None:
    """§5.2. Home Assistant resumes from the persisted *mark*, not from the last
    counter used, so the values between the last save and a crash are given up
    rather than sent again -- to the device a repeat is indistinguishable from
    an attack, and it refuses it silently."""
    saved: list[int] = []
    first = BTHomeWritableCoordinator(
        hass, "A4:C1:38:8E:1F:2B", on_counter=saved.append
    )

    used = [first.next_write_counter() for _ in range(3)]
    assert used == [1, 2, 3]
    assert saved, "the first write must persist a mark"

    # Restart: nothing carries over but what was written down.
    second = BTHomeWritableCoordinator(
        hass, "A4:C1:38:8E:1F:2B", write_counter=saved[-1], on_counter=saved.append
    )
    resumed = second.next_write_counter()

    assert resumed > max(used)
    assert resumed >= COUNTER_STRIDE


def test_resynchronising_jumps_forward(hass: HomeAssistant) -> None:
    """Forward is the only safe direction: a device MUST accept a jump and MUST
    refuse a repeat, so a receiver that has lost its place can recover but
    cannot be talked into reusing a counter."""
    coordinator = BTHomeWritableCoordinator(hass, "A4:C1:38:8E:1F:2B")
    before = coordinator.next_write_counter()
    after = coordinator.resynchronise()

    assert after > before
    assert coordinator.next_write_counter() > after


def test_the_entry_carries_the_key_and_the_counter() -> None:
    """Both belong to the device rather than to a session: a key the user typed
    once, and a counter that must outlive a restart."""
    assert CONF_BINDKEY == "bindkey"
    assert CONF_WRITE_COUNTER == "write_counter"

"""The receiver half of §5: encrypted advertising, sealed writes, counters.

The acceptance criterion names the cases, and they are the ones that matter
because each fails silently on a real device: a wrong key looks like a device
that has nothing to offer, and a counter that goes backwards looks like a
control that has stopped working.
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest

from custom_components.bthome_writable import coordinator as coordinator_module
from custom_components.bthome_writable.const import (
    CONF_BINDKEY,
    CONF_WRITE_COUNTER,
    COUNTER_STRIDE,
    DEVICE_INFO_BYTE_ADVERTISING,
    DEVICE_INFO_BYTE_READ,
    DEVICE_INFO_BYTE_WRITE,
    RESYNC_JUMP,
)
from custom_components.bthome_writable.coordinator import (
    BTHomeWritableCoordinator,
    WriteFailed,
)
from custom_components.bthome_writable.protocol import (
    Declaration,
    characteristic_uuid,
    decrypt_advertising,
    is_encrypted,
    nonce,
    nonce_address,
    objects_at,
    open_counter_report,
    open_read,
    parse_declaration,
    seal,
    seal_write,
    split_sealed,
)

from .conftest import settle, setup_device

VECTORS = json.loads(
    (
        Path(__file__).resolve().parents[2] / "test-vectors" / "test-vectors.json"
    ).read_text(encoding="utf-8")
)["vectors"]

ADVERTISING = [v for v in VECTORS if v["direction"] == "advertising"]
WRITES = [v for v in VECTORS if v["direction"] == "write"]
READS = [v for v in VECTORS if v["direction"] == "read"]


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


@pytest.mark.parametrize("vector", READS, ids=lambda v: v["name"])
def test_read_vectors(vector) -> None:
    """§4.3, §5.1: a sealed read opens under the read direction, 0xFE."""
    key = bytes.fromhex(vector["bindkey"])
    assert open_read(
        bytes.fromhex(vector["payload"]), key, vector["mac"]
    ) == bytes.fromhex(vector["plaintext"])


def test_a_sealed_read_does_not_open_as_anything_else() -> None:
    """The replay vector: the read's bytes, presented as a write, fail -- and a
    write does not open as a read either."""
    read = next(v for v in READS)
    key = bytes.fromhex(read["bindkey"])
    write = seal_write(
        bytes.fromhex(read["plaintext"]), key, read["mac"], read["counter"]
    )
    assert open_read(write, key, read["mac"]) is None


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


def test_every_sealed_vector_carries_a_readable_declaration() -> None:
    """The cross-suite contract, checked rather than assumed (rule 7).

    The generator claimed draft.6 for two commits while still emitting the
    declaration without its length byte: the advertising fixtures had been
    updated and these had not, so §8's sealed examples disagreed with §2.1 and
    nothing noticed, because every test that opened them only checked the
    crypto. Parsing what comes out closes that.
    """
    for vector in ADVERTISING:
        if not vector["mic_valid"]:
            continue
        objects = decrypt_advertising(
            bytes.fromhex(vector["payload"]),
            bytes.fromhex(vector["bindkey"]),
            vector["mac"],
        )
        assert objects is not None, vector["name"]
        declaration = parse_declaration(bytes(objects))
        assert declaration is not None, vector["name"]
        assert declaration.offered, vector["name"]


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


async def test_a_keyed_device_that_advertises_in_clear_is_refused_loudly(
    hass: HomeAssistant,
) -> None:
    """The failure that has no symptom, turned into one that does.

    A Puck.js reflashed from the encrypted example to the plain one kept its
    bindkey in the config entry. Every write was sealed, the device rejected the
    whole payload per section 4.2, and nothing was logged -- the control simply
    stopped working (D-042). Refusing is also the only safe answer: downgrading
    to plaintext would hand unsealed writes to anyone able to make a keyed
    device look unencrypted.
    """
    coordinator = BTHomeWritableCoordinator(
        hass, "A4:C1:38:8E:1F:2B", bindkey=bytes(range(16))
    )
    coordinator.advertises_encrypted = False

    with pytest.raises(WriteFailed, match="advertising in clear"):
        await coordinator._write_now(1, b"\x01")


async def test_an_unkeyed_receiver_refuses_to_write_to_a_sealed_device(
    hass: HomeAssistant,
) -> None:
    """The mirror of D-042, and the half that was silent.

    With no key the write goes out in clear, the device discards the whole
    payload, and §4.2 has already acknowledged it -- so Home Assistant
    reports success and the actuator does not move. A latency campaign that
    reflashes a device unencrypted, plus the re-add that follows, leaves a
    receiver in exactly this state (D-079); it took an hour of looking at
    counters before the missing key was the answer.
    """
    coordinator = BTHomeWritableCoordinator(hass, "A4:C1:38:8E:1F:2B")
    coordinator.advertises_encrypted = True
    coordinator.declaration = Declaration.restore(
        {"layout": [0x1E], "settings_revision": None}
    )

    with pytest.raises(WriteFailed, match="no bindkey is configured"):
        await coordinator._write_now(1, b"\x01")


async def test_a_keyed_device_still_seals_before_the_first_advertisement(
    hass: HomeAssistant,
) -> None:
    """`None` is not `False`. Having heard nothing yet is not evidence that the
    device is plain, and refusing then would break every write issued before the
    first advertisement arrives."""
    coordinator = BTHomeWritableCoordinator(
        hass, "A4:C1:38:8E:1F:2B", bindkey=bytes(range(16))
    )
    assert coordinator.advertises_encrypted is None
    coordinator.declaration = parse_declaration(bytes.fromhex("0009ff011e"))

    # Past the downgrade guard, so it fails later -- on there being no device.
    with (
        patch.object(
            coordinator_module.bluetooth,
            "async_ble_device_from_address",
            return_value=None,
        ),
        pytest.raises(WriteFailed, match="not reachable"),
    ):
        await coordinator._write_now(1, b"\x01")


def test_a_recreated_entry_does_not_resume_below_the_device(
    hass: HomeAssistant,
) -> None:
    """D-063, found on hardware. A device refuses any write counter at or below
    the highest it has accepted -- replay protection, working correctly -- and
    refuses it *after* acknowledging the write, so nothing is visible from Home
    Assistant. A config entry that is younger than the device therefore writes
    into a void: the switch toggles, the action reports success, the device
    never changes.

    Seeding from the clock closes it without asking the device anything, because
    wall time is above every counter any earlier receiver can have sent. The
    device in the hardware test sat at 100135, decades below the clock.
    """
    from custom_components.bthome_writable import _starting_counter

    fresh = _starting_counter(0)
    assert fresh > 100_135, "a re-created entry must clear a device's stored mark"
    assert fresh <= int(time.time())

    # An installation that has been running keeps its own place: the stored mark
    # is ahead of the clock and must not be thrown away.
    ahead = int(time.time()) + 10_000
    assert _starting_counter(ahead) == ahead


@pytest.mark.usefixtures("custom_integration")
async def test_a_keyed_device_offers_a_way_to_resynchronise(
    hass: HomeAssistant, radio, gatt
) -> None:
    """§5.3 asks a receiver to offer resynchronisation. The clock seed covers the
    ordinary way of falling behind; a device whose own flash was restored can
    still be ahead, and then this is the only move that is not a reflash."""
    from custom_components.bthome_writable.const import CONF_BINDKEY

    entry = await setup_device(
        hass, radio, "single-light", entry_data={CONF_BINDKEY: "00" * 16}
    )
    coordinator = entry.runtime_data

    resync = "button.espruino_light_resynchronise_write_counter"
    assert hass.states.get(resync) is not None

    before = coordinator.next_write_counter()
    await hass.services.async_call(
        "button", "press", {"entity_id": resync}, blocking=True
    )
    await settle(hass)

    assert coordinator.next_write_counter() > before + RESYNC_JUMP - 1


@pytest.mark.usefixtures("custom_integration")
async def test_a_plain_device_is_offered_no_such_button(
    hass: HomeAssistant, radio, gatt
) -> None:
    """It would have nothing to do, and a control that does nothing is worse
    than none: the user presses it when something else is wrong."""
    await setup_device(hass, radio, "single-light")
    assert hass.states.get("button.espruino_light_resynchronise_write_counter") is None


# --- the device-information byte is a bitfield, not a value ------------------
#
# Every fixture in this repo is 0x40 or 0x41, because the reference firmware
# sets no other flag. Reading the byte as a value therefore passed every test
# while working with exactly one firmware (found in review, D-068).

SLEEPY_ENCRYPTED = 0x45  # v2 | encrypted | trigger-based
MAC_INCLUDED_PLAIN = 0x42  # v2 | MAC in the payload
MAC_INCLUDED_ENCRYPTED = 0x43  # v2 | encrypted | MAC in the payload


def test_a_sleepy_device_is_still_an_encrypted_one() -> None:
    """0x45, which a trigger-based BTHome device transmits. Comparing the byte
    with 0x41 called it plain, and the receiver then read ciphertext as
    objects."""
    assert is_encrypted(bytes([SLEEPY_ENCRYPTED, 0x00]))
    assert is_encrypted(bytes([0x41, 0x00]))
    assert not is_encrypted(bytes([0x40, 0x00]))
    assert not is_encrypted(bytes([0x44, 0x00]))  # sleepy, in clear


def test_the_objects_start_after_the_header_the_flags_describe() -> None:
    """Bit 1 puts six bytes of MAC between the device-information byte and the
    first object. `bthome-ble` skips seven bytes for it; so must this."""
    assert objects_at(bytes([0x40])) == 1
    assert objects_at(bytes([MAC_INCLUDED_PLAIN])) == 7
    assert objects_at(bytes([MAC_INCLUDED_ENCRYPTED])) == 7


def test_the_nonce_uses_the_mac_the_device_put_in_the_packet() -> None:
    """They differ for a device advertising under a random address, and the
    device sealed with the one it transmitted."""
    packet = bytes([MAC_INCLUDED_ENCRYPTED]) + bytes.fromhex("aabbccddeeff") + b"rest"
    assert nonce_address(packet, "A4:C1:38:8E:1F:2B") == "AA:BB:CC:DD:EE:FF"
    assert nonce_address(bytes([0x41]) + b"rest", "A4:C1:38:8E:1F:2B") == (
        "A4:C1:38:8E:1F:2B"
    )


def test_a_sealed_advertisement_opens_under_whatever_byte_it_carried() -> None:
    """§5.1 says the nonce carries the device-information byte *as transmitted*.
    Sealing under 0x45 and opening under 0x41 authenticates nothing."""
    key = bytes(range(16))
    address = "A4:C1:38:8E:1F:2B"
    objects = bytes.fromhex("000109ff011e")

    sealed = bytes([SLEEPY_ENCRYPTED]) + seal(
        objects, key, address, SLEEPY_ENCRYPTED, 7
    )
    assert decrypt_advertising(sealed, key, address) == objects

    # The same bytes labelled as the reference firmware's are a different
    # nonce, and must not authenticate.
    mislabelled = bytes([DEVICE_INFO_BYTE_ADVERTISING]) + sealed[1:]
    assert decrypt_advertising(mislabelled, key, address) is None


def test_an_encrypted_packet_carrying_its_mac_opens() -> None:
    """The header is seven bytes and the nonce is built from the MAC inside
    it -- both wrong before the review, and wrong in the same packet."""
    key = bytes(range(16))
    advertised = "A4:C1:38:8E:1F:2B"
    inside = "AA:BB:CC:DD:EE:FF"
    objects = bytes.fromhex("000109ff011e")

    sealed = (
        bytes([MAC_INCLUDED_ENCRYPTED])
        + bytes.fromhex("aabbccddeeff")
        + seal(objects, key, inside, MAC_INCLUDED_ENCRYPTED, 9)
    )
    assert decrypt_advertising(sealed, key, advertised) == objects


# --- the counter report (D-075) ---------------------------------------------


def counter_report(counter: int, challenge: bytes, key: bytes, address: str) -> bytes:
    """What a device offering the characteristic answers: seal(challenge || n)."""
    return seal(
        challenge + counter.to_bytes(4, "little"),
        key,
        address,
        DEVICE_INFO_BYTE_READ,
        11,
    )


def test_a_counter_report_answers_the_challenge_it_was_given() -> None:
    key, address, challenge = bytes(range(16)), "A4:C1:38:8E:1F:2B", b"12345678"
    report = counter_report(4242, challenge, key, address)

    assert open_counter_report(report, key, address, challenge) == 4242


def test_a_report_for_another_challenge_is_refused() -> None:
    """This is the whole point of the challenge. Sealing stops a forgery, but a
    report captured earlier is genuine and stale, and a receiver that has just
    lost its state has nothing else to judge it by — it cannot know what counter
    to expect, which is why it is asking (D-075)."""
    key, address = bytes(range(16)), "A4:C1:38:8E:1F:2B"
    captured = counter_report(7, b"OLDNONCE", key, address)

    assert open_counter_report(captured, key, address, b"NEWNONCE") is None


def test_a_report_under_another_key_is_refused() -> None:
    key, address, challenge = bytes(range(16)), "A4:C1:38:8E:1F:2B", b"12345678"
    report = counter_report(7, challenge, bytes(16), address)

    assert open_counter_report(report, key, address, challenge) is None


def test_a_report_of_the_wrong_length_is_refused() -> None:
    """Truncated or padded, it is not the thing we asked for."""
    key, address, challenge = bytes(range(16)), "A4:C1:38:8E:1F:2B", b"12345678"
    short = seal(challenge + b"\x01", key, address, DEVICE_INFO_BYTE_READ, 11)

    assert open_counter_report(short, key, address, challenge) is None


def test_the_receiver_asks_for_the_counter_by_default() -> None:
    """D-080, pinned so that turning it off again has to be deliberate.

    It was off while it was a protocol addition nobody had ruled on. It is on
    because the case it answers is not the unusual one: §5.3 has a device
    resume strictly above anything it accepted, so every reboot puts it ahead of
    the receiver and nothing tells the receiver. Reproduced from nothing more
    than a reflash, twice (D-078 fault 1, D-079).
    """
    from custom_components.bthome_writable.const import ALLOW_COUNTER_SYNC

    assert ALLOW_COUNTER_SYNC is True


async def test_asking_the_device_resumes_above_what_it_reports(
    hass: HomeAssistant, gatt
) -> None:
    """The whole point: the receiver's own counter is irrelevant, including when
    it is wildly behind after a reboot it never saw."""
    key, address = bytes(range(16)), "A4:C1:38:8E:1F:2B"
    marks: list[int] = []
    coordinator = BTHomeWritableCoordinator(
        hass, address, bindkey=key, write_counter=10, on_counter=marks.append
    )
    gatt.offer_counter_report(
        lambda: counter_report(900_000, gatt.writes[-1][1], key, address)
    )

    adopted = await coordinator.async_sync_write_counter()

    assert adopted == 900_001, "strictly above what the device last accepted"
    assert coordinator.next_write_counter() >= 900_001
    assert marks, "the mark is persisted, or a restart loses the jump again"
    assert gatt.disconnects == 1, "the link is not held open"


async def test_a_device_without_the_report_is_left_exactly_as_it_was(
    hass: HomeAssistant, gatt
) -> None:
    """Most devices will not offer it, and they must be no worse off: the clock
    seed of D-064 stands, nothing raises, and the stale GATT table that could
    be hiding the characteristic is dropped (D-012)."""
    coordinator = BTHomeWritableCoordinator(
        hass, "A4:C1:38:8E:1F:2B", bindkey=bytes(range(16)), write_counter=77
    )

    assert await coordinator.async_sync_write_counter() is None
    assert coordinator.next_write_counter() == 78, "the seeded counter stands"
    assert gatt.disconnects == 2, "looked twice, and let go of the link each time"


async def test_the_report_is_looked_for_again_behind_a_stale_cache(
    hass: HomeAssistant, gatt
) -> None:
    """The fault that made this feature do nothing on the bench the first time
    it mattered (D-080).

    A device that has just gained the characteristic is exactly a device whose
    GATT table changed, so the copy Home Assistant holds does not have it. The
    first look therefore finds nothing. Dropping the cache and returning -- as
    it used to -- means the one connection the receiver spends is always the
    one that cannot succeed, and on a device whose firmware changes that is
    every time. Measured: the sealed loop failed, a reload fixed it.
    """
    key, address = bytes(range(16)), "A4:C1:38:8E:1F:2B"
    coordinator = BTHomeWritableCoordinator(
        hass, address, bindkey=key, write_counter=10
    )

    async def reveal() -> None:
        """What dropping a stale table does: the next look sees the truth."""
        gatt.cache_cleared += 1
        gatt.offer_counter_report(
            lambda: counter_report(900_000, gatt.writes[-1][1], key, address)
        )

    gatt.clear_cache = reveal

    assert await coordinator.async_sync_write_counter() == 900_001
    assert gatt.cache_cleared == 1, "cleared once, not on every attempt"
    assert gatt.connections == 2, "and the second connection is the useful one"


async def test_a_plain_device_is_never_asked(hass: HomeAssistant, gatt) -> None:
    """There is nothing to ask and no way to authenticate an answer."""
    coordinator = BTHomeWritableCoordinator(hass, "A4:C1:38:8E:1F:2B")

    assert await coordinator.async_sync_write_counter() is None
    assert gatt.connections == 0, "and no connection is spent finding out"


async def test_a_replayed_report_leaves_the_counter_alone(
    hass: HomeAssistant, gatt
) -> None:
    """A report captured earlier is genuine and stale. Adopting it would walk
    the receiver *backwards*, which is the one direction §5.3 forbids -- so a
    stale answer has to be worth less than no answer."""
    key, address = bytes(range(16)), "A4:C1:38:8E:1F:2B"
    coordinator = BTHomeWritableCoordinator(
        hass, address, bindkey=key, write_counter=5_000
    )
    gatt.offer_counter_report(counter_report(7, b"OLDNONCE", key, address))

    assert await coordinator.async_sync_write_counter() is None
    assert coordinator.next_write_counter() == 5_001, "not rolled back to 8"


def test_the_counter_characteristic_is_not_an_entry() -> None:
    """§4.1 splits the range: 0001-0FFF are entries, 1000 and above are the
    protocol's own. A declaration carries at most 255 entries, so nothing can
    ever reach the reserved block."""
    from custom_components.bthome_writable.const import COUNTER_UUID

    assert characteristic_uuid(1) != COUNTER_UUID
    assert characteristic_uuid(0x1000) == COUNTER_UUID
    assert characteristic_uuid(255) != COUNTER_UUID, "past every possible entry"

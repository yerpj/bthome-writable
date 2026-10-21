"""D-117: a write that reports success must have evidence of it, and the radio
that carries it must be one that hears the device.

Found on the owner's own Puck.js. Four commands, the switch flipping each time,
not one log line, and the lamp never moved. Home Assistant had chosen an ESP32
Bluetooth proxy twelve metres and two walls away which had not heard the device
once in forty seconds; the local adapter heard it every second at -76 dBm. The
proxy connected, the write was acknowledged, and nothing arrived: over a proxy
the ATT response is produced on the far side of Wi-Fi by something that is not
the device, and §4.2 rests on that response being the confirmation.

So two things, both in this integration and neither on the wire: choose a source
that hears the device, and check an acknowledged write against the device
itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import pytest

from custom_components.bthome_writable import coordinator as coordinator_module
from custom_components.bthome_writable.coordinator import BTHomeWritableCoordinator

from .conftest import DEFAULT_ADDRESS, UUID_TEMPLATE, settle, setup_device

pytestmark = pytest.mark.usefixtures("custom_integration")

LIGHT = "switch.espruino_light_light"
TARGET = "number.espruino_light_temperature"
POWER = "switch.espruino_light_power"


# --- the write that is checked against the device ---------------------------


async def test_a_write_the_device_did_not_take_is_not_passed_over_in_silence(
    hass: HomeAssistant, radio, gatt, caplog: pytest.LogCaptureFixture
) -> None:
    """The bench incident: acknowledged, and the value never moved.

    `echo_writes = False` is a device that answers the write and changes
    nothing, which is what a proxy losing the write looks like from here -- and
    also what a device that has not republished the entry yet looks like, which
    is why this is a warning and not a failure (D-122). D-117 asked for one
    thing, that it not be silent, and this is it.
    """
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    gatt.echo_writes = False

    await hass.services.async_call(
        "number", "set_value", {"entity_id": TARGET, "value": 22}, blocking=True
    )
    await settle(hass)

    assert gatt.writes, "the write was attempted"
    assert "still reports the value it had" in caplog.text
    assert float(hass.states.get(TARGET).state) == 22, (
        "and what was written is kept, because nothing disproved it"
    )


async def test_a_device_that_applies_the_write_later_is_not_called_broken(
    hass: HomeAssistant, radio, gatt, caplog: pytest.LogCaptureFixture
) -> None:
    """Measured on the bench, 2026-10-21, and the reason D-120 was demoted.

    @enaon's entry list on our own board. Every `turn_on` confirmed and every
    `turn_off` reported failed, while the board's own console showed the lamp
    off: `isOn:false, bri:0`. §4.3's getter is published, not served on demand,
    so a read answers with whatever the device sealed when it last published,
    and a fade republishes before the fade is over.

    A device that reports the value it had is therefore not evidence of
    anything, and the command must not come back as an error.
    """
    gatt.declare(1, readable={1: bytes.fromhex("1E01")})
    await setup_device(hass, radio, "single-light")
    await settle(hass)
    gatt.echo_writes = False  # the lamp is fading; the published value lags

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)

    assert gatt.writes[-1] == (UUID_TEMPLATE.format(1), bytes.fromhex("1e00"))
    assert "did not reach the device" not in caplog.text, (
        "it reached the device: the lamp was off and the entry was not yet "
        "republished, which no receiver can tell apart from a lost write"
    )


async def test_calling_it_a_failure_is_one_constant_away(
    hass: HomeAssistant, radio, gatt
) -> None:
    """What D-120 shipped, kept behind `AN_UNCHANGED_ENTRY_FAILS_THE_WRITE`.

    It is the right answer for a device whose entries are served from state the
    write has already changed, and the owner's to decide, because the mechanism
    that settles it for every device is the write counter rather than the value
    (D-122).
    """
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    gatt.echo_writes = False

    with (
        patch.object(coordinator_module, "AN_UNCHANGED_ENTRY_FAILS_THE_WRITE", True),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": TARGET, "value": 22}, blocking=True
        )
    await settle(hass)

    assert float(hass.states.get(TARGET).state) == 20, "the state is the device's"


async def test_a_device_that_keeps_its_own_value_is_not_a_failure(
    hass: HomeAssistant, radio, gatt
) -> None:
    """A dimmer that stops at 100, a setpoint quantised to half degrees.

    Something moved, so the write landed; what the device reports is the truth
    and ours was only a request. The two cases are told apart by exactly this.
    """
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    gatt.echo_writes = False
    gatt.readable[UUID_TEMPLATE.format(2)] = bytes.fromhex("5715")  # clamped to 21

    await hass.services.async_call(
        "number", "set_value", {"entity_id": TARGET, "value": 22}, blocking=True
    )
    await settle(hass)

    assert gatt.writes[-1] == (UUID_TEMPLATE.format(2), bytes.fromhex("5716"))
    assert float(hass.states.get(TARGET).state) == 21, "the device's value, not ours"


async def test_a_write_only_entry_is_written_without_a_read(
    hass: HomeAssistant, radio, gatt
) -> None:
    """There is no evidence to be had for a write-only entry (@enaon's lamp).

    The honest form is the `assumed_state` the entity already carries, so the
    write goes out, nothing is read, and nothing is claimed.
    """
    await setup_device(hass, radio, "single-light")
    gatt.declare(1)  # writable, not readable
    await settle(hass)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": LIGHT}, blocking=True
    )
    await settle(hass)

    assert gatt.writes == [(UUID_TEMPLATE.format(1), bytes.fromhex("1e01"))]
    assert gatt.reads == [], "nothing to read back"
    assert hass.states.get(LIGHT).state == "on"
    assert hass.states.get(LIGHT).attributes.get("assumed_state") is True


async def test_a_read_back_from_a_stale_table_fails_the_write(
    hass: HomeAssistant, radio, gatt
) -> None:
    """Where D-116 and D-117 meet, and the reason this branch exists.

    The read back answers with another entry's object, which is the stale cached
    table of D-116. The write was addressed through that same table, so it may
    have reached the wrong characteristic: the only honest outcome is to drop
    the table and report the command failed.
    """
    gatt.declare(2, readable={1: bytes.fromhex("1001"), 2: bytes.fromhex("5714")})
    await setup_device(hass, radio, "thermostat")
    await settle(hass)
    gatt.echo_writes = False
    gatt.readable[UUID_TEMPLATE.format(2)] = bytes.fromhex("1001")  # entry 1's object

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": TARGET, "value": 22}, blocking=True
        )
    await settle(hass)

    assert gatt.cache_cleared == 1, "dropped, so the next command rediscovers"
    assert float(hass.states.get(TARGET).state) == 20, "and nothing was claimed"


# --- the radio that carries it ---------------------------------------------


@dataclass
class FakeScanner:
    """The parts of a `habluetooth` scanner this choice looks at."""

    source: str
    scanning: bool = True
    heard: dict[str, float] | None = None

    @property
    def discovered_device_timestamps(self) -> dict[str, float]:
        """Empty for a local adapter, which keeps none (`HaScanner`)."""
        return self.heard or {}


@dataclass
class FakeAdvertisement:
    rssi: int


@dataclass
class FakeScannerDevice:
    scanner: FakeScanner
    advertisement: FakeAdvertisement
    ble_device: Any


def sources(hass: HomeAssistant, *devices: FakeScannerDevice):
    """Patch the list of connectable sources for this address."""
    return patch.object(
        coordinator_module.bluetooth,
        "async_scanner_devices_by_address",
        return_value=list(devices),
    )


def test_a_source_that_has_not_heard_the_device_is_not_chosen(
    hass: HomeAssistant,
) -> None:
    """The incident itself: the loud, deaf proxy against the quiet adapter.

    The proxy is -40 dBm on whatever it last heard and has not heard this
    device for a minute; the local adapter hears it now, at -76. Scoring on
    signal alone picks the proxy, which is what happened.
    """
    device = BTHomeWritableCoordinator(hass, DEFAULT_ADDRESS)
    proxy = FakeScannerDevice(
        FakeScanner("esp32-proxy", heard={DEFAULT_ADDRESS: time.monotonic() - 60}),
        FakeAdvertisement(-40),
        "through the proxy",
    )
    local = FakeScannerDevice(
        FakeScanner("hci0"), FakeAdvertisement(-76), "through the adapter"
    )

    with sources(hass, proxy, local):
        assert device._connectable_device() == "through the adapter"


def test_among_sources_that_hear_it_the_loudest_wins(hass: HomeAssistant) -> None:
    """With nothing to separate them on freshness, this is the stack's own
    signal and there is no reason to differ from it."""
    device = BTHomeWritableCoordinator(hass, DEFAULT_ADDRESS)
    near = FakeScannerDevice(
        FakeScanner("esp32-proxy", heard={DEFAULT_ADDRESS: time.monotonic()}),
        FakeAdvertisement(-41),
        "through the proxy",
    )
    far = FakeScannerDevice(
        FakeScanner("hci0"), FakeAdvertisement(-88), "through the adapter"
    )

    with sources(hass, near, far):
        assert device._connectable_device() == "through the proxy"


def test_a_scanner_that_is_not_scanning_is_not_a_path(hass: HomeAssistant) -> None:
    device = BTHomeWritableCoordinator(hass, DEFAULT_ADDRESS)
    stopped = FakeScannerDevice(
        FakeScanner("hci0", scanning=False), FakeAdvertisement(-30), "stopped"
    )
    running = FakeScannerDevice(
        FakeScanner("esp32-proxy"), FakeAdvertisement(-90), "running"
    )

    with sources(hass, stopped, running):
        assert device._connectable_device() == "running"


def test_with_no_source_listed_the_stacks_own_answer_stands(
    hass: HomeAssistant,
) -> None:
    """A doubtful path that fails visibly beats none at all, which fails as
    "not reachable by any adapter or proxy"."""
    device = BTHomeWritableCoordinator(hass, DEFAULT_ADDRESS)

    with (
        sources(hass),
        patch.object(
            coordinator_module.bluetooth,
            "async_ble_device_from_address",
            return_value="whatever the stack says",
        ),
    ):
        assert device._connectable_device() == "whatever the stack says"


def test_only_a_deaf_source_is_still_better_than_none(hass: HomeAssistant) -> None:
    """Chosen, because the alternative is to refuse to try."""
    device = BTHomeWritableCoordinator(hass, DEFAULT_ADDRESS)
    deaf = FakeScannerDevice(
        FakeScanner("esp32-proxy", heard={DEFAULT_ADDRESS: time.monotonic() - 600}),
        FakeAdvertisement(-70),
        "through the proxy",
    )

    with sources(hass, deaf):
        assert device._connectable_device() == "through the proxy"

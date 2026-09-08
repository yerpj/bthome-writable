"""Per-device state and the write path.

One coordinator per configured device. It watches the device's advertising —
which is the single source of truth for state (§6) — and turns entity commands
into write-all payloads delivered over a short GATT connection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import time

from bleak_retry_connector import establish_connection
from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONFIRM_WINDOW_CEILING,
    CONFIRM_WINDOW_FLOOR,
    CONFIRM_WINDOW_INTERVALS,
    DEFAULT_MAX_CONNECTIONS,
    MIN_MTU,
    SERVICE_UUID,
    WRITE_CHARACTERISTIC_UUID,
    WRITE_DEBOUNCE,
)
from .protocol import Declaration, ProtocolError, compose_write, parse_declaration

_LOGGER = logging.getLogger(__name__)

# Shared across every configured device: the cap protects the Bluetooth
# adapter's and the proxies' connection slots, which are a host resource, not a
# per-device one (decisions.md D-003).
_connection_slots: dict[int, asyncio.Semaphore] = {}


def connection_semaphore(limit: int = DEFAULT_MAX_CONNECTIONS) -> asyncio.Semaphore:
    """The process-wide connection cap, created on first use."""
    if limit not in _connection_slots:
        _connection_slots[limit] = asyncio.Semaphore(limit)
    return _connection_slots[limit]


class WriteFailed(Exception):
    """The write did not reach the device."""


class BTHomeWritableCoordinator:
    """Tracks one device's declaration and writes to it."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        *,
        name: str | None = None,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
    ) -> None:
        self.hass = hass
        self.address = address
        self.name = name or address
        self.declaration: Declaration | None = None
        self.available = False

        self._listeners: list[Callable[[], None]] = []
        self._pending: dict[int, bytes] = {}
        self._pending_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._semaphore = connection_semaphore(max_connections)

        # Advertising-interval estimate, for the adaptive confirmation window.
        self._last_seen: float | None = None
        self._interval: float | None = None

    # --- Advertising side ---------------------------------------------------

    @callback
    def async_handle_advertisement(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Absorb one advertisement: refresh the declaration and the interval."""
        self._observe_interval(service_info.time)

        payload = service_info.service_data.get("0000fcd2-0000-1000-8000-00805f9b34fb")
        if not payload:
            return

        try:
            # The device-information byte is not part of the object stream.
            declaration = parse_declaration(payload[1:])
        except ProtocolError as error:
            _LOGGER.debug(
                "%s: malformed declaration, ignoring: %s", self.address, error
            )
            return

        if declaration is None:
            return

        self.declaration = declaration
        self.available = True
        self._notify()

    def _observe_interval(self, timestamp: float) -> None:
        """Track how often this device advertises.

        A plain exponential average: the estimate only feeds the confirmation
        window, where being roughly right is enough and being slow to adapt is
        safer than jumping on one late packet.
        """
        if self._last_seen is not None:
            delta = timestamp - self._last_seen
            if 0 < delta < CONFIRM_WINDOW_CEILING:
                self._interval = (
                    delta
                    if self._interval is None
                    else 0.7 * self._interval + 0.3 * delta
                )
        self._last_seen = timestamp

    @property
    def confirm_window(self) -> float:
        """How long an unconfirmed value may stay on screen (§6, D-007)."""
        if self._interval is None:
            return CONFIRM_WINDOW_FLOOR
        return min(
            CONFIRM_WINDOW_CEILING,
            max(CONFIRM_WINDOW_FLOOR, CONFIRM_WINDOW_INTERVALS * self._interval),
        )

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def async_set_unavailable(self) -> None:
        self.available = False
        self._notify()

    def value_at(self, position: int) -> bytes | None:
        """The last advertised value of the object at `position`."""
        if self.declaration is None:
            return None
        for obj in self.declaration.objects:
            if obj.position == position:
                return obj.value
        return None

    # --- Write side ---------------------------------------------------------

    async def async_write(self, position: int, value: bytes) -> None:
        """Queue a new value and flush after a short coalescing delay.

        Coalescing is per position with last-value-wins: dragging a slider must
        produce one write, not one per pixel.
        """
        async with self._pending_lock:
            self._pending[position] = value
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = self.hass.async_create_task(self._flush_soon())

    async def _flush_soon(self) -> None:
        await asyncio.sleep(WRITE_DEBOUNCE)
        async with self._pending_lock:
            changes = dict(self._pending)
            self._pending.clear()
        if changes:
            await self._write_now(changes)

    async def _write_now(self, changes: dict[int, bytes]) -> None:
        """Compose one write-all payload and deliver it (§4.2)."""
        if self.declaration is None:
            raise WriteFailed(
                f"{self.address}: no declaration seen yet, refusing to write"
            )

        # §4.2's payload is composed from the *current* advertisement, never
        # from a layout cached at setup: a device reflashed with a different
        # object order must not receive a write against the old one.
        payload = compose_write(self.declaration, changes)

        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise WriteFailed(f"{self.address}: not reachable by any adapter or proxy")

        started = time.monotonic()
        async with self._semaphore:
            client = await establish_connection(
                client_class=__import__("bleak", fromlist=["BleakClient"]).BleakClient,
                device=device,
                name=self.address,
                max_attempts=2,
            )
            try:
                await self._request_mtu(client)
                await client.write_gatt_char(
                    WRITE_CHARACTERISTIC_UUID, payload, response=True
                )
            finally:
                await client.disconnect()

        _LOGGER.debug(
            "%s: wrote %s in %.0f ms",
            self.address,
            payload.hex(),
            (time.monotonic() - started) * 1000,
        )

    async def _request_mtu(self, client: object) -> None:
        """Ask for an MTU large enough for text writes (§4.4).

        Best effort: several backends negotiate the MTU themselves and expose no
        way to ask, in which case the 20-byte default-MTU limit applies and is
        documented rather than worked around.
        """
        mtu = getattr(client, "mtu_size", None)
        if mtu is not None and mtu < MIN_MTU:
            _LOGGER.debug(
                "%s: MTU is %s, below the %s this protocol asks for; long text "
                "writes may not fit",
                self.address,
                mtu,
                MIN_MTU,
            )

    @property
    def service_uuid(self) -> str:
        return SERVICE_UUID

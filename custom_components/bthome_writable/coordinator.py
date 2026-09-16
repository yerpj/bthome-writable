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
from typing import Any

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .const import (
    ALLOW_PLAINTEXT_DOWNGRADE,
    CONFIRM_ADVERTISEMENTS,
    CONFIRM_WINDOW_CEILING,
    CONFIRM_WINDOW_FLOOR,
    CONFIRM_WINDOW_INTERVALS,
    COUNTER_STRIDE,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MTU_PAYLOAD,
    MIN_MTU,
    RESYNC_AFTER,
    RESYNC_JUMP,
    SERVICE_UUID,
    WRITE_CHARACTERISTIC_UUID,
    WRITE_DEBOUNCE,
)
from .protocol import (
    Declaration,
    ProtocolError,
    compose_write,
    decrypt_advertising,
    is_encrypted,
    parse_declaration,
    seal_write,
)

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
        bindkey: bytes | None = None,
        write_counter: int = 0,
        on_counter: Callable[[int], None] | None = None,
    ) -> None:
        self.hass = hass
        self.address = address
        self.bindkey = bindkey
        """The device's BTHome key, or None for a plain device (section 5)."""

        self.advertises_encrypted: bool | None = None
        """Whether the last advertisement was sealed, or None before the first.

        Kept because a bindkey says what the *receiver* was told, and this says
        what the device is actually doing. When they disagree the write is
        refused rather than downgraded -- see `_write_now`."""

        self._counter = write_counter
        self._counter_mark = write_counter
        self._on_counter = on_counter
        self._unconfirmed = 0
        self.name = name or address
        self.declaration: Declaration | None = None
        self.available = False
        self.advertisements = 0
        """How many advertisements this device has been heard to send.

        Entities use it to tell "the device did not answer" from "this host
        heard nothing at all" (D-011)."""

        self._listeners: list[Callable[[], None]] = []
        self._write_listeners: list[Callable[[set[int], Exception | None], None]] = []
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

        objects = self._plaintext(payload)
        if objects is None:
            return

        try:
            declaration = parse_declaration(objects)
        except ProtocolError as error:
            _LOGGER.debug(
                "%s: malformed declaration, ignoring: %s", self.address, error
            )
            return

        if declaration is None:
            return

        if self._layout_changed(declaration):
            # The device is advertising a different set of objects than it was.
            # For an Espruino device that almost always means new code, which
            # means a rebuilt GATT table — and the host's cached copy is now
            # wrong in the silent way of D-012: the next write would report
            # success and do nothing. Drop it before that happens rather than
            # after, which otherwise costs the user their first command.
            _LOGGER.debug(
                "%s: the advertised layout changed; dropping the cached GATT table",
                self.address,
            )
            self.hass.async_create_task(self.async_clear_service_cache())

        self.declaration = declaration
        self.available = True
        self.advertisements += 1
        self._notify()

    def _plaintext(self, payload: bytes) -> bytes | None:
        """The object stream, decrypting first if the device is encrypted.

        The device-information byte is never part of it. For an encrypted device
        it is also the only thing readable without the key -- everything else in
        the service data is ciphertext, which is why the config flow has to ask
        for a bindkey before it can see a declaration at all.
        """
        self.advertises_encrypted = is_encrypted(payload)
        if not self.advertises_encrypted:
            return payload[1:]

        if self.bindkey is None:
            _LOGGER.debug(
                "%s: advertising is encrypted and no bindkey is configured",
                self.address,
            )
            return None

        objects = decrypt_advertising(payload, self.bindkey, self.address)
        if objects is None:
            _LOGGER.warning(
                "%s: an advertisement did not authenticate; the bindkey may be "
                "wrong, or another device may be using this address",
                self.address,
            )
        return objects

    def next_write_counter(self) -> int:
        """The counter for the next write, persisted coarsely (section 5.2).

        A receiver MUST persist this across restarts: a restarted Home Assistant
        that resumed from zero would send counters the device has already
        accepted, and every write would be refused as a replay. Saved as a
        high-water mark ahead of the counter rather than on every write, and
        resumed *from the mark*, so the values between the last save and a crash
        are given up rather than reused.
        """
        self._counter += 1
        if self._counter >= self._counter_mark:
            self._counter_mark = self._counter + COUNTER_STRIDE
            if self._on_counter is not None:
                self._on_counter(self._counter_mark)
        return self._counter

    @callback
    def note_confirmed(self) -> None:
        """A write was confirmed: whatever the counter is, it is being accepted."""
        self._unconfirmed = 0

    @callback
    def note_unconfirmed(self) -> None:
        """A write was delivered, the device was heard, and nothing changed.

        On a plain device that is a stale GATT table or a device that simply
        refused. On an encrypted one it is most likely a counter this receiver
        has fallen behind on -- a device restored from a backup, or written to
        by something else, remembers a higher one and reads every write as a
        replay. A refused write is silent by design (§6), so nothing will ever
        say so, and a user sees a control that does nothing at all.

        Resynchronising after a couple of these is §5.2's answer. It costs
        nothing if the diagnosis is wrong: the counter space is 32 bits and a
        device must accept a forward jump.
        """
        if self.bindkey is None:
            return
        self._unconfirmed += 1
        if self._unconfirmed < RESYNC_AFTER:
            return
        _LOGGER.warning(
            "%s: %d writes in a row went unconfirmed; resynchronising the write "
            "counter, which a device that has seen higher ones would refuse "
            "silently (PROTOCOL.md section 5.2)",
            self.address,
            self._unconfirmed,
        )
        self._unconfirmed = 0
        self.resynchronise()

    def resynchronise(self) -> int:
        """Jump the counter well forward, for a device that has seen higher.

        Section 5.2 asks a receiver to offer this. A device restored from a
        backup, or a Home Assistant whose stored counter was lost, sends
        counters the device has already accepted -- and since a refused write is
        silent, the symptom is a control that simply stops working. Jumping is
        safe because the device MUST accept forward jumps.
        """
        self._counter += RESYNC_JUMP
        self._counter_mark = self._counter + COUNTER_STRIDE
        if self._on_counter is not None:
            self._on_counter(self._counter_mark)
        _LOGGER.info(
            "%s: write counter resynchronised to %d", self.address, self._counter
        )
        return self._counter

    def _layout_changed(self, declaration: Declaration) -> bool:
        """Whether this declaration describes a different device shape."""
        if self.declaration is None:
            return False
        before = [(obj.position, obj.object_id) for obj in self.declaration.objects]
        after = [(obj.position, obj.object_id) for obj in declaration.objects]
        return before != after

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

    @property
    def confirm_ceiling(self) -> float:
        """Hard upper bound on an optimistic value, however deaf the host is."""
        return CONFIRM_WINDOW_CEILING

    @property
    def confirm_advertisements(self) -> int:
        """Advertisements that must arrive after a write before reverting."""
        return CONFIRM_ADVERTISEMENTS

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
        """Queue a new value; the flush starts immediately if none is running.

        Coalescing is per position with last-value-wins, and happens behind the
        write in flight rather than in front of it: dragging a slider produces
        one write for where it started and one for where it stopped, not one
        per pixel and not one delayed by a debounce.
        """
        async with self._pending_lock:
            self._pending[position] = value
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = self.hass.async_create_task(self._flush_soon())

    @callback
    def async_add_write_listener(
        self, listener: Callable[[set[int], Exception | None], None]
    ) -> Callable[[], None]:
        """Be told when a queued write has actually reached the device.

        Entities need this to know when to start their confirmation window.
        Starting it when the value was *queued* would fold the debounce, the
        connection setup and the disconnect into a window that is meant to
        measure only how long the device takes to refresh its advertising
        (§6) — and connection setup alone is seconds, so that would be most of
        the budget spent before the device has even been told anything.
        """
        self._write_listeners.append(listener)

        def remove() -> None:
            self._write_listeners.remove(listener)

        return remove

    async def _flush_soon(self) -> None:
        """Write what is queued, then anything that arrived while writing.

        Leading edge, not trailing: the first change goes out immediately and
        only what piles up behind it is coalesced. A trailing debounce added its
        whole delay to every single click — the common case by far — to save a
        connection in the rare one. Coalescing still happens, because the
        connection takes seconds and everything queued behind it is merged into
        one follow-up write.
        """
        # Scoped to this burst, never beyond it. It exists to drop the trailing
        # write of a burst that ended where it started, and it is *not*
        # evidence of what the device did -- only of what was sent. Keeping it
        # across flushes turned an unconfirmed write into a permanently
        # unrepeatable one: the value stayed queued as "already written" while
        # the device sat in the other state.
        last_written: bytes | None = None

        while True:
            async with self._pending_lock:
                changes = dict(self._pending)
                self._pending.clear()
            if not changes:
                return

            error: Exception | None = None
            try:
                payload = self._compose(changes)
                if self._is_redundant(payload, last_written):
                    _LOGGER.debug(
                        "%s: skipping %s, which would change nothing",
                        self.address,
                        payload.hex(),
                    )
                else:
                    await self._write_now(payload)
                    last_written = payload
            except Exception as caught:  # broad on purpose: reported to listeners
                error = caught
                last_written = None
                _LOGGER.warning("%s: write failed: %s", self.address, caught)

            for listener in list(self._write_listeners):
                listener(set(changes), error)

            # Anything queued during the write is merged into one more pass.
            async with self._pending_lock:
                if not self._pending:
                    return
            await asyncio.sleep(WRITE_DEBOUNCE)

    def _compose(self, changes: dict[int, bytes]) -> bytes:
        """Build the write-all payload from the *current* advertisement (§4.2).

        Never from a layout cached at setup: a device reflashed with a different
        object order must not receive a write against the old one.
        """
        if self.declaration is None:
            raise WriteFailed(
                f"{self.address}: no declaration seen yet, refusing to write"
            )
        return compose_write(self.declaration, changes)

    def _is_redundant(self, payload: bytes, last_written: bytes | None) -> bool:
        """Whether sending this payload would achieve nothing.

        Two ways it can. The device already advertises every value in it —
        which is evidence, since advertising is the source of truth (§6). Or it
        repeats the write that just went out *in this same burst*, which is
        what a run of toggles ending where it started produces.

        `last_written` deliberately does not survive the burst. It says what was
        sent, not what the device did, and a write can be delivered and do
        nothing (D-012). Treating it as state made an unconfirmed write
        unrepeatable: the receiver kept refusing to resend the value the device
        had never taken.

        Never true when a write-only object is involved. Those have no
        advertised value to compare against, and the whole point of a trigger is
        that sending it again does something.
        """
        assert self.declaration is not None
        if any(obj.write_only for obj in self.declaration.objects):
            return False
        if payload == last_written:
            return True
        return payload == compose_write(self.declaration, {})

    async def _write_now(self, payload: bytes) -> None:
        """Deliver one composed write-all payload over a short connection.

        Sealing happens here rather than in `_compose`, so that everything
        upstream -- the redundancy check especially -- still compares plaintext.
        Two identical commands seal to different bytes, because their counters
        differ, and a sealed comparison would never find a repeat.
        """
        if self.bindkey is not None:
            if self.advertises_encrypted is False and not ALLOW_PLAINTEXT_DOWNGRADE:
                # A key was configured but the device is advertising in clear.
                # Sealing anyway produces bytes it cannot parse, and section 4.2
                # makes it reject the whole write without a word -- the control
                # simply stops working, which is the worst symptom there is.
                #
                # Downgrading to plaintext instead would fix that, and is
                # refused deliberately: an attacker who can make a keyed device
                # appear to advertise in clear would then be handed unsealed
                # writes. Refusing loudly is the only option that is both
                # visible and safe; removing the bindkey is the user's call.
                raise WriteFailed(
                    f"{self.address}: a bindkey is configured but the device is "
                    "advertising in clear. Refusing to send an unencrypted "
                    "write. Either reflash the device with encryption enabled, "
                    "or remove the bindkey by deleting and re-adding this device"
                )
            payload = seal_write(
                payload, self.bindkey, self.address, self.next_write_counter()
            )

        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise WriteFailed(f"{self.address}: not reachable by any adapter or proxy")

        started = time.monotonic()
        async with self._semaphore:
            client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=device,
                name=self.address,
                max_attempts=2,
            )
            try:
                await self._check_mtu(client, payload)
                await self._write_characteristic(client, payload)
            finally:
                await client.disconnect()

        _LOGGER.debug(
            "%s: wrote %s in %.0f ms",
            self.address,
            payload.hex(),
            (time.monotonic() - started) * 1000,
        )

    async def _write_characteristic(self, client: Any, payload: bytes) -> None:
        """Write, and retry once against a freshly discovered GATT table.

        Every host caches a device's GATT table, and an Espruino device rebuilds
        its table each time code is uploaded to it — so the cache goes stale in
        normal use, not as a rare fault. A write resolved through a stale cache
        lands on a handle that no longer means what it did, and the transport
        reports success: nothing fails, the device simply does not act. That is
        the worst failure this integration can have, because the receiver then
        reverts the entity and blames the device.

        So a write that leaves no trace gets exactly one more chance, against a
        rediscovered table. The device rejecting a *delivered* write is the
        other explanation for the same symptom, and the retry is cheap either
        way.
        """
        characteristic = client.services.get_characteristic(WRITE_CHARACTERISTIC_UUID)
        if characteristic is None:
            # A table can only be rediscovered by reconnecting, so drop it and
            # let the next write pick up a fresh one rather than reconnecting
            # inside a write that has already spent its connection budget.
            await client.clear_cache()
            raise WriteFailed(
                f"{self.address}: no write characteristic in the cached GATT "
                "table; it has been dropped, so the next write will rediscover"
            )

        await client.write_gatt_char(characteristic, payload, response=True)

    async def async_clear_service_cache(self) -> None:
        """Forget the cached GATT table for this device.

        Called when a write was delivered and the device did not act on it,
        which is what a stale cache looks like from the outside.
        """
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            return
        async with self._semaphore:
            client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=device,
                name=self.address,
                max_attempts=1,
            )
            try:
                await client.clear_cache()
            finally:
                await client.disconnect()
        _LOGGER.debug("%s: cleared the cached GATT table", self.address)

    async def _check_mtu(self, client: Any, payload: bytes) -> None:
        """Warn if the MTU cannot carry this payload (§4.4).

        Only asked when the payload needs more than a default MTU allows, since
        most writes are a couple of bytes and every backend answers differently.

        Measured on hardware: a write larger than `MTU - 3` is refused outright
        rather than split into a long write, so the MTU is a hard ceiling on a
        write-all payload, not a performance hint (decisions.md D-017). Worth
        knowing accurately, hence `_acquire_mtu()` — BlueZ reports the 23-byte
        default until asked, which would have this warning firing on a link that
        can in fact carry the payload.
        """
        if len(payload) <= DEFAULT_MTU_PAYLOAD:
            return

        acquire = getattr(client, "_acquire_mtu", None)
        if acquire is not None and getattr(client, "_mtu_size", None) is None:
            try:
                await acquire()
            except Exception as error:  # best effort; the warning is advisory
                _LOGGER.debug("%s: could not read the MTU: %s", self.address, error)

        mtu = getattr(client, "mtu_size", None)
        if mtu is not None and mtu < MIN_MTU:
            _LOGGER.debug(
                "%s: MTU is %s and this write is %d bytes; the protocol asks "
                "for %s, so a long write may not fit",
                self.address,
                mtu,
                len(payload),
                MIN_MTU,
            )

    @property
    def service_uuid(self) -> str:
        return SERVICE_UUID

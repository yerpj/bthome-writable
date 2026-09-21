"""Per-device state and the write and read paths (PROTOCOL.md version 2).

One coordinator per configured device. It watches the device's advertising for
its declaration and settings revision, writes one object per entry over a short
GATT connection, and reads entries back when the revision says their values
changed on the device.
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
    BTHOME_SERVICE_UUID,
    COUNTER_STRIDE,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MTU_PAYLOAD,
    EVENT_WRITE,
    MIN_MTU,
    READ_RETRY,
    RESYNC_JUMP,
    SERVICE_UUID,
)
from .protocol import (
    Declaration,
    ProtocolError,
    WritableEntry,
    decode_object,
    decrypt_advertising,
    encode_object,
    is_encrypted,
    open_read,
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


def _settle(waiter: asyncio.Future[None], error: Exception | None) -> None:
    """Finish one caller's wait, unless it has already been finished.

    A future can be resolved twice -- a write that fails after its value was
    superseded, a flush that ends while an item is in flight -- and the second
    attempt would raise `InvalidStateError` from somewhere unrelated.
    """
    if waiter.done():
        return
    if error is None:
        waiter.set_result(None)
    else:
        waiter.set_exception(error)


class WriteFailed(Exception):
    """The write did not reach the device."""


type WriteListener = Callable[[set[int], Exception | None], None]


class BTHomeWritableCoordinator:
    """Tracks one device's declaration, writes to it and reads it back."""

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
        self.name = name or address
        self.bindkey = bindkey
        """The device's BTHome key, or None for a plain device (§5)."""

        self.advertises_encrypted: bool | None = None
        """Whether the last advertisement was sealed, or None before the first.

        A bindkey says what the *receiver* was told; this says what the device
        is actually doing. When they disagree the write is refused rather than
        downgraded -- see `_write_now` and D-042."""

        self._counter = write_counter
        self._counter_mark = write_counter
        self._on_counter = on_counter

        self.declaration: Declaration | None = None
        self.available = False
        self.advertisements = 0

        self._values: dict[int, bytes] = {}
        """Last known value per entry: what was written, or what was read.
        Never what was advertised -- version 2 advertises no writable values."""

        self._revision_advertised: int | None = None
        self._revision_read: int | None = None
        """The revision whose values are in `_values`. Moves only when a read
        succeeds: an Espruino device serves one central at a time, so a read
        attempted while something else holds the link fails, and marking the
        revision seen at that point would leave the state stale indefinitely."""
        self._read_failed_at: float | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._read_again = False

        self._listeners: list[Callable[[], None]] = []
        self._write_listeners: list[WriteListener] = []
        self._pending: list[tuple[int, bytes, bool, float, asyncio.Future[None]]] = []
        self._pending_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        self._semaphore = connection_semaphore(max_connections)

    # --- Advertising side ---------------------------------------------------

    @callback
    def async_handle_advertisement(
        self, service_info: BluetoothServiceInfoBleak
    ) -> None:
        """Absorb one advertisement: the declaration and the settings revision."""
        payload = service_info.service_data.get(BTHOME_SERVICE_UUID)
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

        self.available = True
        self.advertisements += 1

        if declaration is None:
            # A rotating device's sensor-only packet (§2.2): not evidence that
            # nothing is writable, so the last declaration stands.
            self._notify()
            return

        if (
            self.declaration is not None
            and declaration.layout != self.declaration.layout
        ):
            # A different layout almost always means new firmware, which means a
            # rebuilt GATT table -- and the host's cached copy is now wrong in the
            # silent way of D-012. Drop it before the next write finds out, and
            # forget values that belonged to the old entries.
            _LOGGER.debug(
                "%s: the declared layout changed; dropping the cached GATT table",
                self.address,
            )
            self._values.clear()
            self.hass.async_create_task(self.async_clear_service_cache())

        self.declaration = declaration
        self._notice_revision(declaration.settings_revision)
        self._notify()

    def _notice_revision(self, revision: int | None) -> None:
        """Read the device again when its settings revision moves (§3.2).

        Also on first sight: after a Home Assistant restart the entity would
        otherwise show nothing until the next write.
        """
        if revision is None:
            return
        self._revision_advertised = revision
        if revision == self._revision_read:
            return
        if (
            self._read_failed_at is not None
            and time.monotonic() - self._read_failed_at < READ_RETRY
        ):
            # Every advertisement would otherwise be a connection attempt on a
            # device that just refused one.
            return
        self.async_request_read()

    @callback
    def async_request_read(self) -> None:
        """Read every readable entry, once, soon. Coalesces overlapping asks."""
        if self._read_task is not None and not self._read_task.done():
            self._read_again = True
            return
        self._read_task = self.hass.async_create_task(self._read_loop())

    async def _read_loop(self) -> None:
        while True:
            self._read_again = False
            target = self._revision_advertised
            try:
                done = await self.async_read_all()
            except Exception as error:  # best effort: state stays as last known
                _LOGGER.debug("%s: reading state failed: %s", self.address, error)
                done = False
            if done:
                self._revision_read = target
                self._read_failed_at = None
            else:
                # Retried on a later advertisement, once READ_RETRY has passed.
                self._read_failed_at = time.monotonic()
                return
            if not self._read_again:
                return

    def _plaintext(self, payload: bytes) -> bytes | None:
        """The object stream, decrypting first if the device is encrypted.

        The device-information byte is never part of it. For an encrypted device
        it is also the only thing readable without the key, which is why the
        config flow has to ask for a bindkey before it can see a declaration.
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

    @property
    def reports_state(self) -> bool:
        """Whether the device advertises a settings revision, and so can be read
        (§3.2). Otherwise its entries are assumed state (§3.1)."""
        return (
            self.declaration is not None
            and self.declaration.settings_revision is not None
        )

    def value_of(self, entry: int) -> bytes | None:
        """The last known value of an entry: written, or read. None if neither."""
        return self._values.get(entry)

    def entry(self, number: int) -> WritableEntry | None:
        if self.declaration is None or not 1 <= number <= len(self.declaration.entries):
            return None
        return self.declaration.entries[number - 1]

    # --- Counters (§5.3) ----------------------------------------------------

    def next_write_counter(self) -> int:
        """The counter for the next write, persisted coarsely.

        A receiver MUST persist this across restarts: a restarted Home Assistant
        resuming from zero would send counters the device has already accepted,
        and every write would be refused as a replay. Saved as a high-water mark
        ahead of the counter and resumed *from the mark*, so the values between
        the last save and a crash are given up rather than reused.
        """
        self._counter += 1
        if self._counter >= self._counter_mark:
            self._counter_mark = self._counter + COUNTER_STRIDE
            if self._on_counter is not None:
                self._on_counter(self._counter_mark)
        return self._counter

    def resynchronise(self) -> int:
        """Jump the counter well forward, for a device that has seen higher.

        §5.3 asks a receiver to offer this. A device restored from a backup, or
        a Home Assistant whose stored counter was lost, sends counters the device
        has already accepted. Jumping is safe because a device MUST accept a
        forward jump.
        """
        self._counter += RESYNC_JUMP
        self._counter_mark = self._counter + COUNTER_STRIDE
        if self._on_counter is not None:
            self._on_counter(self._counter_mark)
        _LOGGER.info(
            "%s: write counter resynchronised to %d", self.address, self._counter
        )
        return self._counter

    # --- Write side ---------------------------------------------------------

    async def async_write(
        self, entry: int, value: bytes, *, coalesce: bool = True
    ) -> None:
        """Queue a value for an entry and wait for it to reach the device.

        Returns when the device has acknowledged this write, and raises what
        went wrong when it has not. An action that cannot fail is an action the
        user cannot trust, and Home Assistant's own rule for one is to raise so
        that the failure reaches the interface (`action-exceptions`, D-064).
        Waiting costs the caller the connection time, which is what every other
        integration on a radio does.

        Coalescing is per entry, last value wins, and happens behind the write in
        flight rather than in front of it: dragging a slider produces one write
        for where it started and one for where it stopped. It is what keeps a
        source faster than the link from growing the queue without bound, which
        is why it stays while the batching did not (D-059). A command dropped
        that way did not fail -- a newer one for the same entry replaced it --
        so its caller is told it succeeded. Events are queued with
        `coalesce=False`: two presses are two presses.
        """
        waiter: asyncio.Future[None] = self.hass.loop.create_future()
        async with self._pending_lock:
            if coalesce:
                keep = []
                for item in self._pending:
                    if item[0] == entry and item[2]:
                        _settle(item[4], None)
                    else:
                        keep.append(item)
                self._pending = keep
            # Stamped here, where the command arrives, so that what is reported
            # afterwards measures the whole journey rather than the part that
            # happens to be easy to see.
            self._pending.append((entry, value, coalesce, time.monotonic(), waiter))
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = self.hass.async_create_task(self._flush_soon())
        await waiter

    @callback
    def async_add_write_listener(self, listener: WriteListener) -> Callable[[], None]:
        """Be told which entries a write reached, or failed to."""
        self._write_listeners.append(listener)

        def remove() -> None:
            self._write_listeners.remove(listener)

        return remove

    def _report(self, entries: set[int], error: Exception | None) -> None:
        if not entries:
            return
        for listener in list(self._write_listeners):
            listener(entries, error)

    async def _flush_soon(self) -> None:
        """Drain the queue, one command per connection.

        Connect, write one object, wait for the device to acknowledge it, close.
        Nothing is bundled and nothing waits for a companion: a command that
        cannot be delivered fails on its own and takes nothing else with it, and
        the link is held for exactly as long as one write needs it (D-059).

        Leading edge, not trailing: the first change goes out immediately, and
        only what piles up behind it is coalesced (D-020).
        """
        try:
            while True:
                async with self._pending_lock:
                    if not self._pending:
                        return
                    entry, value, coalesce, queued_at, waiter = self._pending.pop(0)

                try:
                    await self._write_now(entry, value, coalesce, queued_at)
                except Exception as caught:  # broad on purpose: reported to callers
                    _LOGGER.warning("%s: write failed: %s", self.address, caught)
                    self._report({entry}, caught)
                    _settle(waiter, caught)
                else:
                    self._report({entry}, None)
                    _settle(waiter, None)
        finally:
            # Whatever ends this loop -- an unload, a cancellation, a fault of
            # its own -- must not leave a caller awaiting a write that will now
            # never happen.
            async with self._pending_lock:
                stranded, self._pending = self._pending, []
            for item in stranded:
                _settle(
                    item[4],
                    WriteFailed(f"{self.address}: the write queue stopped"),
                )

    async def _write_now(
        self,
        number: int,
        value: bytes,
        coalesce: bool = True,
        queued_at: float | None = None,
    ) -> None:
        """Deliver one command: connect, write with response, close.

        The whole of the receiver's side of §4.2, and deliberately the whole of
        it: one object, one connection, no bundling of commands that happen to
        be queued together. The link is opened when there is something to say
        and dropped as soon as the device has acknowledged it, which is what a
        device that serves one central at a time needs from us (D-003, D-059).
        """
        if (
            self.bindkey is not None
            and self.advertises_encrypted is False
            and not ALLOW_PLAINTEXT_DOWNGRADE
        ):
            # A key was configured but the device is advertising in clear.
            # Sealing anyway produces bytes it cannot parse; downgrading would
            # hand unsealed writes to anyone able to make a keyed device look
            # unencrypted. Refusing loudly is the only option that is both
            # visible and safe (D-042).
            raise WriteFailed(
                f"{self.address}: a bindkey is configured but the device is "
                "advertising in clear. Refusing to send an unencrypted "
                "write. Either reflash the device with encryption enabled, "
                "or remove the bindkey by deleting and re-adding this device"
            )

        if self.declaration is None:
            raise WriteFailed(
                f"{self.address}: no declaration seen yet, refusing to write"
            )

        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise WriteFailed(f"{self.address}: not reachable by any adapter or proxy")

        entry = self.entry(number)
        if entry is None:
            raise WriteFailed(
                f"{self.address}: entry {number} is not in the declaration"
            )

        payload = encode_object(entry, value)
        if self.bindkey is not None:
            payload = seal_write(
                payload, self.bindkey, self.address, self.next_write_counter()
            )

        started = time.monotonic()
        async with self._semaphore:
            client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=device,
                name=self.address,
                max_attempts=2,
            )
            connected = time.monotonic()
            try:
                await self._check_mtu(client, payload)
                write_started = time.monotonic()
                await self._write_characteristic(client, entry, payload)
                acknowledged = time.monotonic()
            finally:
                await client.disconnect()

        if coalesce:
            # Events leave no state behind; everything else does.
            self._values[number] = value
        self._report_timing(
            number,
            queued_at=started if queued_at is None else queued_at,
            connect_started=started,
            connected=connected,
            write_started=write_started,
            acknowledged=acknowledged,
        )

    def _report_timing(
        self,
        entry: int,
        *,
        queued_at: float,
        connect_started: float,
        connected: float,
        write_started: float,
        acknowledged: float,
    ) -> None:
        """Say how long a write took, split where the time actually goes.

        Fired as an event rather than logged, so that anyone can watch it: the
        interesting question -- how much of a command is spent waiting to catch
        the device advertising -- is answered by `connect_ms`, and the answer
        depends on the device's advertising interval rather than on anything
        Home Assistant does (`docs/measurements.md`).
        """
        self.hass.bus.async_fire(
            EVENT_WRITE,
            {
                "address": self.address,
                "entry": entry,
                "queued_ms": round((connect_started - queued_at) * 1000, 1),
                "connect_ms": round((connected - connect_started) * 1000, 1),
                "write_ms": round((acknowledged - write_started) * 1000, 1),
                "total_ms": round((acknowledged - queued_at) * 1000, 1),
            },
        )

    async def _write_characteristic(
        self, client: Any, entry: WritableEntry, payload: bytes
    ) -> None:
        """Write with response to the entry's characteristic (§4.2).

        Every host caches a device's GATT table, and an Espruino device rebuilds
        its table each time code is uploaded to it, so the cache goes stale in
        normal use. A characteristic that is not in the table is the visible form
        of that: drop the table so the next attempt rediscovers it.
        """
        characteristic = client.services.get_characteristic(entry.uuid)
        if characteristic is None:
            await client.clear_cache()
            raise WriteFailed(
                f"{self.address}: characteristic {entry.uuid} not in the GATT "
                "table; the cached table has been dropped, so the next write will "
                "rediscover it"
            )
        await client.write_gatt_char(characteristic, payload, response=True)

    # --- Read side (§3.2, §4.3) --------------------------------------------

    async def async_read_all(self) -> bool:
        """Read every offered, readable entry over one connection.

        Returns whether the device was read; raises if the connection fails.
        """
        if self.declaration is None:
            return False
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            return False

        changed = False
        async with self._semaphore:
            client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=device,
                name=self.address,
                max_attempts=2,
            )
            try:
                for entry in self.declaration.offered:
                    characteristic = client.services.get_characteristic(entry.uuid)
                    if (
                        characteristic is None
                        or "read" not in characteristic.properties
                    ):
                        continue
                    raw = bytes(await client.read_gatt_char(characteristic))
                    value = self._open_read(entry, raw)
                    if value is not None and self._values.get(entry.entry) != value:
                        self._values[entry.entry] = value
                        changed = True
            finally:
                await client.disconnect()

        if changed:
            self._notify()
        return True

    def _open_read(self, entry: WritableEntry, raw: bytes) -> bytes | None:
        """A read's value, or None -- with the reason logged -- if unusable."""
        plaintext: bytes | None = raw
        if self.bindkey is not None:
            try:
                plaintext = open_read(raw, self.bindkey, self.address)
            except ProtocolError as error:
                _LOGGER.warning("%s: entry %d: %s", self.address, entry.entry, error)
                return None
            if plaintext is None:
                _LOGGER.warning(
                    "%s: entry %d: a read did not authenticate",
                    self.address,
                    entry.entry,
                )
                return None
        try:
            return decode_object(entry, plaintext)
        except ProtocolError as error:
            _LOGGER.warning("%s: %s", self.address, error)
            return None

    # --- Housekeeping -------------------------------------------------------

    async def async_clear_service_cache(self) -> None:
        """Forget the cached GATT table for this device."""
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
        """Note when the MTU cannot carry this write (§4.4).

        A write larger than `MTU - 3` is refused outright rather than split into
        a long write, so the MTU is a hard ceiling, not a performance hint
        (decisions.md D-017). BlueZ reports the 23-byte default until asked,
        hence `_acquire_mtu()`.
        """
        if len(payload) <= DEFAULT_MTU_PAYLOAD:
            return

        acquire = getattr(client, "_acquire_mtu", None)
        if acquire is not None and getattr(client, "_mtu_size", None) is None:
            try:
                await acquire()
            except Exception as error:  # best effort; the note is advisory
                _LOGGER.debug("%s: could not read the MTU: %s", self.address, error)

        mtu = getattr(client, "mtu_size", None)
        if mtu is not None and mtu < MIN_MTU:
            _LOGGER.debug(
                "%s: MTU is %s and this write is %d bytes; the protocol asks "
                "for %s, so it may not fit",
                self.address,
                mtu,
                len(payload),
                MIN_MTU,
            )

    @property
    def service_uuid(self) -> str:
        return SERVICE_UUID

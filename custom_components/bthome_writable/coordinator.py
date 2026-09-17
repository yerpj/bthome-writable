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
    MIN_MTU,
    RESYNC_JUMP,
    SERVICE_UUID,
    WRITE_DEBOUNCE,
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

        self._revision_seen: int | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._read_again = False

        self._listeners: list[Callable[[], None]] = []
        self._write_listeners: list[WriteListener] = []
        self._pending: list[tuple[int, bytes, bool]] = []
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
        if revision is None or revision == self._revision_seen:
            return
        self._revision_seen = revision
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
            try:
                await self.async_read_all()
            except Exception as error:  # best effort: state stays as last known
                _LOGGER.debug("%s: reading state failed: %s", self.address, error)
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
        """Queue a value for an entry; the flush starts at once if none runs.

        Coalescing is per entry, last value wins, and happens behind the write in
        flight rather than in front of it: dragging a slider produces one write
        for where it started and one for where it stopped. Events are queued with
        `coalesce=False`: two presses are two presses.
        """
        async with self._pending_lock:
            if coalesce:
                self._pending = [
                    item for item in self._pending if not (item[0] == entry and item[2])
                ]
            self._pending.append((entry, value, coalesce))
            if self._flush_task is None or self._flush_task.done():
                self._flush_task = self.hass.async_create_task(self._flush_soon())

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
        """Write what is queued in one connection, then whatever arrived meanwhile.

        Leading edge, not trailing: the first change goes out immediately and
        only what piles up behind it is coalesced (D-020).
        """
        while True:
            async with self._pending_lock:
                batch, self._pending = self._pending, []
            if not batch:
                return

            written: list[tuple[int, bytes, bool]] = []
            try:
                await self._write_now(batch, written)
            except Exception as caught:  # broad on purpose: reported to listeners
                _LOGGER.warning("%s: write failed: %s", self.address, caught)
                done = {item[0] for item in written}
                self._report(done, None)
                self._report({item[0] for item in batch} - done, caught)
            else:
                self._report({item[0] for item in batch}, None)

            async with self._pending_lock:
                if not self._pending:
                    return
            await asyncio.sleep(WRITE_DEBOUNCE)

    async def _write_now(
        self,
        batch: list[tuple[int, bytes, bool]],
        written: list[tuple[int, bytes, bool]],
    ) -> None:
        """Deliver a batch over one connection, one write with response each.

        `written` collects what went through, so a failure part-way reports the
        entries that did arrive as delivered.
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

        started = time.monotonic()
        async with self._semaphore:
            client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=device,
                name=self.address,
                max_attempts=2,
            )
            try:
                for number, value, coalesce in batch:
                    entry = self.entry(number)
                    if entry is None:
                        raise WriteFailed(
                            f"{self.address}: entry {number} is not in the declaration"
                        )
                    payload = encode_object(entry, value)
                    if self.bindkey is not None:
                        payload = seal_write(
                            payload,
                            self.bindkey,
                            self.address,
                            self.next_write_counter(),
                        )
                    await self._check_mtu(client, payload)
                    await self._write_characteristic(client, entry, payload)
                    if coalesce:
                        # Events leave no state behind; everything else does.
                        self._values[number] = value
                    written.append((number, value, coalesce))
            finally:
                await client.disconnect()

        _LOGGER.debug(
            "%s: wrote %d entr%s in %.0f ms",
            self.address,
            len(batch),
            "y" if len(batch) == 1 else "ies",
            (time.monotonic() - started) * 1000,
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

    async def async_read_all(self) -> None:
        """Read every offered, readable entry over one connection."""
        if self.declaration is None:
            return
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            return

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

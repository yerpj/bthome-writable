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
import secrets
import time
from typing import Any

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from habluetooth import BluetoothServiceInfoBleak
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback

from .const import (
    ALLOW_COUNTER_SYNC,
    ALLOW_PLAINTEXT_DOWNGRADE,
    AUTHENTICATION_FAILURES_BEFORE_REAUTH,
    BTHOME_SERVICE_UUID,
    CHALLENGE_LENGTH,
    COMFORTABLE_MTU,
    COUNTER_RESTART_CEILING,
    COUNTER_STRIDE,
    COUNTER_UUID,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MTU_PAYLOAD,
    EVENT_WRITE,
    READ_RETRY,
    RESYNC_JUMP,
    SERVICE_UUID,
)
from .protocol import (
    Declaration,
    ProtocolError,
    WritableEntry,
    advertising_counter,
    decode_object,
    decrypt_advertising,
    encode_object,
    is_encrypted,
    objects_at,
    open_counter_report,
    open_read,
    parse_declaration,
    seal_write,
    trigger_based,
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
        declaration: Declaration | None = None,
        on_declaration: Callable[[Declaration], None] | None = None,
        sleepy_device: bool = False,
        on_sleepy_device: Callable[[bool], None] | None = None,
        on_authentication_failure: Callable[[], None] | None = None,
    ) -> None:
        self.hass = hass
        self.address = address
        self.name = name or address
        self.bindkey = bindkey
        """The device's BTHome key, or None for a plain device (§5)."""

        self.bindkey_verified: bool | None = None
        """Whether a bindkey has ever opened an advertisement from this device.

        Core `bthome` keeps the same flag under the same name, and for the same
        two purposes: it gates the replay check -- there is no counter to
        compare against until one packet has been read -- and it is what the
        reauthentication flow proves (D-082)."""

        self._authentication_failures = 0
        self._on_authentication_failure = on_authentication_failure

        self.last_service_info: BluetoothServiceInfoBleak | None = None
        """The most recent advertisement, kept the way core `bthome` keeps it.

        A reauthentication flow needs an advertisement to check a key against,
        and the user may answer it long after the device went quiet."""

        self.encryption_counter = 0
        """The highest advertising counter accepted, for the replay check."""

        self.sleepy_device = sleepy_device
        self._on_sleepy_device = on_sleepy_device

        self.advertises_encrypted: bool | None = None
        """Whether the last advertisement was sealed, or None before the first.

        A bindkey says what the *receiver* was told; this says what the device
        is actually doing. When they disagree the write is refused rather than
        downgraded -- see `_write_now` and D-042."""

        self._counter = write_counter
        self._counter_mark = write_counter
        self._on_counter = on_counter

        self.declaration: Declaration | None = declaration
        self._on_declaration = on_declaration
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
        revision seen at that point would leave the state stale indefinitely.

        "Succeeds" means every entry, not merely the connection -- the looser
        reading is what made this stale anyway (D-083)."""
        self._read_failed_at: float | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._reading = False

        self._resync_counter = False
        """Whether to ask the device for its write counter before writing again.

        Armed when the settings revision moves, because a device that restarted
        resumes its write counter up to a stride ahead of us and nothing on the
        air says so (D-078 fault 1, D-092). Spent on the next write rather than
        at once: a resynchronisation is a connection, and a device whose
        revision moves is not necessarily a device anyone is about to command."""
        self._offers_counter_report: bool | None = None
        """None until we have looked. False stops the arming above, so a device
        without the characteristic is not reconnected to on every revision."""

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

        self.last_service_info = service_info

        self._notice_sleepy(trigger_based(payload))

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

        remembered = self.declaration
        self.declaration = declaration
        if self._on_declaration is not None and (
            remembered is None
            or remembered.layout != declaration.layout
            or remembered.settings_revision != declaration.settings_revision
        ):
            self._on_declaration(declaration)
        self._notice_revision(declaration.settings_revision)
        self._notify()

    def _notice_revision(self, revision: int | None) -> None:
        """Read the device again when its settings revision moves (§3.2).

        Also on first sight: after a Home Assistant restart the entity would
        otherwise show nothing until the next write.
        """
        if revision is None:
            return
        previous = self._revision_advertised
        self._revision_advertised = revision
        # A revision that moves while we are watching is what a restart looks
        # like: `setup()` picks a random one precisely so that a device whose
        # values went back to their defaults is re-read. A restart also resumes
        # the write counter ahead of ours, in silence, so take the same signal
        # for both (D-092).
        #
        # `changed()` moves it too, and that arms a resynchronisation nothing
        # needed. It costs one connection before the next command, and the
        # adoption refuses to move the counter backwards (D-083 item 11), so a
        # needless one changes nothing.
        if (
            previous is not None
            and revision != previous
            and ALLOW_COUNTER_SYNC
            and self.bindkey is not None
            and self._offers_counter_report is not False
        ):
            self._resync_counter = True
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
        """Read every readable entry, once, soon. Coalesces overlapping asks.

        The guard is a plain flag set *before* the task is created, not the
        task's own state. `async_create_task` starts the coroutine eagerly, so
        `self._read_task` still refers to the previous, finished task while the
        new one is already running -- and an advertisement handled in that
        window saw no read in progress and started a second (D-087).
        """
        if self._reading:
            return
        self._reading = True
        self._read_task = self.hass.async_create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Read until the revision we have read is the one being advertised.

        The loop exists for a device whose state moves *again* while we are
        reading it -- a knob turned twice. It used to continue on a flag set by
        any advertisement arriving during the read, which is not the same thing
        at all: a device advertises every second or so, and a read takes a
        connection, so an ordinary read was followed by a second and often a
        third, each one a connection to a device that serves one central at a
        time.

        Reported by a user at their own site, on hardware this project has
        never touched, and invisible here because the test pushed its
        advertisement *after* the read had settled (D-087).
        """
        try:
            while True:
                target = self._revision_advertised
                try:
                    done = await self.async_read_all()
                except Exception as error:  # best effort: state stays as known
                    _LOGGER.debug("%s: reading state failed: %s", self.address, error)
                    done = False
                if not done:
                    # Retried on a later advertisement, after READ_RETRY.
                    self._read_failed_at = time.monotonic()
                    return
                self._revision_read = target
                self._read_failed_at = None
                if self._revision_advertised == self._revision_read:
                    return
        finally:
            self._reading = False

    def _plaintext(self, payload: bytes) -> bytes | None:
        """The object stream, decrypting first if the device is encrypted.

        The device-information byte is never part of it. For an encrypted device
        it is also the only thing readable without the key, which is why the
        config flow has to ask for a bindkey before it can see a declaration.
        """
        self.advertises_encrypted = is_encrypted(payload)
        if not self.advertises_encrypted:
            # Past the device-information byte, and past the MAC when the device
            # put one there: the flags say how long the header is.
            return payload[objects_at(payload) :]

        if self.bindkey is None:
            _LOGGER.debug(
                "%s: advertising is encrypted and no bindkey is configured",
                self.address,
            )
            # A device that is sealed while we hold no key is the case core
            # `bthome` raises a reauthentication flow for, and so do we: the
            # alternative is an integration that silently shows nothing.
            self._authentication_failed()
            return None

        if not self._counter_increased(payload):
            return None

        objects = decrypt_advertising(payload, self.bindkey, self.address)
        if objects is None:
            _LOGGER.warning(
                "%s: an advertisement did not authenticate; the bindkey may be "
                "wrong, or another device may be using this address",
                self.address,
            )
            self._authentication_failed()
            return None

        self.bindkey_verified = True
        self._authentication_failures = 0
        counter = advertising_counter(payload)
        if counter is not None:
            self.encryption_counter = counter
        return objects

    def _counter_increased(self, payload: bytes) -> bool:
        """`bthome-ble`'s replay check, thresholds included.

        A sealed advertisement carries its counter in the clear, so a replay can
        be dropped before an AES is spent on it. The rule is copied rather than
        invented, because a packet this integration acts on should be one core
        `bthome` would have shown the user:

        * only once a key has opened something, since before that there is
          nothing to compare against;
        * and only above `COUNTER_RESTART_CEILING`, because a counter that
          wrapped or a device whose battery was changed resumes near zero and
          refusing those would make it unreadable until it caught up;
        * and only when it *decreased* -- an equal counter is a duplicate, not
          a replay, and the only device that can produce one is the one being
          heard twice (D-092).

        See `bthome_ble.parser._check_encryption_counter`.
        """
        counter = advertising_counter(payload)
        if counter is None or self.bindkey_verified is not True:
            return True
        # Strictly below, not "not above": the library refuses a *decreasing*
        # counter, and an equal one is the same packet arriving twice. Six
        # ESPHome proxies deliver one advertisement six times, and this used to
        # call each repeat compromised -- sixteen warnings in a day on a device
        # doing nothing wrong, and a receiver stricter than the one whose
        # behaviour this project's argument rests on (D-092, @enaon).
        if counter >= self.encryption_counter or counter < COUNTER_RESTART_CEILING:
            return True
        _LOGGER.warning(
            "%s: the new encryption counter (%i) is smaller than the previous "
            "value (%i). The data might be compromised. BLE advertisement will "
            "be skipped",
            self.address,
            counter,
            self.encryption_counter,
        )
        return False

    def _authentication_failed(self) -> None:
        """Count a packet we could not open, and ask for the key once it is not
        a one-off.

        Core `bthome` asks after two: *"we only ask for reautentification after
        the decryption has failed twice."* One failure is a stray packet -- a
        neighbour on this address, a corrupted frame -- and a reauthentication
        flow raised for one of those teaches the user to dismiss them.
        """
        self.bindkey_verified = False
        self._authentication_failures += 1
        if (
            self._authentication_failures >= AUTHENTICATION_FAILURES_BEFORE_REAUTH
            and self._on_authentication_failure is not None
        ):
            self._on_authentication_failure()

    def _notice_sleepy(self, sleepy: bool) -> None:
        """Remember a trigger-based device, the way core `bthome` does.

        Persisted rather than merely noted, so the entities of a device that
        speaks once an hour are available immediately after a restart instead of
        an hour later.
        """
        if sleepy == self.sleepy_device:
            return
        self.sleepy_device = sleepy
        if self._on_sleepy_device is not None:
            self._on_sleepy_device(sleepy)

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

    def still_declared(self, number: int, object_id: int) -> bool:
        """Whether entry `number` is still the object the caller thinks it is.

        New firmware can turn entry 1 from a light into a text, and the entities
        built for the old layout are not removed -- so a control from before the
        change would otherwise take its value, hand it to the *new* entry's
        encoder, and put a malformed object on the wire. Measured: a stale
        switch produced `53 01`, a text object claiming one character and
        carrying none, and §4.2 acknowledged it before the device refused it, so
        Home Assistant reported success (D-083).

        This is the device's own desync guard, on the receiving side.
        """
        declared = self.entry(number)
        return declared is not None and declared.object_id == object_id

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
                "or reconfigure this device and clear the bindkey"
            )

        if self.bindkey is None and self.advertises_encrypted:
            # The mirror of the case above, and it was the silent one: with no
            # key the write goes out in clear, the device discards the whole
            # payload, and §4.2 has already acknowledged it. Home Assistant
            # reports success and the actuator does not move -- which is how a
            # measurement campaign that reflashed a device unencrypted, and the
            # re-add that followed, left a bench where every sealed write
            # vanished (D-079).
            raise WriteFailed(
                f"{self.address}: the device is advertising encrypted but no "
                "bindkey is configured here, so this write would go out in "
                "clear and be discarded without a word. Reconfigure this "
                "device and give it its bindkey"
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

        if self._resync_counter:
            # Before the counter is taken, not after: `next_write_counter()`
            # hands out a value and the adoption replaces it, so a write that
            # had already drawn one would go out behind the device (D-083
            # item 11 is the same mistake in the other direction).
            try:
                await self.async_sync_write_counter()
            except Exception:  # whatever a connection is entitled to raise
                # Left armed, and the write goes out on the counter we hold. A
                # device that could not be reached for the question will fail
                # the write too, visibly; one that could be reached but
                # answered badly is the case §5.6 tells us to ignore. Turning
                # either into an error from a different layer would hide which
                # of the two happened.
                _LOGGER.debug(
                    "%s: could not ask for the write counter before this "
                    "command; writing on the counter we hold",
                    self.address,
                    exc_info=True,
                )
            else:
                self._resync_counter = False

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

    async def async_sync_write_counter(self) -> int | None:
        """Ask the device what counter it is at, and resume from there (D-075).

        The counter is the one thing a receiver cannot work out for itself. When
        its configuration is younger than the device — re-created, restored from
        an old backup, moved — it has nothing to resume from, and D-064 seeds
        from the system clock instead. That is a good default and still a guess,
        and a guess that fails is refused in silence, because §4.2 acknowledges
        a write before validating it.

        So: write a fresh random challenge, read back the sealed report, check
        the challenge came back, and take the counter. Sealing stops a forgery;
        the challenge stops a replay, which sealing alone does not — a receiver
        with no state cannot tell a captured report from a current one.

        Returns the counter adopted, or None when the device does not offer the
        characteristic, cannot be reached, answers something that does not
        authenticate, or reports a counter we are already ahead of. None is not
        a failure: whatever counter we hold stands.
        """
        if self.bindkey is None:
            return None
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            return None

        challenge = secrets.token_bytes(CHALLENGE_LENGTH)
        report: bytes | None = None
        async with self._semaphore:
            # Twice, because the first look can be defeated by our own cache: a
            # device that has just gained the characteristic is exactly a device
            # whose GATT table changed, and the copy we hold does not have it
            # (D-012). Clearing the cache and not looking again meant this did
            # nothing at all the first time it was ever needed -- which, on a
            # device whose firmware changes, is every time (D-080).
            for attempt in (1, 2):
                client = await establish_connection(
                    client_class=BleakClientWithServiceCache,
                    device=device,
                    name=self.address,
                    max_attempts=2,
                )
                try:
                    if client.services.get_characteristic(COUNTER_UUID) is None:
                        await client.clear_cache()
                        if attempt == 1:
                            _LOGGER.debug(
                                "%s: no counter report in the cached GATT table; "
                                "dropped it and looking again",
                                self.address,
                            )
                            continue
                        _LOGGER.debug(
                            "%s: the device does not offer a counter report; "
                            "keeping the seeded counter",
                            self.address,
                        )
                        # Remembered, so that a revision change does not arm a
                        # resynchronisation this device cannot answer -- which
                        # would be a connection per change, for ever (D-092).
                        self._offers_counter_report = False
                        return None
                    self._offers_counter_report = True
                    await client.write_gatt_char(COUNTER_UUID, challenge, response=True)
                    report = bytes(await client.read_gatt_char(COUNTER_UUID))
                    break
                finally:
                    await client.disconnect()

        if report is None:
            return None

        reported = open_counter_report(report, self.bindkey, self.address, challenge)
        if reported is None:
            _LOGGER.warning(
                "%s: the counter report did not authenticate, or answered a "
                "different challenge; keeping the seeded counter",
                self.address,
            )
            return None

        # Ahead of what the device last accepted, which is what it just told
        # us -- but never *behind* where we already are.
        #
        # This ran unconditionally, and the two numbers are not the same order
        # of magnitude: a receiver seeds from its clock, so it starts near
        # 1.76e9 (D-064), while a freshly flashed device resumes near 1. This
        # method is a background task started during setup, and `_write_now`
        # takes its counter before the connection semaphore -- so a command
        # issued in that window goes out sealed at ~1.76e9, is accepted, and
        # then the adoption drops us to 2. Every later write is behind what the
        # device just accepted, and refused in silence because §4.2
        # acknowledges before validating (D-083).
        #
        # In the case this exists for -- the receiver behind a device that
        # restarted ahead -- `reported + 1` is larger and wins, so the guard
        # costs nothing where it is not needed.
        resumed = (reported + 1) % 2**32
        if resumed <= self._counter:
            _LOGGER.debug(
                "%s: the device reports write counter %d; keeping %d, which is "
                "already ahead of it",
                self.address,
                reported,
                self._counter,
            )
            return None

        self._counter = resumed
        self._counter_mark = self._counter + COUNTER_STRIDE
        if self._on_counter is not None:
            self._on_counter(self._counter_mark)
        _LOGGER.info(
            "%s: the device is at write counter %d; resuming from %d",
            self.address,
            reported,
            self._counter,
        )
        return self._counter

    async def async_read_all(self) -> bool:
        """Read every offered, readable entry over one connection.

        Returns whether the device was read -- **all of it**; raises if the
        connection fails.

        It used to return True as soon as the connection had been made, however
        many entries then failed to authenticate or decode. `_read_loop` took
        that as permission to mark the settings revision read, so an entry whose
        read was refused stayed stale until the revision moved again, which for
        a knob nobody touches twice is for ever. That is the thing §3.2 exists
        to prevent, defeated by its own success check (D-083).
        """
        if self.declaration is None:
            return False
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            return False

        changed = False
        failed = False
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
                    if value is None:
                        # Refused, unauthenticated or undecodable. `_open_read`
                        # has said why; what matters here is that this entry's
                        # value is not the one the revision promised.
                        failed = True
                        continue
                    if self._values.get(entry.entry) != value:
                        self._values[entry.entry] = value
                        changed = True
            finally:
                await client.disconnect()

        if changed:
            self._notify()
        return not failed

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
        """Note when this write may be too large for the link (§4.4).

        A write larger than `MTU - 3` is refused by the stack rather than split
        into a long write, so the MTU is a ceiling and not a performance hint
        (decisions.md D-017). BlueZ reports the 23-byte default until asked,
        hence `_acquire_mtu()`.

        **This only writes a line in the log.** It does not refuse anything --
        the docstring said it did, for as long as there was a floor to refuse
        against (D-084). Refusing here would need a size the protocol no longer
        states, and the stack's own error is the honest one.
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
        if mtu is not None and mtu < COMFORTABLE_MTU:
            _LOGGER.debug(
                "%s: MTU is %s and this write is %d bytes, so it may not fit. "
                "The protocol states no floor (§4.4); %s is simply the size "
                "above which anything this protocol sends certainly fits",
                self.address,
                mtu,
                len(payload),
                COMFORTABLE_MTU,
            )

    @property
    def service_uuid(self) -> str:
        return SERVICE_UUID

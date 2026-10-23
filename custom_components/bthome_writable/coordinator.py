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
    AN_UNCHANGED_ENTRY_FAILS_THE_WRITE,
    AUTHENTICATION_FAILURES_BEFORE_REAUTH,
    BTHOME_SERVICE_UUID,
    CHALLENGE_LENGTH,
    COMFORTABLE_MTU,
    CONFIRM_WRITES_BY_READING_BACK,
    COUNTER_RESTART_CEILING,
    COUNTER_STRIDE,
    COUNTER_UUID,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MTU_PAYLOAD,
    EVENT_WRITE,
    FOLD_A_DUE_READ_INTO_A_WRITE,
    FOLD_THE_COUNTER_QUESTION_INTO_A_WRITE,
    READ_RETRY,
    RESYNC_JUMP,
    SERVICE_UUID,
)
from .protocol import (
    Declaration,
    ProtocolError,
    StaleEntry,
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


class StaleTable(Exception):
    """The cached GATT table does not describe the device any more (D-116).

    Raised inside a read pass, once the cache has been dropped, to say that the
    pass has to start again on a rediscovered table rather than report what it
    found. The write path has done this from the start; the read path used to
    carry on and credit the value to the wrong entry, or skip the entry without
    a word.
    """


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
        self._read_connected = False
        """Whether a read currently *holds* a connection, as opposed to waiting
        for one.

        The difference is the whole of D-130. `_notice_revision` asks for a read
        the moment the revision moves, so `_reading` is true within
        milliseconds and stays true while the read queues for a connection
        slot -- which is where a command can overtake it. A read that has not
        connected yet is a read a command can carry; a read that is connected
        cannot be taken over, and must be left to finish."""

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
        self._counter_table_dropped = False
        """Whether a folded look has already missed the characteristic once.

        The separate question of `async_sync_write_counter` looks twice on two
        connections, because the first look can be defeated by our own cache
        (D-080). Folded into a write there is only one connection, so the two
        looks are spread over two writes instead: the first drops the table and
        leaves the question armed, the second decides on a table the stack has
        rediscovered. Same two looks, no connection of their own (D-129)."""

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
            # Not an error, and not silent either: a device that stops being
            # refreshed looks the same from the outside whatever the reason, so
            # every path that declines to connect says so (D-116).
            _LOGGER.debug("%s: no read: one is already running", self.address)
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
                    _LOGGER.debug(
                        "%s: the device was not read in full; no further attempt "
                        "for %.0f s",
                        self.address,
                        READ_RETRY,
                    )
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

                answered = False

                def done(
                    entry: int = entry,
                    waiter: asyncio.Future[None] = waiter,
                ) -> None:
                    # The command is what the caller is waiting for, and §4.2
                    # says the write response is the confirmation. Anything
                    # this connection does afterwards -- a read the revision
                    # had already called for (D-130) -- is ours, not theirs.
                    nonlocal answered
                    answered = True
                    self._report({entry}, None)
                    _settle(waiter, None)

                try:
                    await self._write_now(
                        entry, value, coalesce, queued_at, on_acknowledged=done
                    )
                except Exception as caught:  # broad on purpose: reported to callers
                    if answered:
                        # The command landed and something after it did not:
                        # the folded read swallows its own failures, so this is
                        # the disconnect or the timing report. Saying the write
                        # failed here would contradict the device.
                        _LOGGER.debug(
                            "%s: the command was acknowledged, but the "
                            "connection ended badly: %s",
                            self.address,
                            caught,
                        )
                        continue
                    _LOGGER.warning("%s: write failed: %s", self.address, caught)
                    self._report({entry}, caught)
                    _settle(waiter, caught)
                else:
                    if not answered:
                        done()
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
        on_acknowledged: Callable[[], None] | None = None,
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

        if self._resync_counter and not FOLD_THE_COUNTER_QUESTION_INTO_A_WRITE:
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

        # Encoded before the connection, so that a value this entry cannot
        # carry is refused without waking the device; sealed inside it, below.
        plain = encode_object(entry, value)

        previous = self._values.get(number)
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
                if self._resync_counter:
                    await self._ask_for_the_counter_here(client)
                asked = time.monotonic()
                # Sealed here rather than before the connection, because the
                # question above can move the counter: the value
                # `next_write_counter()` hands out has to be drawn *after* the
                # adoption, or the write goes out behind what the device has
                # already accepted and is refused in silence, §4.2
                # acknowledging before it validates (D-083 item 11).
                payload = plain
                if self.bindkey is not None:
                    payload = seal_write(
                        plain, self.bindkey, self.address, self.next_write_counter()
                    )
                await self._check_mtu(client, payload)
                write_started = time.monotonic()
                await self._write_characteristic(client, entry, payload)
                acknowledged = time.monotonic()
                reported = await self._read_back(client, entry)
                confirmed = time.monotonic()
                read_back = reported
                self._settle_written_value(number, value, reported, previous, coalesce)
                # Released here, not after the connection closes: the command
                # is confirmed and anything this link does next is ours
                # (D-130).
                if on_acknowledged is not None:
                    on_acknowledged()
                if FOLD_A_DUE_READ_INTO_A_WRITE and self._read_is_due():
                    await self._read_due_here(
                        client, skip=number if read_back is not None else None
                    )
            finally:
                await client.disconnect()

        self._report_timing(
            number,
            queued_at=started if queued_at is None else queued_at,
            connect_started=started,
            connected=connected,
            asked=asked,
            write_started=write_started,
            acknowledged=acknowledged,
            confirmed=confirmed,
        )

    def _settle_written_value(
        self,
        number: int,
        value: bytes,
        reported: bytes | None,
        previous: bytes | None,
        coalesce: bool,
    ) -> None:
        """Decide what this entry is worth now the device has answered.

        Inside the connection rather than after it, because what follows on the
        same link is a read that must not undo this decision: the read path
        adopts what the device reports, and this path knows what the write
        asked for and what the device reported before it (D-117, D-122, D-130).
        """
        if reported is not None and reported != value and coalesce:
            # The device answered, and with something other than what it was
            # given. Either it did not get the write, or it has its own idea of
            # the value -- a dimmer that stops at 100, a setpoint quantised to
            # half degrees -- and those two are told apart by one thing: whether
            # anything moved at all (D-117).
            if reported == previous:
                # Nothing moved, and this is where the evidence runs out. A
                # device that applies a write asynchronously answers with the
                # value it had, because §4.3's getter is published rather than
                # served on demand and the module republishes on the tick after
                # the write (D-122, measured). So say so and keep what was
                # written: calling it a failure called @enaon's lamp broken on
                # every command that turned it off.
                if AN_UNCHANGED_ENTRY_FAILS_THE_WRITE:
                    raise WriteFailed(
                        f"{self.address}: entry {number} was acknowledged and "
                        "the device still reports the value it had, so the "
                        "write did not reach it"
                    )
                _LOGGER.warning(
                    "%s: entry %d was acknowledged and the device still reports "
                    "the value it had: either it did not arrive, or the device "
                    "has not republished the entry yet (D-122)",
                    self.address,
                    number,
                )
                reported = None
            else:
                _LOGGER.debug(
                    "%s: entry %d: the device reports %s where %s was written",
                    self.address,
                    number,
                    reported.hex(),
                    value.hex(),
                )

        if coalesce:
            # Events leave no state behind; everything else does. What is kept
            # is the device's own answer when there is one: ours is what we
            # asked for, which is not the same thing.
            self._values[number] = value if reported is None else reported

    def _report_timing(
        self,
        entry: int,
        *,
        queued_at: float,
        connect_started: float,
        connected: float,
        asked: float,
        write_started: float,
        acknowledged: float,
        confirmed: float,
    ) -> None:
        """Say how long a write took, split where the time actually goes.

        Fired as an event rather than logged, so that anyone can watch it: the
        interesting question -- how much of a command is spent waiting to catch
        the device advertising -- is answered by `connect_ms`, and the answer
        depends on the device's advertising interval rather than on anything
        Home Assistant does (`docs/measurements.md`).

        `counter_ms` is the §5.6 question when this command carried one, zero
        otherwise: it used to be a connection of its own and is now three
        packets on this one (D-129), so what it costs has to be visible.
        """
        self.hass.bus.async_fire(
            EVENT_WRITE,
            {
                "address": self.address,
                "entry": entry,
                "queued_ms": round((connect_started - queued_at) * 1000, 1),
                "connect_ms": round((connected - connect_started) * 1000, 1),
                "counter_ms": round((asked - connected) * 1000, 1),
                "write_ms": round((acknowledged - write_started) * 1000, 1),
                "confirm_ms": round((confirmed - acknowledged) * 1000, 1),
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

    async def _read_back(self, client: Any, entry: WritableEntry) -> bytes | None:
        """What the device reports for this entry, in the connection just used.

        None when there is nothing to ask: the feature turned off, a write-only
        entry, or an answer that could not be opened. §4.2 makes the write
        response the confirmation, and over a proxy that response is produced on
        the far side of Wi-Fi by something that is not the device (D-117). An ATT
        response cannot carry proof of delivery -- ATT has no end-to-end
        authentication -- so the only evidence available is the device's own
        answer, and for a readable entry it costs one read on a link that is
        already open.

        An answer carrying *another entry's* object is the stale cached table of
        D-116, met here rather than on the read path -- and it says something
        about the write, not only about the read: the write was addressed through
        that same table, so it may have reached the wrong characteristic. The
        table is dropped and the command reported failed, which is the one
        outcome that neither hides it nor claims the value.
        """
        if not CONFIRM_WRITES_BY_READING_BACK:
            return None
        characteristic = client.services.get_characteristic(entry.uuid)
        if characteristic is None or "read" not in characteristic.properties:
            _LOGGER.debug(
                "%s: entry %d: write-only, so nothing can confirm this write",
                self.address,
                entry.entry,
            )
            return None
        raw = bytes(await client.read_gatt_char(characteristic))
        try:
            return self._open_read(entry, raw)
        except StaleEntry as wrong:
            await client.clear_cache()
            raise WriteFailed(
                f"{self.address}: {wrong}. The write was acknowledged, but the "
                "cached GATT table is stale, so it may have reached another "
                "entry's characteristic. The table has been dropped and the "
                "next command will rediscover it"
            ) from wrong

    @callback
    def async_ask_the_counter_on_the_next_write(self) -> None:
        """Ask the device for its write counter when something next commands it.

        The same arming a moving settings revision does (`_notice_revision`),
        exposed for setup: a receiver whose configuration is younger than the
        device has to ask, and the connection to ask on is the one the first
        command makes (D-129).
        """
        if self.bindkey is None or self._offers_counter_report is False:
            return
        self._resync_counter = True

    async def async_sync_write_counter(self) -> int | None:
        """Ask the device what counter it is at, over a connection of our own.

        This is the standalone form (D-075). The default is now to fold the
        same exchange into the connection a command already holds, which is
        `_ask_for_the_counter_here`; this one remains for a receiver that turns
        `FOLD_THE_COUNTER_QUESTION_INTO_A_WRITE` off, and for asking without a
        command to carry it.

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
                    report = await self._counter_report(client, challenge)
                finally:
                    await client.disconnect()
                if report is not None:
                    break
                if attempt == 1:
                    _LOGGER.debug(
                        "%s: no counter report in the cached GATT table; "
                        "dropped it and looking again",
                        self.address,
                    )
                    continue
                _LOGGER.debug(
                    "%s: the device does not offer a counter report; keeping "
                    "the seeded counter",
                    self.address,
                )
                # Remembered, so that a revision change does not arm a
                # resynchronisation this device cannot answer -- which would be
                # a connection per change, for ever (D-092).
                self._offers_counter_report = False
                return None

        if report is None:
            return None
        self._offers_counter_report = True
        return self._adopt_counter(report, challenge)

    async def _counter_report(self, client: Any, challenge: bytes) -> bytes | None:
        """The device's sealed answer to `challenge`, over a connection in hand.

        None means the characteristic is not in the GATT table we hold -- and
        the table has been dropped, because the copy we hold cannot be trusted
        to say the characteristic is absent: a device that has just gained one
        is exactly a device whose table changed (D-012, D-080). So the answer
        here is *not this time*, and calling a device one that does not offer
        the report takes a second look, at a table the stack rediscovered.
        """
        if client.services.get_characteristic(COUNTER_UUID) is None:
            await client.clear_cache()
            return None
        await client.write_gatt_char(COUNTER_UUID, challenge, response=True)
        return bytes(await client.read_gatt_char(COUNTER_UUID))

    async def _ask_for_the_counter_here(self, client: Any) -> None:
        """Spend an armed resynchronisation on the connection a write holds.

        §5.6 specifies an exchange, not a connection: write a challenge, read
        the sealed report. Carrying it on the write's own link is three packets
        on a link that is already up, where a connection of its own is 0.7 to
        3.4 s of waiting for an advertising event at a 1000 ms advertising
        interval and more at a slower one (`docs/measurements.md` §16). That
        doubling is what a user measured as a slow first command after a
        restart of Home Assistant (D-129).

        Nothing here raises: the write is what the caller came for, and this
        question failing leaves it to go out on the counter we hold, which is
        what the separate path did when its own connection failed.
        """
        challenge = secrets.token_bytes(CHALLENGE_LENGTH)
        try:
            report = await self._counter_report(client, challenge)
        except Exception:  # whatever a GATT exchange is entitled to raise
            # Left armed, so the next command asks again.
            _LOGGER.debug(
                "%s: could not ask for the write counter on this connection; "
                "writing on the counter we hold",
                self.address,
                exc_info=True,
            )
            return

        if report is None:
            if not self._counter_table_dropped:
                # First miss: the table has just been dropped, so this says
                # nothing about the device yet. Stay armed for the next write,
                # which looks at a table the stack has rediscovered.
                self._counter_table_dropped = True
                _LOGGER.debug(
                    "%s: no counter report in the cached GATT table; dropped it "
                    "and the next command will look again",
                    self.address,
                )
                return
            _LOGGER.debug(
                "%s: the device does not offer a counter report; keeping the "
                "seeded counter",
                self.address,
            )
            self._offers_counter_report = False
            self._resync_counter = False
            return

        self._counter_table_dropped = False
        self._offers_counter_report = True
        self._adopt_counter(report, challenge)
        # Answered, so the question is spent whether or not the answer moved us:
        # a report that does not authenticate is the case §5.6 tells us to
        # ignore, and asking again on every command would be a packet pair per
        # command for ever.
        self._resync_counter = False

    def _adopt_counter(self, report: bytes, challenge: bytes) -> int | None:
        """Resume above the counter a report carries, if it authenticates.

        Returns the counter adopted, or None when the report does not open, does
        not answer the challenge we sent, or names a counter we are already
        ahead of.
        """
        assert self.bindkey is not None
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
        # 1.76e9 (D-064), while a freshly flashed device resumes near 1. The
        # question used to run as a background task started during setup while
        # `_write_now` took its counter before the connection semaphore -- so a
        # command issued in that window went out sealed at ~1.76e9, was
        # accepted, and then the adoption dropped us to 2. Every later write is
        # behind what the device just accepted, and refused in silence because
        # §4.2 acknowledges before validating (D-083). A folded question cannot
        # open that window, since the counter is drawn after it (D-129), but a
        # command racing the separate path still can, and the guard is cheap.
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

        Two passes, because the first one can be defeated by our own cache. A
        device whose characteristic layout changed while the list of objects it
        declares did not leaves the cached table wrong in a way nothing else
        notices: the handles still exist, so a read succeeds and returns another
        entry's object, and the only thing standing in the way is the object-ID
        check in `decode_object`. That check used to be the end of it -- the
        value was dropped and the stale table kept, for ever on a value nobody
        writes again (D-116, @enaon). Now it drops the table and reads again.
        """
        if self.declaration is None:
            _LOGGER.debug(
                "%s: no read: nothing has declared writable entries yet",
                self.address,
            )
            return False
        if (
            self._revision_advertised is not None
            and self._revision_advertised == self._revision_read
        ):
            # Nothing left to do, and the cheapest possible way to find out.
            # A read waits for a connection slot, and whatever held that slot
            # may have been a command that carried this very read (D-130). It
            # used to connect anyway and read values it had just stored.
            _LOGGER.debug(
                "%s: no read: settings revision %s has already been read",
                self.address,
                self._revision_read,
            )
            return True
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            _LOGGER.debug(
                "%s: no read: no connectable source for this device", self.address
            )
            return False

        declaration = self.declaration
        for attempt in (1, 2):
            try:
                return await self._read_pass(device, declaration)
            except StaleTable as stale:
                if attempt == 1:
                    _LOGGER.warning(
                        "%s: %s; the cached GATT table has been dropped and the "
                        "device will be read again",
                        self.address,
                        stale,
                    )
                    continue
                _LOGGER.warning(
                    "%s: %s, on a table just rediscovered; the device's entries "
                    "are not where it declares them",
                    self.address,
                    stale,
                )
                return False
        return False

    async def _read_pass(self, device: Any, declaration: Declaration) -> bool:
        """One connection's worth of reading. Raises `StaleTable` to be redone.

        Reads the declaration it was given rather than the live one, so that the
        two passes read the same device: an advertisement arriving between them
        may have replaced it, and that case is already handled where it belongs,
        by dropping the cache on a layout change.
        """
        async with self._semaphore:
            if (
                self._revision_advertised is not None
                and self._revision_advertised == self._revision_read
            ):
                # Checked again on this side of the wait, not only before it:
                # the slot this read was queueing for may have been held by a
                # command that carried the read with it (D-130).
                _LOGGER.debug(
                    "%s: no read: the revision was read while this one waited "
                    "for a connection slot",
                    self.address,
                )
                return True
            client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=device,
                name=self.address,
                max_attempts=2,
            )
            self._read_connected = True
            try:
                return await self._read_entries(client, declaration)
            finally:
                self._read_connected = False
                await client.disconnect()

    async def _read_entries(
        self, client: Any, declaration: Declaration, *, skip: int | None = None
    ) -> bool:
        """Read every offered, readable entry over a connection in hand.

        Returns whether all of them were read, which is what lets `_read_loop`
        mark the settings revision read (D-083). Raises `StaleTable` when the
        cached GATT table has to be dropped and the device read again.

        `skip` is an entry this connection has already settled: a command's own
        read back has decided it, under rules this loop does not have -- what
        was written, and what the device reported before it (D-117, D-122). The
        revision may still be marked read, because that entry *was* read, by
        the command (D-130).

        A value adopted before a `StaleTable` is kept and announced: it decoded
        and carried its own object id, so it is as good as any other read, and
        the pass that follows the dropped table re-reads the rest.
        """
        changed = False
        failed = False
        try:
            for entry in declaration.offered:
                if entry.entry == skip:
                    continue
                characteristic = client.services.get_characteristic(entry.uuid)
                if characteristic is None:
                    # Declared in the advertising, absent from the table we
                    # hold: the same evidence the write path acts on, and
                    # until D-116 the one case the read path skipped in
                    # silence -- leaving the entry stale and *reporting
                    # success*, so nothing ever came back to it.
                    await client.clear_cache()
                    raise StaleTable(
                        f"entry {entry.entry}: characteristic {entry.uuid} is "
                        "declared but not in the cached GATT table"
                    )
                if "read" not in characteristic.properties:
                    # A write-only entry, which is legal: a lamp that takes
                    # commands and reports nothing (§4.3). Logged because
                    # from the outside it looks exactly like a value Home
                    # Assistant refuses to refresh.
                    _LOGGER.debug(
                        "%s: entry %d: write-only, nothing to read",
                        self.address,
                        entry.entry,
                    )
                    continue
                raw = bytes(await client.read_gatt_char(characteristic))
                try:
                    value = self._open_read(entry, raw)
                except StaleEntry as wrong:
                    await client.clear_cache()
                    raise StaleTable(str(wrong)) from wrong
                if value is None:
                    # Refused, unauthenticated or undecodable. `_open_read`
                    # has said why; what matters here is that this entry's
                    # value is not the one the revision promised.
                    failed = True
                    continue
                _LOGGER.debug(
                    "%s: entry %d: read object 0x%02X, %d value bytes%s",
                    self.address,
                    entry.entry,
                    entry.object_id,
                    len(value),
                    "" if self._values.get(entry.entry) == value else ", new",
                )
                if self._values.get(entry.entry) != value:
                    self._values[entry.entry] = value
                    changed = True
        finally:
            if changed:
                self._notify()
        return not failed

    def _read_is_due(self) -> bool:
        """Whether §3.2 has called for a read that has not been made.

        The same question `_notice_revision` asks before starting one, asked
        again where a connection already exists. A read already in flight is
        not due: it has its own connection, and this one cannot cancel it.
        """
        if self.declaration is None or self._read_connected:
            return False
        if self._revision_advertised is None:
            return False
        # `READ_RETRY` is not consulted, and deliberately: a read in its backoff
        # is still due, and the backoff exists to stop us *connecting* again
        # after a failed read. This connection is already open, so carrying the
        # read costs nothing the backoff was protecting and ends the stale
        # window early rather than waiting it out.
        return self._revision_advertised != self._revision_read

    async def _read_due_here(self, client: Any, *, skip: int | None = None) -> None:
        """Make the read §3.2 called for, on the connection a command holds.

        Nothing here raises: the command has been acknowledged and reported,
        and a read that fails leaves the revision unread, which is exactly what
        `_read_loop` would have recorded. The retry follows on a later
        advertisement, as it does for any failed read (D-130).
        """
        declaration = self.declaration
        if declaration is None:
            return
        target = self._revision_advertised
        # Held for the duration, so that an advertisement arriving mid-read
        # does not start a second one over a connection of its own (D-087), and
        # so that a second command does not fold the same read again.
        was_reading = self._reading
        self._reading = True
        self._read_connected = True
        try:
            done = await self._read_entries(client, declaration, skip=skip)
        except Exception as error:  # a stale table, a refused read, the link
            _LOGGER.debug(
                "%s: the read folded into this command failed: %s",
                self.address,
                error,
            )
            done = False
        finally:
            self._read_connected = False
            # A read loop that is waiting for a slot keeps its own flag: it
            # will find the revision read and stand down by itself.
            self._reading = was_reading

        if done:
            self._revision_read = target
            self._read_failed_at = None
            _LOGGER.debug(
                "%s: settings revision %s read on the command's own connection",
                self.address,
                target,
            )
        else:
            self._read_failed_at = time.monotonic()

    def _open_read(self, entry: WritableEntry, raw: bytes) -> bytes | None:
        """A read's value, or None -- with the reason logged -- if unusable.

        Raises `StaleEntry` for the one unusable read that has a remedy: an
        object ID belonging to another entry, which is the cached table being
        wrong rather than the payload.
        """
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
        except StaleEntry:
            raise
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

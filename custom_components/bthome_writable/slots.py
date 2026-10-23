"""The host's cap on simultaneous connections, with a limit that can move.

D-003 caps how many connections this integration opens at once: a Bluetooth
adapter and an ESPHome proxy each have a fixed number of slots, and an
Espruino's UART or Web IDE session needs one of them left free (§5). The cap is
a property of the *host*. What a device needs is different and is not this: its
own turn, one central at a time, which is the lock of D-131.

This replaces the `dict[int, asyncio.Semaphore]` the cap used to live in. That
dictionary gave every distinct limit a semaphore of its own, so two entries
configured at 2 and at 3 would have opened five connections between them: a cap
any disagreement defeated. It was harmless only because nothing could write the
option, so every entry read the same default and the dictionary never held more
than one key. Exposing the option is exactly what would have made it real
(D-132).

An `asyncio.Semaphore` cannot be resized, which is the other reason for a class
of our own: the cap can then move while connections are open, without reloading
the entry and without dropping anyone.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
import contextlib
from contextlib import asynccontextmanager
import logging
import time

from .const import DEFAULT_MAX_CONNECTIONS

_LOGGER = logging.getLogger(__name__)


class ConnectionSlots:
    """A counting gate whose limit can change, and which takes commands first.

    Used through `taken()`, so a slot is released on every way out of the block
    including an exception and a cancellation:

        async with connection_slots().taken(urgent=True):
            ...

    Two queues, each first in first out: a command is urgent because somebody
    is waiting for it, and this integration's own housekeeping -- a state read,
    a cached GATT table to forget -- is not. Nothing guarantees an ordinary
    waiter gets through while commands keep arriving, and that is accepted: a
    read that waits is retried on the next advertisement (`READ_RETRY`), where
    a command that waits is a user watching a switch that has not moved
    (D-134).
    """

    def __init__(self, limit: int = DEFAULT_MAX_CONNECTIONS) -> None:
        self._limit = max(1, limit)
        self._in_flight = 0
        self._urgent: deque[asyncio.Future[None]] = deque()
        self._ordinary: deque[asyncio.Future[None]] = deque()
        self._held_off_until = 0.0

    @property
    def limit(self) -> int:
        """How many connections the host will have open at once."""
        return self._limit

    @property
    def in_flight(self) -> int:
        """How many slots are held right now."""
        return self._in_flight

    @property
    def waiting(self) -> int:
        """How many callers are queued for one."""
        return len(self._urgent) + len(self._ordinary)

    def resize(self, limit: int) -> None:
        """Move the cap, under live traffic.

        Raising it admits whoever is already queued, which is what makes the
        option take effect without a reload. Lowering it never interrupts a slot
        already held: the excess drains as those callers finish, because a
        connection that is open is already costing the adapter its slot and
        cutting it would only turn a user's command into a failure.
        """
        limit = max(1, limit)
        if limit == self._limit:
            return
        self._limit = limit
        self._admit()

    def hold_off(self, seconds: float) -> None:
        """Stop opening connections for a while: the host has no slot free.

        Said by whichever device found out, on behalf of all of them. The one
        in flight is left alone -- it already has its slot -- and the error is
        not the device's to answer for, so this is the only sanction: everyone
        else waits instead of walking into the same wall, where each would
        otherwise spend `bleak_retry_connector`'s nine attempts discovering it
        (D-133).
        """
        until = time.monotonic() + seconds
        if until > self._held_off_until:
            self._held_off_until = until
            _LOGGER.debug("no connection slot was free; holding off %.1fs", seconds)

    @property
    def holding_off(self) -> float:
        """Seconds still to wait before a connection may be opened."""
        return max(0.0, self._held_off_until - time.monotonic())

    async def acquire(self, *, urgent: bool = False) -> None:
        """Wait for a slot. Every caller that returns owes a `release`.

        `urgent` is for a connection somebody is waiting for, which goes ahead
        of any queued housekeeping and behind any queued command.
        """
        # Before the queue rather than after it: the point is not to take a
        # slot and sit on it, it is not to connect yet.
        while (cooling := self.holding_off) > 0:
            await asyncio.sleep(cooling)

        if not self.waiting and self._in_flight < self._limit:
            self._in_flight += 1
            return

        queue = self._urgent if urgent else self._ordinary
        waiter = asyncio.get_running_loop().create_future()
        queue.append(waiter)
        try:
            await waiter
        except asyncio.CancelledError:
            if waiter.done() and not waiter.cancelled():
                # Admitted, then cancelled before resuming: the slot is this
                # caller's and nobody else knows it, so hand it on rather than
                # lose it for the lifetime of the process.
                self._in_flight -= 1
                self._admit()
            else:
                with contextlib.suppress(ValueError):
                    queue.remove(waiter)
            raise

    def release(self) -> None:
        """Give a slot back, and pass it to whoever is first in line."""
        if self._in_flight > 0:
            self._in_flight -= 1
        self._admit()

    def _admit(self) -> None:
        """Let as many waiters through as the current limit allows.

        Commands first, in the order they arrived, then housekeeping in the
        order it arrived.
        """
        while self.waiting and self._in_flight < self._limit:
            queue = self._urgent if self._urgent else self._ordinary
            waiter = queue.popleft()
            # A cancelled waiter is done and wants nothing: skip it, and do not
            # spend the slot on it.
            if not waiter.done():
                self._in_flight += 1
                waiter.set_result(None)

    @asynccontextmanager
    async def taken(self, *, urgent: bool = False) -> AsyncIterator[None]:
        """One slot, held for the block and released on every way out."""
        await self.acquire(urgent=urgent)
        try:
            yield
        finally:
            self.release()


_host = ConnectionSlots()
_asked: dict[str, int] = {}


def connection_slots() -> ConnectionSlots:
    """The one gate every connection this integration opens passes through."""
    return _host


def register_request(address: str, limit: int) -> ConnectionSlots:
    """Record what one device's entry asks of the host cap, and get the gate.

    **The lowest request wins.** The number answers a question about the host --
    how many connections its adapters and proxies can afford -- so every entry's
    options form edits the same host-wide meaning and the entries are expected
    to agree. When they do not, taking the most cautious of them means no value
    a user set is ever exceeded, and the cost of being too cautious is a queue
    where the cost of being too generous is a refused write (D-132).
    """
    _asked[address] = max(1, limit)
    _host.resize(min(_asked.values()))
    return _host


def withdraw_request(address: str) -> None:
    """Forget an entry's request, when it is unloaded or removed.

    Without this a device that is gone would go on holding the cap down for the
    ones that remain.
    """
    if _asked.pop(address, None) is not None:
        _host.resize(min(_asked.values(), default=DEFAULT_MAX_CONNECTIONS))


def reset() -> None:
    """Forget every request and start a fresh gate. For tests.

    Call it before anything is constructed: a coordinator keeps the gate it was
    given, so resetting under a live one leaves that one on the old gate.
    """
    global _host
    _asked.clear()
    _host = ConnectionSlots()

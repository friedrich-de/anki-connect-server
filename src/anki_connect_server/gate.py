"""Serialize collection work from the HTTP API, MCP tools, and automatic sync."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress

BUSY_MESSAGE = "The collection is busy (a sync or another request is running); try again shortly"


class CollectionBusyError(RuntimeError):
    """Raised when the collection stays busy for longer than the caller waits."""


class CollectionGate:
    """One asyncio lock shared by every entry point that touches the collection.

    Anki collections are not safe for concurrent use, and a sync closes and reopens
    the collection. Every request therefore waits for the gate, then runs its
    blocking collection work in a worker thread while holding it.
    """

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self._lock = asyncio.Lock()

    def locked(self) -> bool:
        return self._lock.locked()

    @asynccontextmanager
    async def hold(self, wait: float | None = None) -> AsyncGenerator[None]:
        try:
            await asyncio.wait_for(self._lock.acquire(), self.timeout if wait is None else wait)
        except TimeoutError as error:
            raise CollectionBusyError(BUSY_MESSAGE) from error
        try:
            yield
        finally:
            self._lock.release()

    async def run[T](self, function: Callable[[], T], wait: float | None = None) -> T:
        """Run blocking collection work in a thread while holding the gate.

        A cancelled caller still waits for the thread to finish before the gate is
        released, so cancellation can never let two threads use the collection.
        """
        async with self.hold(wait):
            work = asyncio.ensure_future(asyncio.to_thread(function))
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                while not work.done():
                    with suppress(asyncio.CancelledError):
                        await asyncio.wait({work})
                raise

"""Synchronize with AnkiWeb by itself, so mined cards reach other devices.

The loop watches the collection's sync stamps. Once the collection has changes
that are not on AnkiWeb and has been quiet for ``delay`` seconds, it syncs; it
also syncs every ``interval`` seconds to pull changes made elsewhere. When
AnkiWeb asks for a full sync while this server still has unsynced changes, it
stops instead of replacing them (see ``AnkiWrapper.sync_to_ankiweb``).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from enum import StrEnum

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.gate import CollectionBusyError
from anki_connect_server.sync import SyncConflictError

logger = logging.getLogger(__name__)

MAX_RETRY_SECONDS = 900.0
BLOCKED_RETRY_SECONDS = 600.0


class AutoSyncState(StrEnum):
    OFF = "off"
    STARTING = "starting"
    SYNCING = "syncing"
    OK = "ok"
    FAILING = "failing"
    BLOCKED = "blocked"


class AutoSync:
    def __init__(
        self,
        wrapper: AnkiWrapper,
        *,
        delay: float,
        interval: float,
        poll: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.wrapper = wrapper
        self.delay = delay
        self.interval = interval
        self.poll = poll
        self.clock = clock
        self.state = AutoSyncState.STARTING
        self.last_error: str | None = None
        self._failures = 0
        self._retry_at = 0.0
        self._last_attempt: float | None = None
        self._seen_mod: int | None = None
        self._changed_at = 0.0
        self._pending_since: float | None = None

    @property
    def max_wait(self) -> float:
        """Sync during a long, busy mining session at least this often."""
        return self.delay * 5

    async def run(self) -> None:
        if not self.wrapper.settings.has_ankiweb_credentials:
            self.state = AutoSyncState.OFF
            self.last_error = "AnkiWeb credentials are not configured"
            logger.error("Automatic sync is enabled but AnkiWeb credentials are missing")
            return
        logger.info(
            "Automatic sync: %.0f s after changes, every %.0f s otherwise",
            self.delay,
            self.interval,
        )
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Automatic sync check failed")
            await asyncio.sleep(self.poll)

    async def tick(self) -> None:
        if self.wrapper.gate.locked():
            return
        try:
            mod, last_sync, _usn = await self.wrapper.gate.run(self.wrapper.sync_stamps, 1.0)
        except CollectionBusyError:
            return
        now = self.clock()
        due = False
        if mod > last_sync:
            if self._pending_since is None:
                self._pending_since = now
            if mod != self._seen_mod:
                self._seen_mod = mod
                self._changed_at = now
            due = now - self._changed_at >= self.delay or now - self._pending_since >= self.max_wait
        else:
            self._pending_since = None
            self._seen_mod = None
        if self._last_attempt is None or (
            self.interval > 0 and now - self._last_attempt >= self.interval
        ):
            due = True
        if due and now >= self._retry_at:
            await self.sync_now()

    async def sync_now(self) -> None:
        now = self.clock()
        self._last_attempt = now
        previous = self.state
        self.state = AutoSyncState.SYNCING
        try:
            result = await self.wrapper.gate.run(self.wrapper.sync_to_ankiweb)
        except CollectionBusyError:
            self.state = previous
            return
        except SyncConflictError as error:
            self.state = AutoSyncState.BLOCKED
            self.last_error = str(error)
            self._retry_at = now + max(self.interval, BLOCKED_RETRY_SECONDS)
            logger.warning("Automatic sync is blocked: %s", error)
            return
        except Exception as error:
            self._failures += 1
            self.state = AutoSyncState.FAILING
            self.last_error = str(error)
            backoff = min(self.delay * 2**self._failures, MAX_RETRY_SECONDS)
            self._retry_at = now + backoff
            logger.warning("Automatic sync failed (retry in %.0f s): %s", backoff, error)
            return
        self._failures = 0
        self._retry_at = 0.0
        self.state = AutoSyncState.OK
        self.last_error = None
        self._pending_since = None
        self._seen_mod = None
        logger.info(
            "Automatic sync completed: collection %s, media %s",
            result.collection.outcome,
            result.media.outcome,
        )

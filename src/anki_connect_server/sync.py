"""Typed synchronization results and MCP foreground orchestration."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from enum import StrEnum
from typing import TYPE_CHECKING, Literal

from fastmcp import Context
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from anki_connect_server.anki_wrapper import AnkiWrapper


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionSyncOutcome(StrEnum):
    NO_CHANGES = "no_changes"
    MERGED = "merged"
    DOWNLOADED = "downloaded"


class DownloadReason(StrEnum):
    CONFLICT = "conflict"
    REMOTE_ONLY = "remote_only"


class CollectionSyncResult(_StrictModel):
    outcome: CollectionSyncOutcome
    download_reason: DownloadReason | None = None
    local_data_replaced: bool


class MediaSyncResult(_StrictModel):
    outcome: Literal["completed"] = "completed"
    checked: str | None = None
    added: str | None = None
    removed: str | None = None


class SyncResult(_StrictModel):
    status: Literal["completed"] = "completed"
    collection: CollectionSyncResult
    media: MediaSyncResult
    server_message: str | None = None


class SyncError(RuntimeError):
    """Raised when a synchronization phase cannot complete safely."""


class SyncManager:
    """Run one cancellable foreground sync and relay its progress to MCP."""

    def __init__(self, wrapper: AnkiWrapper) -> None:
        self.wrapper = wrapper
        self._lock = asyncio.Lock()

    async def run(self, context: Context) -> SyncResult:
        if self._lock.locked():
            raise SyncError("A synchronization is already in progress")

        async with self._lock:
            loop = asyncio.get_running_loop()
            events: asyncio.Queue[str] = asyncio.Queue()

            def progress(message: str) -> None:
                loop.call_soon_threadsafe(events.put_nowait, message)

            operation = asyncio.create_task(
                asyncio.to_thread(self.wrapper.sync_to_ankiweb, progress=progress)
            )
            sequence = 0
            try:
                while not operation.done() or not events.empty():
                    try:
                        message = await asyncio.wait_for(events.get(), timeout=0.1)
                    except TimeoutError:
                        continue
                    await context.report_progress(progress=sequence, message=message)
                    sequence += 1
                return await operation
            except asyncio.CancelledError:
                await asyncio.to_thread(self.wrapper.abort_sync)
                with suppress(Exception):
                    await asyncio.shield(operation)
                raise

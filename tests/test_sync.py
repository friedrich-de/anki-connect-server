import asyncio
import threading
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from anki.sync import SyncAuth
from anki.sync_pb2 import (
    MediaSyncProgress,
    MediaSyncStatusResponse,
    SyncCollectionResponse,
    SyncStatusResponse,
)
from fastmcp import Context

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import Config
from anki_connect_server.sync import (
    CollectionSyncOutcome,
    DownloadReason,
    SyncError,
    SyncManager,
    SyncResult,
)


def _sync_wrapper(tmp_path: Path) -> AnkiWrapper:
    settings = Config(
        collection_path=tmp_path / "sync.anki2",
        ankiweb_user="user@example.com",
        ankiweb_pass="secret",
        ankiweb_url="https://sync.example.com",
    )
    return AnkiWrapper(settings.collection_path, settings=settings)


def _media_status(
    *,
    active: bool,
    checked: str = "",
    added: str = "",
    removed: str = "",
) -> MediaSyncStatusResponse:
    return MediaSyncStatusResponse(
        active=active,
        progress=MediaSyncProgress(checked=checked, added=added, removed=removed),
    )


@pytest.mark.parametrize(
    ("required", "reason"),
    [
        (SyncCollectionResponse.FULL_SYNC, DownloadReason.CONFLICT),
        (SyncCollectionResponse.FULL_DOWNLOAD, DownloadReason.REMOTE_ONLY),
    ],
)
def test_full_sync_always_downloads_and_waits_for_media(
    tmp_path: Path,
    required: SyncCollectionResponse.ChangesRequired.ValueType,
    reason: DownloadReason,
) -> None:
    wrapper = _sync_wrapper(tmp_path)
    auth = SyncAuth(hkey="key")
    response = SyncCollectionResponse(
        host_number=7,
        required=required,
        server_media_usn=42,
        server_message="hello",
    )
    progress: list[str] = []
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=auth),
            patch.object(wrapper.col, "sync_collection", return_value=response) as collection_sync,
            patch.object(wrapper.col, "close_for_full_sync") as close_for_full_sync,
            patch.object(wrapper.col, "full_upload_or_download") as full_sync,
            patch.object(wrapper.col, "reopen") as reopen,
            patch.object(
                wrapper.col,
                "media_sync_status",
                side_effect=[
                    _media_status(active=True, checked="1"),
                    _media_status(active=False, checked="2", added="3", removed="4"),
                ],
            ),
            patch("anki_connect_server.anki_wrapper.time.sleep"),
        ):
            result = wrapper.sync_to_ankiweb(progress=progress.append)

        collection_sync.assert_called_once_with(auth, sync_media=True)
        close_for_full_sync.assert_called_once_with()
        full_sync.assert_called_once_with(auth=auth, server_usn=42, upload=False)
        reopen.assert_called_once_with(after_full_sync=True)
        assert result.collection.outcome is CollectionSyncOutcome.DOWNLOADED
        assert result.collection.download_reason is reason
        assert result.collection.local_data_replaced
        assert result.media.model_dump() == {
            "outcome": "completed",
            "checked": "2",
            "added": "3",
            "removed": "4",
        }
        assert result.server_message == "hello"
        assert progress[0] == "Authenticating with AnkiWeb"
        assert "Downloading" in progress[2]
        assert progress[-1] == "Synchronization completed"
    finally:
        wrapper.close()


def test_upload_only_response_fails_safely_and_preserves_local_collection(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    response = SyncCollectionResponse(
        host_number=7,
        required=SyncCollectionResponse.FULL_UPLOAD,
    )
    original_collection = wrapper.col
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=SyncAuth(hkey="key")),
            patch.object(wrapper.col, "sync_collection", return_value=response),
            patch.object(wrapper.col, "full_upload_or_download") as full_sync,
            patch.object(wrapper.col, "sync_media") as media_sync,
            pytest.raises(SyncError, match="only a full upload is possible"),
        ):
            wrapper.sync_to_ankiweb()

        full_sync.assert_not_called()
        media_sync.assert_not_called()
        assert wrapper.col is original_collection
        assert wrapper.collection_generation == 0
        assert "Default" in wrapper.deck_names()
    finally:
        wrapper.close()


@pytest.mark.parametrize(
    ("required", "outcome"),
    [
        (SyncCollectionResponse.NO_CHANGES, CollectionSyncOutcome.NO_CHANGES),
        (SyncCollectionResponse.NORMAL_SYNC, CollectionSyncOutcome.MERGED),
    ],
)
def test_regular_sync_includes_media_and_reopens_collection(
    tmp_path: Path,
    required: SyncCollectionResponse.ChangesRequired.ValueType,
    outcome: CollectionSyncOutcome,
) -> None:
    wrapper = _sync_wrapper(tmp_path)
    auth = SyncAuth(hkey="key")
    response = SyncCollectionResponse(host_number=1, required=required)
    original_collection = wrapper.col
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=auth),
            patch.object(wrapper.col, "sync_collection", return_value=response) as collection_sync,
            patch.object(
                wrapper.col,
                "media_sync_status",
                return_value=_media_status(active=False),
            ) as media_status,
        ):
            result = wrapper.sync_to_ankiweb()

        collection_sync.assert_called_once_with(auth, sync_media=True)
        media_status.assert_called_once_with()
        assert result.collection.outcome is outcome
        assert not result.collection.local_data_replaced
        assert wrapper.col is not original_collection
        assert wrapper.collection_generation == 1
        assert "Default" in wrapper.deck_names()
    finally:
        wrapper.close()


def test_media_failure_reports_partial_completion_and_allows_retry(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    response = SyncCollectionResponse(
        host_number=1,
        required=SyncCollectionResponse.NORMAL_SYNC,
    )
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=SyncAuth(hkey="key")),
            patch.object(wrapper.col, "sync_collection", return_value=response),
            patch.object(wrapper.col, "media_sync_status", side_effect=ValueError("media failed")),
            pytest.raises(
                SyncError,
                match="collection synchronization completed; media remains incomplete",
            ),
        ):
            wrapper.sync_to_ankiweb()

        assert wrapper.collection_generation == 1
        retry_collection = wrapper.col
        with (
            patch.object(retry_collection, "sync_login", return_value=SyncAuth(hkey="key")),
            patch.object(
                retry_collection,
                "sync_collection",
                return_value=SyncCollectionResponse(required=SyncCollectionResponse.NO_CHANGES),
            ),
            patch.object(
                retry_collection,
                "media_sync_status",
                return_value=_media_status(active=False),
            ),
        ):
            retried = wrapper.sync_to_ankiweb()

        assert retried.status == "completed"
        assert wrapper.collection_generation == 2
    finally:
        wrapper.close()


def test_failed_full_download_recovers_collection(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    response = SyncCollectionResponse(
        required=SyncCollectionResponse.FULL_DOWNLOAD,
        server_media_usn=42,
    )
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=SyncAuth(hkey="key")),
            patch.object(wrapper.col, "sync_collection", return_value=response),
            patch.object(wrapper.col, "close_for_full_sync"),
            patch.object(
                wrapper.col,
                "full_upload_or_download",
                side_effect=ValueError("download failed"),
            ),
            patch.object(wrapper.col, "reopen") as reopen,
            pytest.raises(SyncError, match="Full collection download failed"),
        ):
            wrapper.sync_to_ankiweb()

        reopen.assert_called_once_with(after_full_sync=True)
        assert wrapper.collection_generation == 1
        assert "Default" in wrapper.deck_names()
    finally:
        wrapper.close()


def test_authentication_failure_is_phase_specific(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    try:
        with (
            patch.object(wrapper.col, "sync_login", side_effect=ValueError("bad login")),
            pytest.raises(SyncError, match="AnkiWeb authentication failed: bad login"),
        ):
            wrapper.sync_to_ankiweb()
    finally:
        wrapper.close()


def test_collection_network_failure_is_phase_specific(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    original_collection = wrapper.col
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=SyncAuth(hkey="key")),
            patch.object(
                wrapper.col,
                "sync_collection",
                side_effect=ConnectionError("network unavailable"),
            ),
            pytest.raises(
                SyncError,
                match="Collection synchronization failed: network unavailable",
            ),
        ):
            wrapper.sync_to_ankiweb()

        assert wrapper.col is not original_collection
        assert wrapper.collection_generation == 1
        assert "Default" in wrapper.deck_names()
    finally:
        wrapper.close()


def test_concurrent_sync_is_rejected(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    started = threading.Event()
    release = threading.Event()
    results: list[SyncResult] = []
    errors: list[Exception] = []

    def login(**_kwargs: str | None) -> SyncAuth:
        started.set()
        assert release.wait(timeout=2)
        return SyncAuth(hkey="key")

    def run_sync() -> None:
        try:
            results.append(wrapper.sync_to_ankiweb())
        except Exception as error:
            errors.append(error)

    try:
        with (
            patch.object(wrapper.col, "sync_login", side_effect=login),
            patch.object(
                wrapper.col,
                "sync_collection",
                return_value=SyncCollectionResponse(required=SyncCollectionResponse.NO_CHANGES),
            ),
            patch.object(
                wrapper.col,
                "media_sync_status",
                return_value=_media_status(active=False),
            ),
        ):
            thread = threading.Thread(target=run_sync)
            thread.start()
            assert started.wait(timeout=2)
            with pytest.raises(SyncError, match="already in progress"):
                wrapper.sync_to_ankiweb()
            release.set()
            thread.join(timeout=2)

        assert not thread.is_alive()
        assert not errors
        assert len(results) == 1
    finally:
        release.set()
        wrapper.close()


def test_sync_status_and_media_compatibility_actions_wait_for_completion(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    auth = SyncAuth(hkey="key")
    status = SyncStatusResponse(required=SyncStatusResponse.NORMAL_SYNC)
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=auth) as login,
            patch.object(wrapper.col, "sync_status", return_value=status),
            patch.object(wrapper.col, "sync_media") as sync_media,
            patch.object(
                wrapper.col,
                "media_sync_status",
                side_effect=[_media_status(active=True), _media_status(active=False)],
            ) as media_status,
            patch("anki_connect_server.anki_wrapper.time.sleep"),
        ):
            assert wrapper.sync_status() == {"required": 1, "newEndpoint": None}
            assert wrapper.sync_media_only() == "media sync completed"

        login.assert_called_with(
            username="user@example.com",
            password="secret",
            endpoint="https://sync.example.com",
        )
        sync_media.assert_called_once_with(auth)
        assert media_status.call_count == 2
    finally:
        wrapper.close()


class _ProgressContext:
    async def report_progress(
        self,
        progress: float,
        total: float | None = None,
        message: str | None = None,
    ) -> None:
        del progress, total, message


@pytest.mark.asyncio
async def test_mcp_sync_cancellation_aborts_and_waits_for_cleanup(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    manager = SyncManager(wrapper)
    original_collection = wrapper.col
    started = threading.Event()
    aborted = threading.Event()

    def blocking_collection(_auth: SyncAuth, *, sync_media: bool) -> SyncCollectionResponse:
        assert sync_media
        started.set()
        assert aborted.wait(timeout=2)
        raise SyncError("cancelled")

    try:
        with (
            patch.object(
                original_collection,
                "sync_login",
                return_value=SyncAuth(hkey="key"),
            ),
            patch.object(
                original_collection,
                "sync_collection",
                side_effect=blocking_collection,
            ),
            patch.object(original_collection, "abort_sync", side_effect=aborted.set) as abort,
            patch.object(original_collection, "abort_media_sync") as abort_media,
        ):
            operation = asyncio.create_task(manager.run(cast(Context, _ProgressContext())))
            assert await asyncio.to_thread(started.wait, 2)
            operation.cancel()
            with pytest.raises(asyncio.CancelledError):
                await operation

        abort.assert_called_once_with()
        abort_media.assert_called_once_with()
        assert aborted.is_set()
        assert wrapper.col is not original_collection
        assert wrapper.collection_generation == 1
        assert "Default" in wrapper.deck_names()
    finally:
        aborted.set()
        wrapper.close()


def test_missing_sync_credentials_are_reported(settings: Config) -> None:
    wrapper = AnkiWrapper(settings.collection_path, settings=settings)
    try:
        with pytest.raises(ValueError, match="required for sync"):
            wrapper.sync_to_ankiweb()
    finally:
        wrapper.close()

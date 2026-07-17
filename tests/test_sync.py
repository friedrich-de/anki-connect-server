from pathlib import Path
from unittest.mock import patch

import pytest
from anki.sync import SyncAuth
from anki.sync_pb2 import SyncCollectionResponse, SyncStatusResponse

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import Config


def _sync_wrapper(tmp_path: Path, *, full_upload: bool = False) -> AnkiWrapper:
    settings = Config(
        collection_path=tmp_path / "sync.anki2",
        ankiweb_user="user@example.com",
        ankiweb_pass="secret",
        ankiweb_url="https://sync.example.com",
        full_upload=full_upload,
    )
    return AnkiWrapper(settings.collection_path, settings=settings)


@pytest.mark.parametrize(
    ("required", "upload"),
    [
        (SyncCollectionResponse.FULL_SYNC, False),
        (SyncCollectionResponse.FULL_DOWNLOAD, False),
        (SyncCollectionResponse.FULL_UPLOAD, True),
    ],
)
def test_full_sync_directions(
    tmp_path: Path,
    required: SyncCollectionResponse.ChangesRequired.ValueType,
    upload: bool,
) -> None:
    wrapper = _sync_wrapper(tmp_path, full_upload=upload)
    auth = SyncAuth(hkey="key")
    response = SyncCollectionResponse(
        host_number=7,
        required=required,
        server_media_usn=42,
    )
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=auth),
            patch.object(wrapper.col, "sync_collection", return_value=response),
            patch.object(wrapper.col, "close_for_full_sync") as close_for_full_sync,
            patch.object(wrapper.col, "full_upload_or_download") as full_sync,
            patch.object(wrapper.col, "reopen") as reopen,
        ):
            result = wrapper.sync_to_ankiweb()

        assert result == f"sync completed: host=7, required={required}"
        close_for_full_sync.assert_called_once_with()
        full_sync.assert_called_once_with(auth=auth, server_usn=42, upload=upload)
        reopen.assert_called_once_with(after_full_sync=True)
    finally:
        wrapper.close()


def test_full_upload_is_skipped_unless_enabled(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrapper = _sync_wrapper(tmp_path)
    response = SyncCollectionResponse(host_number=7, required=SyncCollectionResponse.FULL_UPLOAD)
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=SyncAuth(hkey="key")),
            patch.object(wrapper.col, "sync_collection", return_value=response),
            patch.object(wrapper.col, "full_upload_or_download") as full_sync,
            caplog.at_level("WARNING"),
        ):
            wrapper.sync_to_ankiweb()

        full_sync.assert_not_called()
        assert "FULL_UPLOAD=false" in caplog.text
    finally:
        wrapper.close()


def test_normal_sync_reopens_collection(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    response = SyncCollectionResponse(host_number=1, required=SyncCollectionResponse.NORMAL_SYNC)
    original_collection = wrapper.col
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=SyncAuth(hkey="key")),
            patch.object(wrapper.col, "sync_collection", return_value=response),
        ):
            wrapper.sync_to_ankiweb()

        assert wrapper.col is not original_collection
        assert "Default" in wrapper.deck_names()
    finally:
        wrapper.close()


def test_failed_full_sync_recovers_collection(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    wrapper = _sync_wrapper(tmp_path)
    response = SyncCollectionResponse(
        host_number=7,
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
                side_effect=ValueError("sync failed"),
            ),
            patch.object(wrapper.col, "reopen") as reopen,
            caplog.at_level("ERROR"),
            pytest.raises(ValueError, match="sync failed"),
        ):
            wrapper.sync_to_ankiweb()

        assert "AnkiWeb sync failed" in caplog.text
        reopen.assert_called_once_with(after_full_sync=True)
        assert "Default" in wrapper.deck_names()
    finally:
        wrapper.close()


def test_sync_status_and_media_forward_credentials(tmp_path: Path) -> None:
    wrapper = _sync_wrapper(tmp_path)
    auth = SyncAuth(hkey="key")
    status = SyncStatusResponse(required=SyncStatusResponse.NORMAL_SYNC)
    try:
        with (
            patch.object(wrapper.col, "sync_login", return_value=auth) as login,
            patch.object(wrapper.col, "sync_status", return_value=status),
            patch.object(wrapper.col, "sync_media") as sync_media,
        ):
            assert wrapper.sync_status() == {"required": 1, "newEndpoint": None}
            assert wrapper.sync_media_only() == "media sync completed"

        login.assert_called_with(
            username="user@example.com",
            password="secret",
            endpoint="https://sync.example.com",
        )
        sync_media.assert_called_once_with(auth)
    finally:
        wrapper.close()


def test_missing_sync_credentials_are_reported(settings: Config) -> None:
    wrapper = AnkiWrapper(settings.collection_path, settings=settings)
    try:
        with pytest.raises(ValueError, match="required for sync"):
            wrapper.sync_to_ankiweb()
    finally:
        wrapper.close()

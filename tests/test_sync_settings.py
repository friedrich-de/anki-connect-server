"""Settings changed on another device survive this server's syncs.

These tests run Anki's own sync server (it ships with the ``anki`` package) and a
second collection that stands in for a desktop Anki, because the rule under test
lives in Anki's sync protocol: the collection's settings travel as a whole, from
the side whose collection was modified last.
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from anki.collection import Collection
from anki.sync_pb2 import SyncCollectionResponse

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import Config
from anki_connect_server.sync import CollectionSyncOutcome

USER = "user"
PASSWORD = "secret"
SETTING = "fsrs"


@pytest.fixture
def sync_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Anki's sync client honours proxy variables; the local server must not go through one.
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "127.0.0.1,localhost")
    environment = {
        **os.environ,
        "SYNC_USER1": f"{USER}:{PASSWORD}",
        "SYNC_BASE": str(tmp_path / "sync-server"),
        "SYNC_HOST": "127.0.0.1",
        "SYNC_PORT": str(port),
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "anki.syncserver"],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if server.poll() is not None or time.monotonic() > deadline:
                    pytest.fail("Anki's sync server did not start")
                time.sleep(0.05)
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.terminate()
        server.wait(timeout=10)


class OtherDevice:
    """A second collection that syncs like a desktop Anki."""

    def __init__(self, path: Path, url: str) -> None:
        self.col = Collection(str(path))
        self.url = url

    def add_note(self, front: str) -> None:
        notetype = self.col.models.by_name("Basic")
        assert notetype is not None
        note = self.col.new_note(notetype)
        note["Front"] = front
        self.col.add_note(note, self.col.decks.get_current_id())

    def sync(self, *, upload: bool = False) -> None:
        auth = self.col.sync_login(username=USER, password=PASSWORD, endpoint=self.url)
        result = self.col.sync_collection(auth, sync_media=False)
        if result.required in (
            SyncCollectionResponse.FULL_SYNC,
            SyncCollectionResponse.FULL_UPLOAD,
            SyncCollectionResponse.FULL_DOWNLOAD,
        ):
            assert upload, "an unexpected full sync was required"
            self.col.close_for_full_sync()
            self.col.full_upload_or_download(auth=auth, server_usn=None, upload=True)
            self.col.reopen(after_full_sync=True)

    def fronts(self) -> list[str]:
        database = self.col.db
        assert database is not None
        return [str(front) for front in database.list("select sfld from notes order by id")]


@pytest.fixture
def desktop(tmp_path: Path, sync_url: str) -> Iterator[OtherDevice]:
    device = OtherDevice(tmp_path / "desktop.anki2", sync_url)
    device.add_note("from the desktop")
    device.sync(upload=True)
    try:
        yield device
    finally:
        device.col.close()


@pytest.fixture
def server(tmp_path: Path, sync_url: str, desktop: OtherDevice) -> Iterator[AnkiWrapper]:
    """This server, already holding the desktop's collection."""
    assert desktop.fronts() == ["from the desktop"]
    settings = Config(
        collection_path=tmp_path / "server.anki2",
        ankiweb_user=USER,
        ankiweb_pass=PASSWORD,
        ankiweb_url=sync_url,
    )
    wrapper = AnkiWrapper(settings.collection_path, settings=settings)
    try:
        assert wrapper.sync_to_ankiweb().collection.outcome is CollectionSyncOutcome.DOWNLOADED
        yield wrapper
    finally:
        wrapper.close()


def _mine(wrapper: AnkiWrapper, front: str) -> None:
    note_id = wrapper.add_note(
        {"deckName": "Default", "modelName": "Basic", "fields": {"Front": front, "Back": ""}}
    )
    assert note_id is not None


def _pause() -> None:
    """Keep the millisecond modification stamps of consecutive steps apart."""
    time.sleep(0.02)


def test_setting_synced_elsewhere_survives_a_card_mined_before_it_was_pulled(
    desktop: OtherDevice, server: AnkiWrapper
) -> None:
    desktop.col.set_config(SETTING, True)
    desktop.sync()
    _pause()

    # The server has not pulled the change yet when the next card is mined on it.
    assert server.col.get_config(SETTING, None) is None
    _mine(server, "mined on the server")
    _pause()
    assert server.sync_to_ankiweb().collection.outcome is CollectionSyncOutcome.MERGED

    assert server.col.get_config(SETTING, None) is True
    assert not server.has_unsynced_changes()
    desktop.sync()
    assert desktop.col.get_config(SETTING, None) is True
    assert desktop.fronts() == ["from the desktop", "mined on the server"]


def test_server_side_counters_still_reach_other_devices_when_nothing_changed_elsewhere(
    desktop: OtherDevice, server: AnkiWrapper
) -> None:
    position = int(desktop.col.get_config("nextPos"))
    _mine(server, "mined on the server")
    _pause()
    assert server.sync_to_ankiweb().collection.outcome is CollectionSyncOutcome.MERGED

    desktop.sync()
    assert desktop.fronts() == ["from the desktop", "mined on the server"]
    assert int(desktop.col.get_config("nextPos")) == position + 1


def test_changes_on_both_sides_merge_and_the_other_device_keeps_its_setting(
    desktop: OtherDevice, server: AnkiWrapper
) -> None:
    _mine(server, "mined first")
    _pause()
    desktop.add_note("added on the desktop")
    desktop.col.set_config(SETTING, True)
    desktop.sync()
    _pause()
    _mine(server, "mined second")
    _pause()
    assert server.sync_to_ankiweb().collection.outcome is CollectionSyncOutcome.MERGED

    desktop.sync()
    expected = sorted(["from the desktop", "mined first", "added on the desktop", "mined second"])
    assert sorted(desktop.fronts()) == expected
    assert sorted(str(front) for front in server.db().list("select sfld from notes")) == expected
    assert desktop.col.get_config(SETTING, None) is True
    assert server.col.get_config(SETTING, None) is True

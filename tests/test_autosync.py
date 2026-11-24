from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.autosync import AutoSync, AutoSyncState
from anki_connect_server.config import Config
from anki_connect_server.sync import (
    CollectionSyncOutcome,
    CollectionSyncResult,
    MediaSyncResult,
    SyncConflictError,
    SyncError,
    SyncResult,
)

RESULT = SyncResult(
    collection=CollectionSyncResult(
        outcome=CollectionSyncOutcome.MERGED, local_data_replaced=False
    ),
    media=MediaSyncResult(),
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def wrapper(tmp_path: Path) -> Iterator[AnkiWrapper]:
    settings = Config(
        collection_path=tmp_path / "auto.anki2",
        ankiweb_user="user@example.com",
        ankiweb_pass="secret",
    )
    value = AnkiWrapper(settings.collection_path, settings=settings)
    try:
        yield value
    finally:
        value.close()


def _mark_synced(wrapper: AnkiWrapper) -> None:
    wrapper.db().execute("update col set ls = mod")


def _mine(wrapper: AnkiWrapper, front: str) -> None:
    wrapper.add_note({"deckName": "Default", "modelName": "Basic", "fields": {"Front": front}})


@pytest.mark.asyncio
async def test_syncs_at_start_then_after_quiet_changes(wrapper: AnkiWrapper) -> None:
    clock = Clock()
    auto = AutoSync(wrapper, delay=30, interval=600, clock=clock)

    def fake_sync() -> SyncResult:
        _mark_synced(wrapper)
        return RESULT

    with patch.object(wrapper, "sync_to_ankiweb", side_effect=fake_sync) as sync:
        await auto.tick()
        assert sync.call_count == 1
        assert auto.state is AutoSyncState.OK

        _mine(wrapper, "first")
        await auto.tick()
        clock.now += 20
        await auto.tick()
        assert sync.call_count == 1

        clock.now += 15
        await auto.tick()
        assert sync.call_count == 2

        # Nothing changed: no sync until the periodic pull is due.
        clock.now += 300
        await auto.tick()
        assert sync.call_count == 2
        clock.now += 300
        await auto.tick()
        assert sync.call_count == 3


@pytest.mark.asyncio
async def test_busy_mining_session_still_syncs_within_the_maximum_wait(
    wrapper: AnkiWrapper,
) -> None:
    clock = Clock()
    auto = AutoSync(wrapper, delay=30, interval=0, clock=clock)

    def fake_sync() -> SyncResult:
        _mark_synced(wrapper)
        return RESULT

    with patch.object(wrapper, "sync_to_ankiweb", side_effect=fake_sync) as sync:
        await auto.tick()
        assert sync.call_count == 1
        for index in range(7):
            _mine(wrapper, f"card {index}")
            clock.now += 25
            await auto.tick()
        assert sync.call_count == 2


@pytest.mark.asyncio
async def test_conflict_blocks_and_failures_back_off(wrapper: AnkiWrapper) -> None:
    clock = Clock()
    auto = AutoSync(wrapper, delay=30, interval=600, clock=clock)

    with patch.object(wrapper, "sync_to_ankiweb", side_effect=SyncConflictError("conflict")):
        await auto.tick()
    assert auto.state is AutoSyncState.BLOCKED
    assert auto.last_error == "conflict"

    with patch.object(wrapper, "sync_to_ankiweb", side_effect=SyncError("offline")) as sync:
        clock.now += 300
        await auto.tick()
        sync.assert_not_called()
        clock.now += 300
        await auto.tick()
        assert sync.call_count == 1
        assert auto.state is AutoSyncState.FAILING
        clock.now += 10
        await auto.tick()
        assert sync.call_count == 1


@pytest.mark.asyncio
async def test_busy_gate_skips_the_check(wrapper: AnkiWrapper) -> None:
    auto = AutoSync(wrapper, delay=30, interval=600, clock=Clock())
    with patch.object(wrapper, "sync_to_ankiweb") as sync:
        async with wrapper.gate.hold():
            await auto.tick()
        sync.assert_not_called()


@pytest.mark.asyncio
async def test_missing_credentials_turn_automatic_sync_off(tmp_path: Path) -> None:
    settings = Config(collection_path=tmp_path / "plain.anki2")
    wrapper = AnkiWrapper(settings.collection_path, settings=settings)
    try:
        auto = AutoSync(wrapper, delay=30, interval=600)
        await auto.run()
        assert auto.state is AutoSyncState.OFF
    finally:
        wrapper.close()

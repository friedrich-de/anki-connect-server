from unittest.mock import patch

import pytest

from anki_connect_server import ANKICONNECT_API_VERSION
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.handlers import dispatch
from anki_connect_server.sync import (
    CollectionSyncOutcome,
    CollectionSyncResult,
    MediaSyncResult,
    SyncResult,
)
from anki_connect_server.types import JsonObject


@pytest.mark.asyncio
async def test_dispatches_version(anki_wrapper: AnkiWrapper) -> None:
    assert await dispatch("version", {}, anki_wrapper) == ANKICONNECT_API_VERSION


@pytest.mark.asyncio
async def test_sync_compatibility_actions_remain_available(anki_wrapper: AnkiWrapper) -> None:
    sync_result = SyncResult(
        collection=CollectionSyncResult(
            outcome=CollectionSyncOutcome.NO_CHANGES,
            local_data_replaced=False,
        ),
        media=MediaSyncResult(),
    )
    with (
        patch.object(anki_wrapper, "sync_to_ankiweb", return_value=sync_result) as sync,
        patch.object(
            anki_wrapper,
            "sync_status",
            return_value={"required": 0, "newEndpoint": None},
        ) as status,
        patch.object(
            anki_wrapper,
            "sync_media_only",
            return_value="media sync completed",
        ) as media,
    ):
        assert await dispatch("sync", {}, anki_wrapper) == sync_result.model_dump(
            mode="json", exclude_none=True
        )
        assert await dispatch("syncStatus", {}, anki_wrapper) == {
            "required": 0,
            "newEndpoint": None,
        }
        assert await dispatch("syncMedia", {}, anki_wrapper) == "media sync completed"

    sync.assert_called_once_with(None, None, None)
    status.assert_called_once_with(None, None, None)
    media.assert_called_once_with(None, None, None)


@pytest.mark.asyncio
async def test_dispatches_note_and_deck_actions(anki_wrapper: AnkiWrapper) -> None:
    deck_id = await dispatch("createDeck", {"deck": "Spanish"}, anki_wrapper)
    note_id = await dispatch(
        "addNote",
        {
            "note": {
                "deckName": "Spanish",
                "modelName": "Basic",
                "fields": {"Front": "hola", "Back": "hello"},
            }
        },
        anki_wrapper,
    )

    assert isinstance(deck_id, int)
    assert isinstance(note_id, int)
    assert note_id in anki_wrapper.find_notes("hola")


@pytest.mark.asyncio
async def test_update_note_fields_preserves_http_response_shape(
    anki_wrapper: AnkiWrapper,
) -> None:
    note_id = anki_wrapper.add_note(
        {
            "deckName": "Default",
            "modelName": "Basic",
            "fields": {"Front": "before", "Back": "unchanged"},
        }
    )
    assert note_id is not None

    result = await dispatch(
        "updateNoteFields",
        {"note": {"id": note_id, "fields": {"Front": "after"}}},
        anki_wrapper,
    )

    assert result is None
    assert anki_wrapper.notes_info([note_id])[0]["fields"] == {
        "Front": {"value": "after", "order": 0},
        "Back": {"value": "unchanged", "order": 1},
    }


@pytest.mark.parametrize(
    ("action", "params", "message"),
    [
        ("createDeck", {}, "Missing required parameters"),
        ("createDeck", {"deck": ""}, "cannot be empty"),
        ("addNote", {"note": "invalid"}, "note must be an object"),
        ("addNotes", {"notes": "invalid"}, "notes must be a list"),
        ("suspend", {"cards": [True]}, "only integers"),
        ("answerCards", {}, "Missing required parameters"),
        ("answerCards", {"answers": [1]}, "only objects"),
        ("answerCards", {"answers": [], "extra": True}, "exactly answers"),
        (
            "answerCards",
            {"answers": [{"cardId": 1, "ease": 3, "extra": True}]},
            "exactly cardId and ease",
        ),
        (
            "answerCards",
            {"answers": [{"cardId": 1, "ease": 0}]},
            "ease must be one of",
        ),
    ],
)
@pytest.mark.asyncio
async def test_validation_errors_are_consistent(
    anki_wrapper: AnkiWrapper,
    action: str,
    params: JsonObject,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await dispatch(action, params, anki_wrapper)


@pytest.mark.asyncio
async def test_multi_preserves_results_and_unknown_action_errors(
    anki_wrapper: AnkiWrapper,
) -> None:
    result = await dispatch(
        "multi",
        {
            "actions": [
                {"action": "version", "params": {}},
                {"action": "missing", "params": {}},
            ]
        },
        anki_wrapper,
    )

    assert result == [6, {"error": "Unknown action: missing"}]


@pytest.mark.asyncio
async def test_unknown_action_is_rejected(anki_wrapper: AnkiWrapper) -> None:
    with pytest.raises(ValueError, match="Unsupported action"):
        await dispatch("missing", {}, anki_wrapper)

import pytest

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.handlers import API_VERSION, dispatch
from anki_connect_server.types import JsonObject


@pytest.mark.asyncio
async def test_dispatches_version(anki_wrapper: AnkiWrapper) -> None:
    assert await dispatch("version", {}, anki_wrapper) == API_VERSION


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


@pytest.mark.parametrize(
    ("action", "params", "message"),
    [
        ("createDeck", {}, "Missing required parameters"),
        ("createDeck", {"deck": ""}, "cannot be empty"),
        ("addNote", {"note": "invalid"}, "note must be an object"),
        ("addNotes", {"notes": "invalid"}, "notes must be a list"),
        ("suspend", {"cards": [True]}, "only integers"),
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

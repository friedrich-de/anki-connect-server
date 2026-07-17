from collections.abc import Iterator

import pytest

from anki_connect_server import wrapper
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.mcp_server import (
    add_note,
    cards_to_notes,
    create_deck,
    find_cards,
    get_api_version,
    get_deck_names,
    get_notes_info,
    mcp,
)


@pytest.fixture(autouse=True)
def initialized_mcp(anki_wrapper: AnkiWrapper) -> Iterator[None]:
    original = wrapper.maybe_get_anki_wrapper()
    wrapper.set_wrapper(anki_wrapper)
    try:
        yield
    finally:
        wrapper.set_wrapper(original)


@pytest.mark.asyncio
async def test_expected_tools_are_registered() -> None:
    names = {tool.name for tool in await mcp.list_tools()}
    assert {"add_note", "get_deck_names", "sync", "get_sync_status"} <= names


def test_representative_mcp_tools_use_shared_wrapper() -> None:
    deck_id = create_deck("MCP")
    note_id = add_note("MCP", "Basic", {"Front": "MCP question", "Back": "answer"})
    assert note_id is not None

    card_ids = find_cards(f"nid:{note_id}")
    assert deck_id > 0
    assert "MCP" in get_deck_names()
    assert cards_to_notes(card_ids) == [note_id]
    assert get_notes_info([note_id])[0]["noteId"] == note_id
    assert get_api_version() == 6


def test_wrapper_access_before_initialization_is_clear() -> None:
    current = wrapper.maybe_get_anki_wrapper()
    wrapper.set_wrapper(None)
    try:
        with pytest.raises(RuntimeError, match="not initialized"):
            get_deck_names()
    finally:
        wrapper.set_wrapper(current)

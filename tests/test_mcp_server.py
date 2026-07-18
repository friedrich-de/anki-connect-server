from typing import cast
from unittest.mock import patch

import pytest
from fastmcp import Client
from mcp.types import AudioContent, ImageContent, TextContent

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.mcp_server import create_mcp_server
from anki_connect_server.types import JsonObject

EXPECTED_TOOLS = {
    "add_note",
    "add_tags",
    "are_due",
    "are_suspended",
    "cards_to_notes",
    "change_deck",
    "create_deck",
    "delete_decks",
    "delete_media_file",
    "delete_notes",
    "export_package",
    "find_cards",
    "find_notes",
    "get_all_tags",
    "get_api_version",
    "get_card_intervals",
    "get_cards_info",
    "get_deck_config",
    "get_deck_names",
    "get_deck_names_and_ids",
    "get_media_dir_path",
    "get_model_field_names",
    "get_model_names",
    "get_model_styling",
    "get_model_templates",
    "get_notes_info",
    "get_next_review_card",
    "get_review_queue",
    "get_sync_status",
    "import_package",
    "remove_tags",
    "retrieve_media_file",
    "store_media_file",
    "suspend_cards",
    "sync",
    "sync_media",
    "submit_review",
    "unsuspend_cards",
}


@pytest.mark.asyncio
async def test_expected_tools_and_schemas_are_registered(anki_wrapper: AnkiWrapper) -> None:
    async with Client(create_mcp_server(lambda: anki_wrapper)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert tools.keys() == EXPECTED_TOOLS
    for tool in tools.values():
        tool_schema = cast(JsonObject, tool.inputSchema)
        tool_properties = tool_schema["properties"]
        assert isinstance(tool_properties, dict)
        assert "context" not in tool_properties

    schema = cast(JsonObject, tools["create_deck"].inputSchema)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {"deck"}

    review_schema = cast(JsonObject, tools["submit_review"].inputSchema)
    review_properties = review_schema["properties"]
    assert isinstance(review_properties, dict)
    rating = review_properties["rating"]
    assert isinstance(rating, dict)
    assert rating["enum"] == ["again", "hard", "good", "easy"]


@pytest.mark.asyncio
async def test_representative_mcp_tools_use_lifespan_wrapper(
    anki_wrapper: AnkiWrapper,
) -> None:
    async with Client(create_mcp_server(lambda: anki_wrapper)) as client:
        deck_id = cast(int, (await client.call_tool("create_deck", {"deck": "MCP"})).data)
        note_id = cast(
            int,
            (
                await client.call_tool(
                    "add_note",
                    {
                        "deck_name": "MCP",
                        "model_name": "Basic",
                        "fields": {"Front": "MCP question", "Back": "answer"},
                    },
                )
            ).data,
        )
        card_ids = cast(
            list[int],
            (await client.call_tool("find_cards", {"query": f"nid:{note_id}"})).data,
        )
        deck_names = cast(list[str], (await client.call_tool("get_deck_names")).data)
        note_ids = cast(
            list[int],
            (await client.call_tool("cards_to_notes", {"cards": card_ids})).data,
        )
        note_info = cast(
            list[JsonObject],
            (await client.call_tool("get_notes_info", {"notes": [note_id]})).data,
        )
        api_version = cast(int, (await client.call_tool("get_api_version")).data)

    assert deck_id > 0
    assert "MCP" in deck_names
    assert note_ids == [note_id]
    assert note_info[0]["noteId"] == note_id
    assert api_version == 6


@pytest.mark.asyncio
async def test_interactive_review_tools_share_session_and_retry_safely(
    anki_wrapper: AnkiWrapper,
) -> None:
    anki_wrapper.col.media.write_data("picture.png", b"\x89PNG")
    anki_wrapper.col.media.write_data("voice.mp3", b"ID3")
    note_id = anki_wrapper.add_note(
        {
            "deckName": "Default",
            "modelName": "Basic",
            "fields": {
                "Front": 'MCP review <img src="picture.png"> [sound:voice.mp3]',
                "Back": "answer",
            },
        }
    )
    assert note_id is not None

    async with Client(create_mcp_server(lambda: anki_wrapper)) as client:
        queue = await client.call_tool("get_review_queue", {"deck": "Default"})
        first = await client.call_tool("get_next_review_card", {"deck": "Default"})
        second = await client.call_tool("get_next_review_card", {"deck": "Default"})
        first_data = cast(JsonObject, first.structured_content)
        second_data = cast(JsonObject, second.structured_content)
        review_id = first_data["review_id"]
        assert isinstance(review_id, str)
        applied = await client.call_tool(
            "submit_review",
            {"review_id": review_id, "rating": "good"},
        )
        retried = await client.call_tool(
            "submit_review",
            {"review_id": review_id, "rating": "good"},
        )

    assert cast(JsonObject, queue.structured_content)["total"] == 1
    assert first_data["review_id"] == second_data["review_id"]
    assert isinstance(first_data["question"], str)
    assert "MCP review" in first_data["question"]
    assert isinstance(first.content[0], TextContent)
    assert any(isinstance(block, ImageContent) for block in first.content)
    assert any(isinstance(block, AudioContent) for block in first.content)
    assert applied.structured_content == retried.structured_content


@pytest.mark.asyncio
async def test_mcp_lifespan_closes_wrapper(anki_wrapper: AnkiWrapper) -> None:
    with patch.object(anki_wrapper, "close") as close:
        async with Client(create_mcp_server(lambda: anki_wrapper)):
            pass

    close.assert_called_once_with()

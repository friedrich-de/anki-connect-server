import json
from collections.abc import Callable
from typing import cast
from unittest.mock import patch

import pytest
from fastmcp import Client
from mcp.types import AudioContent, ImageContent, TextContent

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.mcp_server import create_mcp_server
from anki_connect_server.sync import (
    CollectionSyncOutcome,
    CollectionSyncResult,
    MediaSyncResult,
    SyncResult,
)
from anki_connect_server.types import JsonObject

EXPECTED_TOOLS = {
    "add_note",
    "add_tags",
    "are_due",
    "change_deck",
    "create_deck",
    "delete_decks",
    "delete_media_file",
    "delete_notes",
    "export_package",
    "find_cards",
    "get_all_tags",
    "get_deck_config",
    "get_deck_names",
    "get_model_field_names",
    "get_model_names",
    "get_model_styling",
    "get_model_templates",
    "get_next_review_card",
    "get_review_queue",
    "import_package",
    "inspect_cards",
    "remove_tags",
    "retrieve_media_file",
    "search_notes",
    "store_media_file",
    "suspend_cards",
    "sync",
    "submit_review",
    "unsuspend_cards",
}

REMOVED_MCP_TOOLS = {
    "are_suspended",
    "cards_to_notes",
    "find_notes",
    "get_api_version",
    "get_card_intervals",
    "get_cards_info",
    "get_deck_names_and_ids",
    "get_media_dir_path",
    "get_notes_info",
    "get_sync_status",
    "sync_media",
}


@pytest.mark.asyncio
async def test_expected_tools_and_schemas_are_registered(anki_wrapper: AnkiWrapper) -> None:
    async with Client(create_mcp_server(lambda: anki_wrapper)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert tools.keys() == EXPECTED_TOOLS
    assert len(tools) == 29
    assert REMOVED_MCP_TOOLS.isdisjoint(tools)
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

    search_schema = cast(JsonObject, tools["search_notes"].inputSchema)
    search_properties = search_schema["properties"]
    assert isinstance(search_properties, dict)
    content = search_properties["content"]
    assert isinstance(content, dict)
    assert content["enum"] == ["preview", "fields"]
    assert search_properties["limit"] == {
        "default": 20,
        "maximum": 100,
        "minimum": 1,
        "type": "integer",
    }

    inspect_schema = cast(JsonObject, tools["inspect_cards"].inputSchema)
    inspect_properties = inspect_schema["properties"]
    assert isinstance(inspect_properties, dict)
    property_selection = inspect_properties["properties"]
    assert isinstance(property_selection, dict)
    options = property_selection["anyOf"]
    assert isinstance(options, list)
    array_option = options[0]
    assert isinstance(array_option, dict)
    items = array_option["items"]
    assert isinstance(items, dict)
    assert items["enum"] == [
        "identity",
        "state",
        "scheduling",
        "timestamps",
        "history",
        "fields",
        "all",
    ]

    sync_schema = cast(JsonObject, tools["sync"].outputSchema)
    sync_properties = sync_schema["properties"]
    assert isinstance(sync_properties, dict)
    assert set(sync_properties) == {"status", "collection", "media", "server_message"}


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
        search = await client.call_tool(
            "search_notes",
            {"query": f"nid:{note_id}", "content": "fields"},
        )
        suspended = cast(
            bool,
            (await client.call_tool("suspend_cards", {"cards": card_ids})).data,
        )
        inspection = await client.call_tool(
            "inspect_cards",
            {"note_ids": [note_id]},
        )

    assert deck_id > 0
    assert "MCP" in deck_names
    assert suspended
    search_data = cast(JsonObject, search.structured_content)
    search_notes = search_data["notes"]
    assert isinstance(search_notes, list)
    assert search_data["total"] == 1
    assert search_notes[0] == {
        "note_id": note_id,
        "model": "Basic",
        "tags": [],
        "fields": {"Front": "MCP question", "Back": "answer"},
    }
    inspection_data = cast(JsonObject, inspection.structured_content)
    inspected_cards = inspection_data["cards"]
    assert isinstance(inspected_cards, list)
    inspected = inspected_cards[0]
    assert isinstance(inspected, dict)
    assert set(inspected) == {"card_id", "identity", "state", "scheduling"}
    identity = inspected["identity"]
    state = inspected["state"]
    scheduling = inspected["scheduling"]
    assert isinstance(identity, dict)
    assert identity["note_id"] == note_id
    assert isinstance(state, dict)
    assert state["suspended"] is True
    assert isinstance(scheduling, dict)
    assert scheduling["interval_days"] == 0
    assert isinstance(inspection.content[0], TextContent)
    assert json.loads(inspection.content[0].text) == inspection_data


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
async def test_sync_is_one_foreground_tool_with_progress_and_structured_result(
    anki_wrapper: AnkiWrapper,
) -> None:
    progress_messages: list[str] = []
    expected = SyncResult(
        collection=CollectionSyncResult(
            outcome=CollectionSyncOutcome.MERGED,
            local_data_replaced=False,
        ),
        media=MediaSyncResult(checked="4", added="1", removed="0"),
    )

    def run_sync(*, progress: Callable[[str], None] | None = None) -> SyncResult:
        assert progress is not None
        progress("Authenticating with AnkiWeb")
        progress("Synchronizing collection")
        progress("Synchronizing media")
        progress("Synchronization completed")
        return expected

    async def on_progress(
        _progress: float,
        _total: float | None,
        message: str | None,
    ) -> None:
        if message is not None:
            progress_messages.append(message)

    with patch.object(anki_wrapper, "sync_to_ankiweb", side_effect=run_sync):
        async with Client(
            create_mcp_server(lambda: anki_wrapper),
            progress_handler=on_progress,
        ) as client:
            result = await client.call_tool("sync")

    assert result.structured_content == expected.model_dump(mode="json", exclude_none=True)
    assert progress_messages == [
        "Authenticating with AnkiWeb",
        "Synchronizing collection",
        "Synchronizing media",
        "Synchronization completed",
    ]


@pytest.mark.asyncio
async def test_mcp_lifespan_closes_wrapper(anki_wrapper: AnkiWrapper) -> None:
    with patch.object(anki_wrapper, "close") as close:
        async with Client(create_mcp_server(lambda: anki_wrapper)):
            pass

    close.assert_called_once_with()

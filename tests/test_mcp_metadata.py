import pytest
from fastmcp import Client
from mcp.types import ToolAnnotations

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.mcp_server import create_mcp_server
from anki_connect_server.tool_metadata import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_IDEMPOTENT_WRITE,
    DESTRUCTIVE_OPEN_WORLD_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    READ_ONLY_OPEN_WORLD,
    SERVER_INSTRUCTIONS,
)

EXPECTED_ANNOTATIONS = {
    "add_note": ADDITIVE_WRITE,
    "add_tags": IDEMPOTENT_WRITE,
    "are_due": READ_ONLY,
    "are_suspended": READ_ONLY,
    "cards_to_notes": READ_ONLY,
    "change_deck": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "create_deck": IDEMPOTENT_WRITE,
    "delete_decks": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "delete_media_file": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "delete_notes": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "export_package": DESTRUCTIVE_OPEN_WORLD_WRITE,
    "find_cards": READ_ONLY,
    "find_notes": READ_ONLY,
    "get_all_tags": READ_ONLY,
    "get_api_version": READ_ONLY,
    "get_card_intervals": READ_ONLY,
    "get_cards_info": READ_ONLY,
    "get_deck_config": READ_ONLY,
    "get_deck_names": READ_ONLY,
    "get_deck_names_and_ids": READ_ONLY,
    "get_media_dir_path": READ_ONLY,
    "get_model_field_names": READ_ONLY,
    "get_model_names": READ_ONLY,
    "get_model_styling": READ_ONLY,
    "get_model_templates": READ_ONLY,
    "get_notes_info": READ_ONLY,
    "get_sync_status": READ_ONLY_OPEN_WORLD,
    "import_package": DESTRUCTIVE_OPEN_WORLD_WRITE,
    "remove_tags": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "retrieve_media_file": READ_ONLY,
    "store_media_file": IDEMPOTENT_WRITE,
    "suspend_cards": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "sync": DESTRUCTIVE_OPEN_WORLD_WRITE,
    "sync_media": DESTRUCTIVE_OPEN_WORLD_WRITE,
    "unsuspend_cards": DESTRUCTIVE_IDEMPOTENT_WRITE,
}


@pytest.mark.asyncio
async def test_every_exposed_tool_has_explicit_annotations(
    anki_wrapper: AnkiWrapper,
) -> None:
    async with Client(create_mcp_server(lambda: anki_wrapper)) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}

    assert tools.keys() == EXPECTED_ANNOTATIONS.keys()
    for name, expected in EXPECTED_ANNOTATIONS.items():
        annotations = tools[name].annotations
        assert annotations == expected
        assert annotations is not None
        assert all(
            getattr(annotations, hint) is not None
            for hint in (
                "readOnlyHint",
                "destructiveHint",
                "idempotentHint",
                "openWorldHint",
            )
        )


def test_annotation_profiles_are_explicit() -> None:
    assert (
        ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
        == READ_ONLY
    )
    assert (
        ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        )
        == READ_ONLY_OPEN_WORLD
    )
    assert (
        ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        )
        == ADDITIVE_WRITE
    )
    assert (
        ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
        == IDEMPOTENT_WRITE
    )
    assert (
        ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        )
        == DESTRUCTIVE_IDEMPOTENT_WRITE
    )
    assert (
        ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        )
        == DESTRUCTIVE_OPEN_WORLD_WRITE
    )


@pytest.mark.asyncio
async def test_server_instructions_are_exposed_during_initialization(
    anki_wrapper: AnkiWrapper,
) -> None:
    server = create_mcp_server(lambda: anki_wrapper)
    async with Client(server) as client:
        initialize_result = client.initialize_result

    assert initialize_result is not None
    assert initialize_result.instructions == SERVER_INSTRUCTIONS
    for phrase in (
        "target deck",
        "note type",
        "required fields",
        "find_notes",
        "get_notes_info",
        "state-changing operations",
    ):
        assert phrase in SERVER_INSTRUCTIONS

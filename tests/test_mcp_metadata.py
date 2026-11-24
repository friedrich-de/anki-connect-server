import pytest
from fastmcp import Client
from mcp.types import ToolAnnotations

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.mcp_server import create_mcp_server
from anki_connect_server.tool_metadata import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_IDEMPOTENT_WRITE,
    DESTRUCTIVE_OPEN_WORLD_WRITE,
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    SERVER_INSTRUCTIONS,
)

EXPECTED_ANNOTATIONS = {
    "add_note": ADDITIVE_WRITE,
    "add_tags": IDEMPOTENT_WRITE,
    "are_due": READ_ONLY,
    "change_deck": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "create_deck": IDEMPOTENT_WRITE,
    "delete_decks": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "delete_media_file": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "delete_notes": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "export_package": DESTRUCTIVE_OPEN_WORLD_WRITE,
    "find_cards": READ_ONLY,
    "get_all_tags": READ_ONLY,
    "get_deck_config": READ_ONLY,
    "get_deck_names": READ_ONLY,
    "get_model_field_names": READ_ONLY,
    "get_model_names": READ_ONLY,
    "get_model_styling": READ_ONLY,
    "get_model_templates": READ_ONLY,
    "get_next_review_card": READ_ONLY,
    "get_review_queue": READ_ONLY,
    "import_package": DESTRUCTIVE_OPEN_WORLD_WRITE,
    "inspect_cards": READ_ONLY,
    "remove_tags": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "retrieve_media_file": READ_ONLY,
    "search_notes": READ_ONLY,
    "store_media_file": IDEMPOTENT_WRITE,
    "suspend_cards": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "sync": DESTRUCTIVE_OPEN_WORLD_WRITE,
    "submit_review": IDEMPOTENT_WRITE,
    "unsuspend_cards": DESTRUCTIVE_IDEMPOTENT_WRITE,
    "update_note_fields": DESTRUCTIVE_WRITE,
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
                "read_only_hint",
                "destructive_hint",
                "idempotent_hint",
                "open_world_hint",
            )
        )


def test_annotation_profiles_are_explicit() -> None:
    assert (
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=False,
        )
        == DESTRUCTIVE_WRITE
    )
    assert (
        ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
        == READ_ONLY
    )
    assert (
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        )
        == ADDITIVE_WRITE
    )
    assert (
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        )
        == IDEMPOTENT_WRITE
    )
    assert (
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
        == DESTRUCTIVE_IDEMPOTENT_WRITE
    )
    assert (
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=False,
            open_world_hint=True,
        )
        == DESTRUCTIVE_OPEN_WORLD_WRITE
    )


@pytest.mark.asyncio
async def test_server_instructions_are_exposed_during_initialization(
    anki_wrapper: AnkiWrapper,
) -> None:
    server = create_mcp_server(lambda: anki_wrapper)
    async with Client(server) as client:
        instructions = client.instructions

    assert instructions == SERVER_INSTRUCTIONS
    for phrase in (
        "get_next_review_card",
        "ask exactly its one question",
        "never reveal the returned answer",
        "incorrect, missing, or materially wrong means again",
        "correct or semantically equivalent means good",
        "hard or easy only when the user explicitly",
        "immediately call submit_review",
        "target deck",
        "note type",
        "required fields",
        "search_notes",
        "inspect_cards",
        "find_cards only for card-specific Anki queries",
        "inspect its current fields and note ID",
        "update_note_fields with only the fields the user requested",
        "note edits affect all sibling cards",
        "preserve supplied text and HTML verbatim",
        "Store new binary media",
        "sync tool synchronizes collection data and media",
        "wait for its final result",
        "never uploads a full collection",
        "discard_local_changes only after the user agrees",
        "state-changing operations",
    ):
        assert phrase in SERVER_INSTRUCTIONS

    first_512 = SERVER_INSTRUCTIONS[:512]
    for phrase in ("get_next_review_card", "ask exactly", "submit_review", "fetching the next"):
        assert phrase in first_512

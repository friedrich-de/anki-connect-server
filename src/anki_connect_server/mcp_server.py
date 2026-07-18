import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated

from fastmcp import Context, FastMCP
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel, Field

from anki_connect_server.anki_wrapper import AnkiWrapper, WrapperFactory, create_anki_wrapper
from anki_connect_server.explore import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_SEARCH_LIMIT,
    MAX_INSPECT_IDS,
    MAX_SEARCH_LIMIT,
    InspectCardsResult,
    InspectProperty,
    SearchContent,
    SearchNotesResult,
    inspect_collection_cards,
    search_collection_notes,
)
from anki_connect_server.review import (
    QueueCounts,
    ReviewCardPayload,
    ReviewManager,
    ReviewRating,
    SubmitReviewResult,
)
from anki_connect_server.sync import SyncManager, SyncResult
from anki_connect_server.tool_metadata import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_IDEMPOTENT_WRITE,
    DESTRUCTIVE_OPEN_WORLD_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    SERVER_INSTRUCTIONS,
)
from anki_connect_server.types import JsonObject, NoteInput


@dataclass
class McpState:
    wrapper: AnkiWrapper
    reviews: ReviewManager
    syncs: SyncManager


type AnkiMcpServer = FastMCP[dict[str, McpState]]

_STATE_CONTEXT_KEY = "anki_state"


def _get_state(context: Context) -> McpState:
    value = context.lifespan_context.get(_STATE_CONTEXT_KEY)
    if not isinstance(value, McpState):
        raise RuntimeError("Anki MCP state is not initialized")
    return value


def _get_wrapper(context: Context) -> AnkiWrapper:
    return _get_state(context).wrapper


def _structured_result(value: BaseModel) -> ToolResult:
    structured = value.model_dump(mode="json", exclude_none=True)
    return ToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(structured, ensure_ascii=False, separators=(",", ":")),
            )
        ],
        structured_content=structured,
    )


def get_deck_names(context: Context) -> list[str]:
    """Get all deck names in the collection."""
    return _get_wrapper(context).deck_names()


def create_deck(deck: str, context: Context) -> int:
    """Create a new deck with the given name."""
    return _get_wrapper(context).create_deck(deck)


def delete_decks(context: Context, decks: list[str], cards_too: bool = False) -> bool:
    """Delete one or more decks and optionally their cards."""
    _get_wrapper(context).delete_decks(decks, cards_too)
    return True


def get_model_names(context: Context) -> list[str]:
    """Get all note model names."""
    return _get_wrapper(context).model_names()


def get_model_field_names(model_name: str, context: Context) -> list[str]:
    """Get all field names for a specific model."""
    return _get_wrapper(context).model_field_names(model_name)


def add_note(
    context: Context,
    deck_name: str,
    model_name: str,
    fields: dict[str, str],
    tags: list[str] | None = None,
) -> int | None:
    """Add a new note to the collection."""
    note = NoteInput(
        deckName=deck_name,
        modelName=model_name,
        fields=fields,
        tags=list(tags or []),
    )
    return _get_wrapper(context).add_note(note)


def search_notes(
    query: str,
    context: Context,
    limit: Annotated[int, Field(ge=1, le=MAX_SEARCH_LIMIT)] = DEFAULT_SEARCH_LIMIT,
    offset: Annotated[int, Field(ge=0)] = 0,
    content: SearchContent = SearchContent.PREVIEW,
) -> SearchNotesResult:
    """Search notes with bounded previews or cleaned fields for token-efficient discovery."""
    return search_collection_notes(
        _get_wrapper(context),
        query,
        limit=limit,
        offset=offset,
        content=content,
    )


def delete_notes(notes: list[int], context: Context) -> bool:
    """Delete notes by their IDs."""
    _get_wrapper(context).delete_notes(notes)
    return True


def find_cards(query: str, context: Context) -> list[int]:
    """Find cards matching the given search query."""
    return _get_wrapper(context).find_cards(query)


def inspect_cards(
    context: Context,
    card_ids: Annotated[list[int] | None, Field(min_length=1, max_length=MAX_INSPECT_IDS)] = None,
    note_ids: Annotated[list[int] | None, Field(min_length=1, max_length=MAX_INSPECT_IDS)] = None,
    properties: list[InspectProperty] | None = None,
    history_limit: Annotated[int, Field(ge=1, le=MAX_INSPECT_IDS)] = DEFAULT_HISTORY_LIMIT,
) -> ToolResult:
    """Inspect selected card state, scheduling, history, or cleaned fields without rendering."""
    result = inspect_collection_cards(
        _get_wrapper(context),
        card_ids=card_ids,
        note_ids=note_ids,
        properties=properties,
        history_limit=history_limit,
    )
    return _structured_result(result)


def suspend_cards(cards: list[int], context: Context) -> bool:
    """Suspend one or more cards."""
    return _get_wrapper(context).suspend(cards)


def unsuspend_cards(cards: list[int], context: Context) -> bool:
    """Unsuspend one or more cards."""
    return _get_wrapper(context).unsuspend(cards)


def are_due(cards: list[int], context: Context) -> list[bool]:
    """Check whether cards are due for review."""
    return _get_wrapper(context).are_due(cards)


def get_all_tags(context: Context) -> list[str]:
    """Get all tags in the collection."""
    return _get_wrapper(context).get_tags()


def add_tags(notes: list[int], tags: str, context: Context) -> bool:
    """Add tags to notes."""
    _get_wrapper(context).add_tags(notes, tags)
    return True


def remove_tags(notes: list[int], tags: str, context: Context) -> bool:
    """Remove tags from notes."""
    _get_wrapper(context).remove_tags(notes, tags)
    return True


def change_deck(cards: list[int], deck: str, context: Context) -> bool:
    """Move cards to a different deck."""
    _get_wrapper(context).change_deck(cards, deck)
    return True


def get_deck_config(deck: str, context: Context) -> JsonObject:
    """Get deck configuration."""
    return _get_wrapper(context).get_deck_config(deck)


def get_model_templates(model_name: str, context: Context) -> dict[str, dict[str, str]]:
    """Get card templates for a model."""
    return _get_wrapper(context).model_templates(model_name)


def get_model_styling(model_name: str, context: Context) -> JsonObject:
    """Get CSS styling for a model."""
    return _get_wrapper(context).model_styling(model_name)


def get_review_queue(deck: str, context: Context) -> QueueCounts:
    """Get Anki's current new, learning, and review counts for an existing deck."""
    return _get_state(context).reviews.get_queue(deck)


def get_next_review_card(deck: str, context: Context) -> ToolResult:
    """Get one queued card for an interactive review without changing its schedule."""
    return _get_state(context).reviews.get_next_card(context.session_id, deck)


def submit_review(
    review_id: str,
    rating: ReviewRating,
    context: Context,
) -> SubmitReviewResult:
    """Immediately apply one queued review rating to the local Anki collection."""
    return _get_state(context).reviews.submit(context.session_id, review_id, rating)


def store_media_file(filename: str, data: str, context: Context) -> bool:
    """Store a base64-encoded media file."""
    _get_wrapper(context).store_media_file(filename, data)
    return True


def retrieve_media_file(filename: str, context: Context) -> str | None:
    """Retrieve a media file as base64."""
    return _get_wrapper(context).retrieve_media_file(filename)


def delete_media_file(filename: str, context: Context) -> bool:
    """Delete a media file."""
    _get_wrapper(context).delete_media_file(filename)
    return True


def import_package(path: str, context: Context) -> JsonObject:
    """Import an Anki package."""
    return _get_wrapper(context).import_package(path)


def export_package(
    context: Context,
    deck: str,
    path: str,
    include_sched: bool = False,
) -> bool:
    """Export a deck to an Anki package."""
    _get_wrapper(context).export_package(deck, path, include_sched)
    return True


async def sync(context: Context) -> ToolResult:
    """Synchronize collection data and media with AnkiWeb and wait for completion."""
    return _structured_result(await _get_state(context).syncs.run(context))


def _register_tools(server: AnkiMcpServer) -> None:
    server.tool(get_deck_names, annotations=READ_ONLY)
    server.tool(create_deck, annotations=IDEMPOTENT_WRITE)
    server.tool(delete_decks, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(get_model_names, annotations=READ_ONLY)
    server.tool(get_model_field_names, annotations=READ_ONLY)
    server.tool(add_note, annotations=ADDITIVE_WRITE)
    server.tool(search_notes, annotations=READ_ONLY)
    server.tool(delete_notes, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(find_cards, annotations=READ_ONLY)
    server.tool(
        inspect_cards,
        annotations=READ_ONLY,
        output_schema=InspectCardsResult.model_json_schema(),
    )
    server.tool(suspend_cards, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(unsuspend_cards, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(are_due, annotations=READ_ONLY)
    server.tool(get_all_tags, annotations=READ_ONLY)
    server.tool(add_tags, annotations=IDEMPOTENT_WRITE)
    server.tool(remove_tags, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(change_deck, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(get_deck_config, annotations=READ_ONLY)
    server.tool(get_model_templates, annotations=READ_ONLY)
    server.tool(get_model_styling, annotations=READ_ONLY)
    server.tool(get_review_queue, annotations=READ_ONLY)
    server.tool(
        get_next_review_card,
        annotations=READ_ONLY,
        output_schema=ReviewCardPayload.model_json_schema(),
    )
    server.tool(submit_review, annotations=IDEMPOTENT_WRITE)
    server.tool(store_media_file, annotations=IDEMPOTENT_WRITE)
    server.tool(retrieve_media_file, annotations=READ_ONLY)
    server.tool(delete_media_file, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(import_package, annotations=DESTRUCTIVE_OPEN_WORLD_WRITE)
    server.tool(export_package, annotations=DESTRUCTIVE_OPEN_WORLD_WRITE)
    server.tool(
        sync,
        annotations=DESTRUCTIVE_OPEN_WORLD_WRITE,
        output_schema=SyncResult.model_json_schema(),
    )


def create_mcp_server(wrapper_factory: WrapperFactory = create_anki_wrapper) -> AnkiMcpServer:
    @asynccontextmanager
    async def lifespan(_server: AnkiMcpServer) -> AsyncGenerator[dict[str, McpState]]:
        anki_wrapper = wrapper_factory()
        state = McpState(
            wrapper=anki_wrapper,
            reviews=ReviewManager(anki_wrapper),
            syncs=SyncManager(anki_wrapper),
        )
        try:
            yield {_STATE_CONTEXT_KEY: state}
        finally:
            anki_wrapper.close()

    server = FastMCP(
        name="Anki Connect MCP Server",
        instructions=SERVER_INSTRUCTIONS,
        lifespan=lifespan,
    )
    _register_tools(server)
    return server


mcp = create_mcp_server()


def run() -> None:
    mcp.run()

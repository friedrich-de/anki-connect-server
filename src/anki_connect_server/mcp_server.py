from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import Context, FastMCP

from anki_connect_server import ANKICONNECT_API_VERSION
from anki_connect_server.anki_wrapper import AnkiWrapper, WrapperFactory, create_anki_wrapper
from anki_connect_server.tool_metadata import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_IDEMPOTENT_WRITE,
    DESTRUCTIVE_OPEN_WORLD_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    READ_ONLY_OPEN_WORLD,
    SERVER_INSTRUCTIONS,
)
from anki_connect_server.types import JsonObject, JsonValue, NoteInput

type AnkiMcpServer = FastMCP[dict[str, AnkiWrapper]]

_WRAPPER_CONTEXT_KEY = "anki_wrapper"


def _get_wrapper(context: Context) -> AnkiWrapper:
    value = context.lifespan_context.get(_WRAPPER_CONTEXT_KEY)
    if not isinstance(value, AnkiWrapper):
        raise RuntimeError("Anki wrapper is not initialized")
    return value


def get_deck_names(context: Context) -> list[str]:
    """Get all deck names in the collection."""
    return _get_wrapper(context).deck_names()


def get_deck_names_and_ids(context: Context) -> dict[str, int]:
    """Get all deck names with their IDs."""
    return _get_wrapper(context).deck_names_and_ids()


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


def find_notes(query: str, context: Context) -> list[int]:
    """Find notes matching the given search query."""
    return _get_wrapper(context).find_notes(query)


def get_notes_info(notes: list[int], context: Context) -> list[JsonObject]:
    """Get detailed information about specific notes."""
    return _get_wrapper(context).notes_info(notes)


def delete_notes(notes: list[int], context: Context) -> bool:
    """Delete notes by their IDs."""
    _get_wrapper(context).delete_notes(notes)
    return True


def find_cards(query: str, context: Context) -> list[int]:
    """Find cards matching the given search query."""
    return _get_wrapper(context).find_cards(query)


def get_cards_info(cards: list[int], context: Context) -> list[JsonObject]:
    """Get detailed information about specific cards."""
    return _get_wrapper(context).cards_info(cards)


def suspend_cards(cards: list[int], context: Context) -> bool:
    """Suspend one or more cards."""
    return _get_wrapper(context).suspend(cards)


def unsuspend_cards(cards: list[int], context: Context) -> bool:
    """Unsuspend one or more cards."""
    return _get_wrapper(context).unsuspend(cards)


def are_suspended(cards: list[int], context: Context) -> list[bool]:
    """Check whether cards are suspended."""
    return _get_wrapper(context).are_suspended(cards)


def are_due(cards: list[int], context: Context) -> list[bool]:
    """Check whether cards are due for review."""
    return _get_wrapper(context).are_due(cards)


def get_card_intervals(
    context: Context,
    cards: list[int],
    complete: bool = False,
) -> list[JsonValue]:
    """Get intervals for cards."""
    return _get_wrapper(context).get_intervals(cards, complete)


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


def get_media_dir_path(context: Context) -> str:
    """Get the path to the media directory."""
    return _get_wrapper(context).get_media_dir_path()


def change_deck(cards: list[int], deck: str, context: Context) -> bool:
    """Move cards to a different deck."""
    _get_wrapper(context).change_deck(cards, deck)
    return True


def cards_to_notes(cards: list[int], context: Context) -> list[int]:
    """Convert card IDs to note IDs."""
    return _get_wrapper(context).cards_to_notes(cards)


def get_deck_config(deck: str, context: Context) -> JsonObject:
    """Get deck configuration."""
    return _get_wrapper(context).get_deck_config(deck)


def get_model_templates(model_name: str, context: Context) -> dict[str, dict[str, str]]:
    """Get card templates for a model."""
    return _get_wrapper(context).model_templates(model_name)


def get_model_styling(model_name: str, context: Context) -> JsonObject:
    """Get CSS styling for a model."""
    return _get_wrapper(context).model_styling(model_name)


def get_api_version() -> int:
    """Get the AnkiConnect API version."""
    return ANKICONNECT_API_VERSION


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


def sync(context: Context) -> str:
    """Sync the collection with AnkiWeb."""
    return _get_wrapper(context).sync_to_ankiweb()


def sync_media(context: Context) -> str:
    """Sync only media files with AnkiWeb."""
    return _get_wrapper(context).sync_media_only()


def get_sync_status(context: Context) -> JsonObject:
    """Get sync status from AnkiWeb."""
    return _get_wrapper(context).sync_status()


def _register_tools(server: AnkiMcpServer) -> None:
    server.tool(get_deck_names, annotations=READ_ONLY)
    server.tool(get_deck_names_and_ids, annotations=READ_ONLY)
    server.tool(create_deck, annotations=IDEMPOTENT_WRITE)
    server.tool(delete_decks, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(get_model_names, annotations=READ_ONLY)
    server.tool(get_model_field_names, annotations=READ_ONLY)
    server.tool(add_note, annotations=ADDITIVE_WRITE)
    server.tool(find_notes, annotations=READ_ONLY)
    server.tool(get_notes_info, annotations=READ_ONLY)
    server.tool(delete_notes, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(find_cards, annotations=READ_ONLY)
    server.tool(get_cards_info, annotations=READ_ONLY)
    server.tool(suspend_cards, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(unsuspend_cards, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(are_suspended, annotations=READ_ONLY)
    server.tool(are_due, annotations=READ_ONLY)
    server.tool(get_card_intervals, annotations=READ_ONLY)
    server.tool(get_all_tags, annotations=READ_ONLY)
    server.tool(add_tags, annotations=IDEMPOTENT_WRITE)
    server.tool(remove_tags, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(get_media_dir_path, annotations=READ_ONLY)
    server.tool(change_deck, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(cards_to_notes, annotations=READ_ONLY)
    server.tool(get_deck_config, annotations=READ_ONLY)
    server.tool(get_model_templates, annotations=READ_ONLY)
    server.tool(get_model_styling, annotations=READ_ONLY)
    server.tool(get_api_version, annotations=READ_ONLY)
    server.tool(store_media_file, annotations=IDEMPOTENT_WRITE)
    server.tool(retrieve_media_file, annotations=READ_ONLY)
    server.tool(delete_media_file, annotations=DESTRUCTIVE_IDEMPOTENT_WRITE)
    server.tool(import_package, annotations=DESTRUCTIVE_OPEN_WORLD_WRITE)
    server.tool(export_package, annotations=DESTRUCTIVE_OPEN_WORLD_WRITE)
    server.tool(sync, annotations=DESTRUCTIVE_OPEN_WORLD_WRITE)
    server.tool(sync_media, annotations=DESTRUCTIVE_OPEN_WORLD_WRITE)
    server.tool(get_sync_status, annotations=READ_ONLY_OPEN_WORLD)


def create_mcp_server(wrapper_factory: WrapperFactory = create_anki_wrapper) -> AnkiMcpServer:
    @asynccontextmanager
    async def lifespan(_server: AnkiMcpServer) -> AsyncGenerator[dict[str, AnkiWrapper]]:
        anki_wrapper = wrapper_factory()
        try:
            yield {_WRAPPER_CONTEXT_KEY: anki_wrapper}
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

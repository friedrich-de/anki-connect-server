from fastmcp import FastMCP

from anki_connect_server import wrapper
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import Config, get_config
from anki_connect_server.types import JsonObject, JsonValue, NoteInput


def get_wrapper(settings: Config | None = None) -> AnkiWrapper:
    resolved_settings = settings or get_config()
    return AnkiWrapper(resolved_settings.collection_path, settings=resolved_settings)


def init_wrapper(settings: Config | None = None) -> None:
    wrapper.set_wrapper(get_wrapper(settings))


mcp = FastMCP(name="Anki Connect MCP Server")


@mcp.tool
def get_deck_names() -> list[str]:
    """Get all deck names in the collection."""
    return wrapper.get_anki_wrapper().deck_names()


@mcp.tool
def get_deck_names_and_ids() -> dict[str, int]:
    """Get all deck names with their IDs."""
    return wrapper.get_anki_wrapper().deck_names_and_ids()


@mcp.tool
def create_deck(deck: str) -> int:
    """Create a new deck with the given name."""
    return wrapper.get_anki_wrapper().create_deck(deck)


@mcp.tool
def delete_decks(decks: list[str], cards_too: bool = False) -> bool:
    """Delete one or more decks and optionally their cards."""
    wrapper.get_anki_wrapper().delete_decks(decks, cards_too)
    return True


@mcp.tool
def get_model_names() -> list[str]:
    """Get all note model names."""
    return wrapper.get_anki_wrapper().model_names()


@mcp.tool
def get_model_field_names(model_name: str) -> list[str]:
    """Get all field names for a specific model."""
    return wrapper.get_anki_wrapper().model_field_names(model_name)


@mcp.tool
def add_note(
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
    return wrapper.get_anki_wrapper().add_note(note)


@mcp.tool
def find_notes(query: str) -> list[int]:
    """Find notes matching the given search query."""
    return wrapper.get_anki_wrapper().find_notes(query)


@mcp.tool
def get_notes_info(notes: list[int]) -> list[JsonObject]:
    """Get detailed information about specific notes."""
    return wrapper.get_anki_wrapper().notes_info(notes)


@mcp.tool
def delete_notes(notes: list[int]) -> bool:
    """Delete notes by their IDs."""
    wrapper.get_anki_wrapper().delete_notes(notes)
    return True


@mcp.tool
def find_cards(query: str) -> list[int]:
    """Find cards matching the given search query."""
    return wrapper.get_anki_wrapper().find_cards(query)


@mcp.tool
def get_cards_info(cards: list[int]) -> list[JsonObject]:
    """Get detailed information about specific cards."""
    return wrapper.get_anki_wrapper().cards_info(cards)


@mcp.tool
def suspend_cards(cards: list[int]) -> bool:
    """Suspend one or more cards."""
    return wrapper.get_anki_wrapper().suspend(cards)


@mcp.tool
def unsuspend_cards(cards: list[int]) -> bool:
    """Unsuspend one or more cards."""
    return wrapper.get_anki_wrapper().unsuspend(cards)


@mcp.tool
def are_suspended(cards: list[int]) -> list[bool]:
    """Check whether cards are suspended."""
    return wrapper.get_anki_wrapper().are_suspended(cards)


@mcp.tool
def are_due(cards: list[int]) -> list[bool]:
    """Check whether cards are due for review."""
    return wrapper.get_anki_wrapper().are_due(cards)


@mcp.tool
def get_card_intervals(cards: list[int], complete: bool = False) -> list[JsonValue]:
    """Get intervals for cards."""
    return wrapper.get_anki_wrapper().get_intervals(cards, complete)


@mcp.tool
def get_all_tags() -> list[str]:
    """Get all tags in the collection."""
    return wrapper.get_anki_wrapper().get_tags()


@mcp.tool
def add_tags(notes: list[int], tags: str) -> bool:
    """Add tags to notes."""
    wrapper.get_anki_wrapper().add_tags(notes, tags)
    return True


@mcp.tool
def remove_tags(notes: list[int], tags: str) -> bool:
    """Remove tags from notes."""
    wrapper.get_anki_wrapper().remove_tags(notes, tags)
    return True


@mcp.tool
def get_media_dir_path() -> str:
    """Get the path to the media directory."""
    return wrapper.get_anki_wrapper().get_media_dir_path()


@mcp.tool
def change_deck(cards: list[int], deck: str) -> bool:
    """Move cards to a different deck."""
    wrapper.get_anki_wrapper().change_deck(cards, deck)
    return True


@mcp.tool
def cards_to_notes(cards: list[int]) -> list[int]:
    """Convert card IDs to note IDs."""
    return wrapper.get_anki_wrapper().cards_to_notes(cards)


@mcp.tool
def get_deck_config(deck: str) -> JsonObject:
    """Get deck configuration."""
    return wrapper.get_anki_wrapper().get_deck_config(deck)


@mcp.tool
def get_model_templates(model_name: str) -> dict[str, dict[str, str]]:
    """Get card templates for a model."""
    return wrapper.get_anki_wrapper().model_templates(model_name)


@mcp.tool
def get_model_styling(model_name: str) -> JsonObject:
    """Get CSS styling for a model."""
    return wrapper.get_anki_wrapper().model_styling(model_name)


@mcp.tool
def get_api_version() -> int:
    """Get the AnkiConnect API version."""
    return 6


@mcp.tool
def store_media_file(filename: str, data: str) -> bool:
    """Store a base64-encoded media file."""
    wrapper.get_anki_wrapper().store_media_file(filename, data)
    return True


@mcp.tool
def retrieve_media_file(filename: str) -> str | None:
    """Retrieve a media file as base64."""
    return wrapper.get_anki_wrapper().retrieve_media_file(filename)


@mcp.tool
def delete_media_file(filename: str) -> bool:
    """Delete a media file."""
    wrapper.get_anki_wrapper().delete_media_file(filename)
    return True


@mcp.tool
def import_package(path: str) -> JsonObject:
    """Import an Anki package."""
    return wrapper.get_anki_wrapper().import_package(path)


@mcp.tool
def export_package(deck: str, path: str, include_sched: bool = False) -> bool:
    """Export a deck to an Anki package."""
    wrapper.get_anki_wrapper().export_package(deck, path, include_sched)
    return True


@mcp.tool
def sync() -> str:
    """Sync the collection with AnkiWeb."""
    return wrapper.get_anki_wrapper().sync_to_ankiweb()


@mcp.tool
def sync_media() -> str:
    """Sync only media files with AnkiWeb."""
    return wrapper.get_anki_wrapper().sync_media_only()


@mcp.tool
def get_sync_status() -> JsonObject:
    """Get sync status from AnkiWeb."""
    return wrapper.get_anki_wrapper().sync_status()


mcp_app = mcp.http_app()


def run() -> None:
    init_wrapper()
    try:
        mcp.run()
    finally:
        wrapper.close_wrapper()


if __name__ == "__main__":
    run()

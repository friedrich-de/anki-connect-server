"""Shared MCP metadata for the server and its registered tools."""

from mcp.types import ToolAnnotations

SERVER_INSTRUCTIONS = (
    "Use these tools to inspect and modify the user's Anki collection. Before adding a note, "
    "identify the target deck, note type, and required fields with get_deck_names, "
    "get_model_names, and get_model_field_names. Before changing or deleting existing data, "
    "locate it with find_notes or find_cards and inspect it with get_notes_info or "
    "get_cards_info. Only perform state-changing operations when the user has requested them, "
    "and report returned IDs and failures. Import, export, and AnkiWeb sync tools interact with "
    "resources outside the collection; verify their paths, scope, and intended direction first."
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

READ_ONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

ADDITIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)

IDEMPOTENT_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

DESTRUCTIVE_IDEMPOTENT_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)

DESTRUCTIVE_OPEN_WORLD_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

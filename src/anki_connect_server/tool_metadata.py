"""Shared MCP metadata for the server and its registered tools."""

from mcp.types import ToolAnnotations

SERVER_INSTRUCTIONS = (
    "For an interactive deck review, call get_next_review_card, ask exactly its one question, "
    "and never reveal the returned answer before the user responds. Wait for the response, "
    "compare it semantically with the answer, then immediately call submit_review: incorrect, "
    "missing, or materially wrong means again; correct or semantically equivalent means good. "
    "Use hard or easy only when the user explicitly requests or supplies that rating. Report any "
    "submission failure before fetching the next card, then repeat one card at a time. The user's "
    "review request authorizes each inferred rating. Ratings remain local until sync is called. "
    "Use these tools to inspect and modify the user's Anki collection. Before adding a note, "
    "identify the target deck, note type, and required fields with get_deck_names, "
    "get_model_names, and get_model_field_names. Before changing or deleting existing data, "
    "locate it with search_notes and use inspect_cards for targeted state, scheduling, history, "
    "or cleaned fields. Use find_cards only for card-specific Anki queries that note search "
    "cannot express. Only perform state-changing operations when the user has requested them, "
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

"""Token-efficient note discovery and sparse card inspection."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, cast

import anki.collection  # Import before anki.cards to avoid its hook cycle.
from anki import stats_pb2
from anki.cards import Card, CardId
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_RELEARNING,
    CARD_TYPE_REV,
    MODEL_STD,
    QUEUE_TYPE_DAY_LEARN_RELEARN,
    QUEUE_TYPE_LRN,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_NEW,
    QUEUE_TYPE_PREVIEW,
    QUEUE_TYPE_REV,
    QUEUE_TYPE_SIBLING_BURIED,
    QUEUE_TYPE_SUSPENDED,
)
from anki.errors import NotFoundError
from anki.notes import Note, NoteId
from pydantic import BaseModel, ConfigDict, Field

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.content import clean_field_html

SEARCH_PREVIEW_CHARACTERS = 120
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100
DEFAULT_HISTORY_LIMIT = 20
MAX_INSPECT_IDS = 100

type CardTypeName = Literal["new", "learning", "review", "relearning", "unknown"]
type CardQueueName = Literal[
    "user_buried",
    "scheduler_buried",
    "suspended",
    "new",
    "learning",
    "review",
    "day_learning",
    "preview",
    "unknown",
]
type ReviewKind = Literal[
    "learning", "review", "relearning", "filtered", "manual", "rescheduled", "unknown"
]
type ReviewButton = Literal["again", "hard", "good", "easy", "unknown"]

_CARD_TYPES: dict[int, CardTypeName] = {
    int(CARD_TYPE_NEW): "new",
    int(CARD_TYPE_LRN): "learning",
    int(CARD_TYPE_REV): "review",
    int(CARD_TYPE_RELEARNING): "relearning",
}
_CARD_QUEUES: dict[int, CardQueueName] = {
    int(QUEUE_TYPE_MANUALLY_BURIED): "user_buried",
    int(QUEUE_TYPE_SIBLING_BURIED): "scheduler_buried",
    int(QUEUE_TYPE_SUSPENDED): "suspended",
    int(QUEUE_TYPE_NEW): "new",
    int(QUEUE_TYPE_LRN): "learning",
    int(QUEUE_TYPE_REV): "review",
    int(QUEUE_TYPE_DAY_LEARN_RELEARN): "day_learning",
    int(QUEUE_TYPE_PREVIEW): "preview",
}
_REVIEW_KINDS: dict[int, ReviewKind] = {
    stats_pb2.RevlogEntry.LEARNING: "learning",
    stats_pb2.RevlogEntry.REVIEW: "review",
    stats_pb2.RevlogEntry.RELEARNING: "relearning",
    stats_pb2.RevlogEntry.FILTERED: "filtered",
    stats_pb2.RevlogEntry.MANUAL: "manual",
    stats_pb2.RevlogEntry.RESCHEDULED: "rescheduled",
}
_REVIEW_BUTTONS: dict[int, ReviewButton] = {
    1: "again",
    2: "hard",
    3: "good",
    4: "easy",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchContent(StrEnum):
    PREVIEW = "preview"
    FIELDS = "fields"


class NotePreview(_StrictModel):
    note_id: int
    model: str
    tags: list[str]
    preview: str


class NoteFields(_StrictModel):
    note_id: int
    model: str
    tags: list[str]
    fields: dict[str, str]


class SearchNotesResult(_StrictModel):
    query: str
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    returned: int = Field(ge=0)
    has_more: bool
    notes: list[NotePreview | NoteFields]
    missing_note_ids: list[int]


class InspectProperty(StrEnum):
    IDENTITY = "identity"
    STATE = "state"
    SCHEDULING = "scheduling"
    TIMESTAMPS = "timestamps"
    HISTORY = "history"
    FIELDS = "fields"
    ALL = "all"


_DEFAULT_PROPERTIES = (
    InspectProperty.IDENTITY,
    InspectProperty.STATE,
    InspectProperty.SCHEDULING,
)
_ALL_PROPERTIES = (
    *_DEFAULT_PROPERTIES,
    InspectProperty.TIMESTAMPS,
    InspectProperty.HISTORY,
    InspectProperty.FIELDS,
)


class CardIdentity(_StrictModel):
    note_id: int
    deck: str
    model: str
    template: str


class CardState(_StrictModel):
    card_type: CardTypeName
    queue: CardQueueName
    suspended: bool
    buried: bool


class FsrsMemory(_StrictModel):
    stability: float
    difficulty: float


class CardScheduling(_StrictModel):
    due_at: str | None = None
    due_position: int | None = None
    interval_days: int = Field(ge=0)
    ease_factor: float | None = None
    reviews: int = Field(ge=0)
    lapses: int = Field(ge=0)
    remaining_steps: int = Field(ge=0)
    memory: FsrsMemory | None = None
    retrievability: float | None = None
    desired_retention: float | None = None


class CardTimestamps(_StrictModel):
    added_at: str
    modified_at: str
    first_review_at: str | None = None
    latest_review_at: str | None = None


class ReviewHistoryEntry(_StrictModel):
    reviewed_at: str
    kind: ReviewKind
    rating: ReviewButton
    interval_seconds: int
    previous_interval_seconds: int
    elapsed_seconds: float = Field(ge=0)
    ease_factor: float | None = None
    memory: FsrsMemory | None = None


class CardHistory(_StrictModel):
    total: int = Field(ge=0)
    entries: list[ReviewHistoryEntry]


class InspectedCard(_StrictModel):
    card_id: int
    identity: CardIdentity | None = None
    state: CardState | None = None
    scheduling: CardScheduling | None = None
    timestamps: CardTimestamps | None = None
    history: CardHistory | None = None
    fields: dict[str, str] | None = None


class InspectCardsResult(_StrictModel):
    properties: list[InspectProperty]
    cards: list[InspectedCard]
    missing_card_ids: list[int]
    missing_note_ids: list[int]


def search_collection_notes(
    wrapper: AnkiWrapper,
    query: str,
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    content: SearchContent = SearchContent.PREVIEW,
) -> SearchNotesResult:
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    collection: anki.collection.Collection = wrapper.col
    note_ids = [int(note_id) for note_id in collection.find_notes(query)]
    page_ids = note_ids[offset : offset + limit]
    notes: list[NotePreview | NoteFields] = []
    missing: list[int] = []
    for note_id in page_ids:
        try:
            note = collection.get_note(NoteId(note_id))
        except NotFoundError:
            missing.append(note_id)
            continue
        model = collection.models.get(note.mid)
        model_name = cast(str, model.get("name", "")) if model is not None else ""
        cleaned = _clean_fields(wrapper, note)
        if content is SearchContent.FIELDS:
            notes.append(
                NoteFields(
                    note_id=note_id,
                    model=model_name,
                    tags=list(note.tags),
                    fields=cleaned,
                )
            )
        else:
            preview = next(iter(cleaned.values()), "")
            if len(preview) > SEARCH_PREVIEW_CHARACTERS:
                preview = preview[:SEARCH_PREVIEW_CHARACTERS].rstrip() + "…"
            notes.append(
                NotePreview(
                    note_id=note_id,
                    model=model_name,
                    tags=list(note.tags),
                    preview=preview,
                )
            )
    return SearchNotesResult(
        query=query,
        total=len(note_ids),
        offset=offset,
        returned=len(notes),
        has_more=offset + len(page_ids) < len(note_ids),
        notes=notes,
        missing_note_ids=missing,
    )


def inspect_collection_cards(
    wrapper: AnkiWrapper,
    *,
    card_ids: Sequence[int] | None = None,
    note_ids: Sequence[int] | None = None,
    properties: Sequence[InspectProperty] | None = None,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
) -> InspectCardsResult:
    if (card_ids is None) == (note_ids is None):
        raise ValueError("Provide exactly one of card_ids or note_ids")
    supplied = cast(Sequence[int], card_ids if card_ids is not None else note_ids)
    if not supplied:
        raise ValueError("The supplied ID list must not be empty")
    if len(supplied) > MAX_INSPECT_IDS:
        raise ValueError(f"At most {MAX_INSPECT_IDS} IDs may be supplied")
    if not 1 <= history_limit <= MAX_INSPECT_IDS:
        raise ValueError(f"history_limit must be between 1 and {MAX_INSPECT_IDS}")

    selected = _resolve_properties(properties)
    note_cache: dict[int, Note] = {}
    card_cache: dict[int, Card] = {}
    missing_notes: list[int] = []
    if note_ids is not None:
        resolved_ids = _cards_for_notes(
            wrapper, _unique(note_ids), note_cache, card_cache, missing_notes
        )
    else:
        resolved_ids = _unique(card_ids or [])
    if len(resolved_ids) > MAX_INSPECT_IDS:
        raise ValueError(f"The supplied notes expand to more than {MAX_INSPECT_IDS} cards")

    cards: list[InspectedCard] = []
    missing_cards: list[int] = []
    for card_id in resolved_ids:
        try:
            card = card_cache.get(card_id) or wrapper.col.get_card(CardId(card_id))
        except NotFoundError:
            missing_cards.append(card_id)
            continue
        card_cache[card_id] = card
        cards.append(
            _inspect_card(
                wrapper,
                card,
                selected,
                history_limit=history_limit,
                note_cache=note_cache,
            )
        )
    return InspectCardsResult(
        properties=list(selected),
        cards=cards,
        missing_card_ids=missing_cards,
        missing_note_ids=missing_notes,
    )


def _cards_for_notes(
    wrapper: AnkiWrapper,
    note_ids: Sequence[int],
    note_cache: dict[int, Note],
    card_cache: dict[int, Card],
    missing_notes: list[int],
) -> list[int]:
    card_ids: list[int] = []
    for note_id in note_ids:
        try:
            note_cache[note_id] = wrapper.col.get_note(NoteId(note_id))
        except NotFoundError:
            missing_notes.append(note_id)
            continue
        note_cards = [
            wrapper.col.get_card(card_id)
            for card_id in wrapper.col.card_ids_of_note(NoteId(note_id))
        ]
        note_cards.sort(key=lambda card: card.ord)
        for card in note_cards:
            typed_id = int(card.id)
            if typed_id not in card_cache:
                card_cache[typed_id] = card
                card_ids.append(typed_id)
    return card_ids


def _inspect_card(
    wrapper: AnkiWrapper,
    card: Card,
    properties: Sequence[InspectProperty],
    *,
    history_limit: int,
    note_cache: dict[int, Note],
) -> InspectedCard:
    selected = set(properties)
    stats = (
        wrapper.col.card_stats_data(card.id)
        if selected
        & {
            InspectProperty.SCHEDULING,
            InspectProperty.TIMESTAMPS,
        }
        else None
    )
    note: Note | None = None
    if selected & {InspectProperty.IDENTITY, InspectProperty.FIELDS}:
        note_id = int(card.nid)
        note = note_cache.get(note_id)
        if note is None:
            note = wrapper.col.get_note(card.nid)
            note_cache[note_id] = note

    return InspectedCard(
        card_id=int(card.id),
        identity=_identity(wrapper, card, note) if InspectProperty.IDENTITY in selected else None,
        state=_state(card) if InspectProperty.STATE in selected else None,
        scheduling=(
            _scheduling(card, stats)
            if InspectProperty.SCHEDULING in selected and stats is not None
            else None
        ),
        timestamps=(
            _timestamps(card, stats)
            if InspectProperty.TIMESTAMPS in selected and stats is not None
            else None
        ),
        history=(
            _history(wrapper, card, history_limit) if InspectProperty.HISTORY in selected else None
        ),
        fields=(
            _clean_fields(wrapper, note) if InspectProperty.FIELDS in selected and note else None
        ),
    )


def _identity(wrapper: AnkiWrapper, card: Card, note: Note | None) -> CardIdentity:
    if note is None:
        raise RuntimeError("Card identity requested without its note")
    notetype = wrapper.col.models.get(note.mid)
    model_name = cast(str, notetype.get("name", "")) if notetype is not None else ""
    template_name = ""
    if notetype is not None:
        templates = notetype.get("tmpls", [])
        template_index = card.ord if notetype.get("type") == MODEL_STD else 0
        if template_index < len(templates):
            template_name = cast(str, templates[template_index].get("name", ""))
    return CardIdentity(
        note_id=int(note.id),
        deck=wrapper.col.decks.name(card.did),
        model=model_name,
        template=template_name,
    )


def _state(card: Card) -> CardState:
    queue = int(card.queue)
    return CardState(
        card_type=_CARD_TYPES.get(int(card.type), "unknown"),
        queue=_CARD_QUEUES.get(queue, "unknown"),
        suspended=queue == int(QUEUE_TYPE_SUSPENDED),
        buried=queue in (int(QUEUE_TYPE_MANUALLY_BURIED), int(QUEUE_TYPE_SIBLING_BURIED)),
    )


def _scheduling(card: Card, stats: stats_pb2.CardStatsResponse) -> CardScheduling:
    return CardScheduling(
        due_at=_optional_timestamp(stats, "due_date"),
        due_position=stats.due_position if stats.HasField("due_position") else None,
        interval_days=stats.interval,
        ease_factor=stats.ease / 1000 if stats.ease else None,
        reviews=stats.reviews,
        lapses=stats.lapses,
        remaining_steps=card.left,
        memory=_memory(stats.memory_state) if stats.HasField("memory_state") else None,
        retrievability=(
            stats.fsrs_retrievability if stats.HasField("fsrs_retrievability") else None
        ),
        desired_retention=(
            stats.desired_retention if stats.HasField("desired_retention") else None
        ),
    )


def _timestamps(card: Card, stats: stats_pb2.CardStatsResponse) -> CardTimestamps:
    return CardTimestamps(
        added_at=_timestamp(stats.added),
        modified_at=_timestamp(card.mod),
        first_review_at=_optional_timestamp(stats, "first_review"),
        latest_review_at=_optional_timestamp(stats, "latest_review"),
    )


def _history(wrapper: AnkiWrapper, card: Card, limit: int) -> CardHistory:
    entries = sorted(
        wrapper.col.get_review_logs(card.id), key=lambda entry: entry.time, reverse=True
    )
    return CardHistory(
        total=len(entries),
        entries=[_history_entry(entry) for entry in entries[:limit]],
    )


def _history_entry(
    entry: stats_pb2.CardStatsResponse.StatsRevlogEntry,
) -> ReviewHistoryEntry:
    return ReviewHistoryEntry(
        reviewed_at=_timestamp(entry.time),
        kind=_REVIEW_KINDS.get(entry.review_kind, "unknown"),
        rating=_REVIEW_BUTTONS.get(entry.button_chosen, "unknown"),
        interval_seconds=entry.interval,
        previous_interval_seconds=entry.last_interval,
        elapsed_seconds=entry.taken_secs,
        ease_factor=entry.ease / 1000 if entry.ease else None,
        memory=_memory(entry.memory_state) if entry.HasField("memory_state") else None,
    )


def _memory(memory: object) -> FsrsMemory:
    stability = getattr(memory, "stability", None)
    difficulty = getattr(memory, "difficulty", None)
    if not isinstance(stability, float) or not isinstance(difficulty, float):
        raise TypeError("Invalid FSRS memory state")
    return FsrsMemory(stability=stability, difficulty=difficulty)


def _clean_fields(wrapper: AnkiWrapper, note: Note) -> dict[str, str]:
    return {
        name: cleaned
        for name, value in note.items()
        if (
            cleaned := clean_field_html(
                value,
                media_exists=lambda filename: wrapper.media_path(filename).is_file(),
            )
        )
    }


def _resolve_properties(
    properties: Sequence[InspectProperty] | None,
) -> tuple[InspectProperty, ...]:
    if properties is None:
        return _DEFAULT_PROPERTIES
    if InspectProperty.ALL in properties:
        return _ALL_PROPERTIES
    requested = set(properties)
    return tuple(prop for prop in _ALL_PROPERTIES if prop in requested)


def _unique(values: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(values))


def _timestamp(value: int) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat()


def _optional_timestamp(message: object, field: str) -> str | None:
    has_field = getattr(message, "HasField", None)
    if not callable(has_field) or not has_field(field):
        return None
    value = getattr(message, field, None)
    return _timestamp(value) if isinstance(value, int) else None

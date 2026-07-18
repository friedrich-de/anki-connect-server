from typing import cast
from unittest.mock import patch

import pytest
from anki import cards_pb2, stats_pb2
from anki.cards import Card, CardId
from anki.errors import NotFoundError

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.explore import (
    FsrsMemory,
    InspectProperty,
    NoteFields,
    NotePreview,
    SearchContent,
    inspect_collection_cards,
    search_collection_notes,
)
from anki_connect_server.types import NoteInput


def _add_note(
    wrapper: AnkiWrapper,
    front: str,
    back: str = "answer",
    *,
    model: str = "Basic",
    tags: list[str] | None = None,
) -> tuple[int, list[int]]:
    note_id = wrapper.add_note(
        NoteInput(
            deckName="Default",
            modelName=model,
            fields={"Front": front, "Back": back},
            tags=list(tags or []),
        )
    )
    assert note_id is not None
    return note_id, wrapper.find_cards(f"nid:{note_id}")


def test_search_notes_returns_bounded_clean_previews_and_loads_only_the_page(
    anki_wrapper: AnkiWrapper,
) -> None:
    anki_wrapper.col.media.write_data("present.png", b"png")
    first_id, _ = _add_note(
        anki_wrapper,
        '<div>Hello&nbsp;world<br><img src="present.png"></div>',
        tags=["one"],
    )
    _add_note(anki_wrapper, "second")
    matching_ids = [int(note_id) for note_id in anki_wrapper.col.find_notes("*")]
    expected_id = matching_ids[0]

    with patch.object(
        anki_wrapper.col,
        "get_note",
        wraps=anki_wrapper.col.get_note,
    ) as get_note:
        result = search_collection_notes(anki_wrapper, "*", limit=1)

    assert result.total == 2
    assert result.returned == 1
    assert result.has_more
    assert result.missing_note_ids == []
    assert get_note.call_count == 1
    note = cast(NotePreview, result.notes[0])
    assert note.note_id == expected_id
    if note.note_id == first_id:
        assert note.tags == ["one"]
        assert note.preview == "Hello world\n[image: present.png]"
    else:
        assert note.preview == "second"


def test_search_notes_fields_mode_elides_empty_fields_and_marks_missing_media(
    anki_wrapper: AnkiWrapper,
) -> None:
    note_id, _ = _add_note(
        anki_wrapper,
        '<span>Question</span> <img src="missing.png">',
        "<div>&nbsp;</div>",
    )

    result = search_collection_notes(
        anki_wrapper,
        f"nid:{note_id}",
        content=SearchContent.FIELDS,
    )

    note = cast(NoteFields, result.notes[0])
    assert note.fields == {"Front": "Question [missing image: missing.png]"}
    assert not hasattr(note, "preview")


def test_search_notes_unicode_preview_truncation_and_offset(
    anki_wrapper: AnkiWrapper,
) -> None:
    long_text = "é" * 130
    note_id, _ = _add_note(anki_wrapper, long_text)
    ids = [int(value) for value in anki_wrapper.col.find_notes("*")]
    offset = ids.index(note_id)

    result = search_collection_notes(anki_wrapper, "*", limit=1, offset=offset)

    preview = cast(NotePreview, result.notes[0]).preview
    assert preview == "é" * 120 + "…"
    assert result.offset == offset
    assert not result.has_more


def test_search_notes_reports_notes_removed_after_search(anki_wrapper: AnkiWrapper) -> None:
    missing = NotFoundError("missing", None, None, None)
    with (
        patch.object(anki_wrapper.col, "find_notes", return_value=[123]),
        patch.object(anki_wrapper.col, "get_note", side_effect=missing),
    ):
        result = search_collection_notes(anki_wrapper, "*")

    assert result.returned == 0
    assert result.missing_note_ids == [123]


@pytest.mark.parametrize(
    ("limit", "offset", "message"),
    [(0, 0, "limit"), (101, 0, "limit"), (1, -1, "offset")],
)
def test_search_notes_validates_bounds(
    anki_wrapper: AnkiWrapper,
    limit: int,
    offset: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        search_collection_notes(anki_wrapper, "*", limit=limit, offset=offset)


def test_inspect_cards_default_is_sparse_and_never_renders_or_reads_history(
    anki_wrapper: AnkiWrapper,
) -> None:
    note_id, card_ids = _add_note(anki_wrapper, "question")
    with (
        patch.object(Card, "render_output", autospec=True) as render,
        patch.object(anki_wrapper.col, "get_review_logs", autospec=True) as history,
    ):
        result = inspect_collection_cards(anki_wrapper, card_ids=card_ids)

    card = result.cards[0]
    assert result.properties == [
        InspectProperty.IDENTITY,
        InspectProperty.STATE,
        InspectProperty.SCHEDULING,
    ]
    assert card.card_id == card_ids[0]
    assert card.identity is not None
    assert card.identity.note_id == note_id
    assert card.identity.template == "Card 1"
    assert card.state is not None
    assert card.state.card_type == "new"
    assert card.state.queue == "new"
    assert card.scheduling is not None
    assert card.scheduling.due_position == 1
    assert card.timestamps is None
    assert card.history is None
    assert card.fields is None
    render.assert_not_called()
    history.assert_not_called()


def test_inspect_cards_expands_notes_in_template_order_and_reuses_note_fields(
    anki_wrapper: AnkiWrapper,
) -> None:
    note_id, card_ids = _add_note(
        anki_wrapper,
        "front",
        "back",
        model="Basic (and reversed card)",
    )
    assert len(card_ids) == 2

    with patch.object(
        anki_wrapper.col,
        "get_note",
        wraps=anki_wrapper.col.get_note,
    ) as get_note:
        result = inspect_collection_cards(
            anki_wrapper,
            note_ids=[note_id, note_id],
            properties=[InspectProperty.IDENTITY, InspectProperty.FIELDS],
        )

    assert [card.identity.template for card in result.cards if card.identity] == [
        "Card 1",
        "Card 2",
    ]
    assert [card.card_id for card in result.cards] == card_ids
    assert all(card.fields == {"Front": "front", "Back": "back"} for card in result.cards)
    assert get_note.call_count == 1


def test_inspect_cards_reports_missing_card_and_note_ids(anki_wrapper: AnkiWrapper) -> None:
    note_id, card_ids = _add_note(anki_wrapper, "present")

    cards = inspect_collection_cards(anki_wrapper, card_ids=[card_ids[0], 123, card_ids[0]])
    notes = inspect_collection_cards(anki_wrapper, note_ids=[note_id, 456])

    assert [card.card_id for card in cards.cards] == card_ids
    assert cards.missing_card_ids == [123]
    assert notes.missing_note_ids == [456]


def test_inspect_cards_all_properties_use_public_stats_and_history(
    anki_wrapper: AnkiWrapper,
) -> None:
    _note_id, card_ids = _add_note(anki_wrapper, "question")
    card_id = card_ids[0]
    assert anki_wrapper.answer_cards([{"cardId": card_id, "ease": 3}]) == [True]

    result = inspect_collection_cards(
        anki_wrapper,
        card_ids=[card_id],
        properties=[InspectProperty.ALL],
    )

    card = result.cards[0]
    assert result.properties == [
        InspectProperty.IDENTITY,
        InspectProperty.STATE,
        InspectProperty.SCHEDULING,
        InspectProperty.TIMESTAMPS,
        InspectProperty.HISTORY,
        InspectProperty.FIELDS,
    ]
    assert card.timestamps is not None
    assert card.timestamps.added_at.endswith("+00:00")
    assert card.timestamps.latest_review_at is not None
    assert card.history is not None
    assert card.history.total == 1
    entry = card.history.entries[0]
    assert entry.kind == "learning"
    assert entry.rating == "good"
    assert entry.interval_seconds == 600
    assert entry.reviewed_at.endswith("+00:00")


def test_inspect_cards_returns_fsrs_values_and_bounded_newest_history(
    anki_wrapper: AnkiWrapper,
) -> None:
    _note_id, card_ids = _add_note(anki_wrapper, "question")
    card_id = card_ids[0]
    stats = stats_pb2.CardStatsResponse(
        card_id=card_id,
        note_id=card_id,
        deck="Default",
        added=100,
        interval=7,
        ease=2500,
        reviews=4,
        lapses=1,
        memory_state=cards_pb2.FsrsMemoryState(stability=3.5, difficulty=4.5),
        fsrs_retrievability=0.91,
        desired_retention=0.9,
    )
    history = [
        stats_pb2.CardStatsResponse.StatsRevlogEntry(time=value, button_chosen=value)
        for value in (1, 3, 2)
    ]
    with (
        patch.object(anki_wrapper.col, "card_stats_data", return_value=stats),
        patch.object(anki_wrapper.col, "get_review_logs", return_value=history),
    ):
        result = inspect_collection_cards(
            anki_wrapper,
            card_ids=[card_id],
            properties=[InspectProperty.SCHEDULING, InspectProperty.HISTORY],
            history_limit=2,
        )

    scheduling = result.cards[0].scheduling
    card_history = result.cards[0].history
    assert scheduling is not None
    assert scheduling.ease_factor == 2.5
    assert scheduling.memory == FsrsMemory(stability=3.5, difficulty=4.5)
    assert scheduling.retrievability == pytest.approx(0.91)
    assert scheduling.desired_retention == pytest.approx(0.9)
    assert card_history is not None
    assert card_history.total == 3
    assert [entry.rating for entry in card_history.entries] == ["good", "hard"]


@pytest.mark.parametrize(
    ("card_ids", "note_ids", "history_limit", "message"),
    [
        (None, None, 20, "exactly one"),
        ([1], [2], 20, "exactly one"),
        ([], None, 20, "must not be empty"),
        (list(range(101)), None, 20, "At most 100"),
        ([1], None, 0, "history_limit"),
    ],
)
def test_inspect_cards_validates_inputs(
    anki_wrapper: AnkiWrapper,
    card_ids: list[int] | None,
    note_ids: list[int] | None,
    history_limit: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        inspect_collection_cards(
            anki_wrapper,
            card_ids=card_ids,
            note_ids=note_ids,
            history_limit=history_limit,
        )


def test_inspect_cards_rejects_note_expansion_over_limit(anki_wrapper: AnkiWrapper) -> None:
    note_id, _ = _add_note(anki_wrapper, "question")
    with (
        patch(
            "anki_connect_server.explore._cards_for_notes",
            return_value=list(range(101)),
        ),
        pytest.raises(ValueError, match="more than 100 cards"),
    ):
        inspect_collection_cards(anki_wrapper, note_ids=[note_id])


def test_inspect_cards_names_suspended_state(anki_wrapper: AnkiWrapper) -> None:
    _note_id, card_ids = _add_note(anki_wrapper, "question")
    anki_wrapper.col.sched.suspend_cards([CardId(card_ids[0])])

    result = inspect_collection_cards(
        anki_wrapper,
        card_ids=card_ids,
        properties=[InspectProperty.STATE],
    )

    state = result.cards[0].state
    assert state is not None
    assert state.suspended
    assert not state.buried
    assert state.queue == "suspended"

import pytest
from anki.cards import Card, CardId
from anki.errors import NotFoundError
from anki.notes import NoteId

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.types import NoteInput


def _scheduling_state(card: Card) -> tuple[int, int, int, int, int, int, int]:
    return (
        card.type,
        card.queue,
        card.due,
        card.ivl,
        card.factor,
        card.reps,
        card.lapses,
    )


def _add_reversed_note(wrapper: AnkiWrapper) -> tuple[int, list[int]]:
    note_id = wrapper.add_note(
        NoteInput(
            deckName="Default",
            modelName="Basic (and reversed card)",
            fields={"Front": "original front", "Back": "original back"},
        )
    )
    assert note_id is not None
    cards = sorted(
        (
            wrapper.col.get_card(card_id)
            for card_id in wrapper.col.card_ids_of_note(NoteId(note_id))
        ),
        key=lambda card: card.ord,
    )
    return note_id, [int(card.id) for card in cards]


def test_update_note_fields_is_partial_verbatim_and_preserves_scheduling(
    anki_wrapper: AnkiWrapper,
) -> None:
    note_id, card_ids = _add_reversed_note(anki_wrapper)
    before = {
        card_id: _scheduling_state(anki_wrapper.col.get_card(CardId(card_id)))
        for card_id in card_ids
    }

    affected = anki_wrapper.update_note_fields(
        note_id,
        {"Back": "<b>Grüße &amp; 你好</b>"},
    )

    note = anki_wrapper.col.get_note(NoteId(note_id))
    assert affected == card_ids
    assert note["Front"] == "original front"
    assert note["Back"] == "<b>Grüße &amp; 你好</b>"
    assert "<b>Grüße &amp; 你好</b>" in anki_wrapper.col.get_card(CardId(card_ids[1])).question(
        reload=True
    )
    assert {
        card_id: _scheduling_state(anki_wrapper.col.get_card(CardId(card_id)))
        for card_id in card_ids
    } == before

    assert anki_wrapper.update_note_fields(note_id, {"Front": ""}) == card_ids
    assert anki_wrapper.col.get_note(NoteId(note_id))["Front"] == ""


def test_update_note_fields_rejects_invalid_requests_atomically(
    anki_wrapper: AnkiWrapper,
) -> None:
    note_id, _ = _add_reversed_note(anki_wrapper)
    original = dict(anki_wrapper.col.get_note(NoteId(note_id)).items())

    with pytest.raises(ValueError, match="at least one field"):
        anki_wrapper.update_note_fields(note_id, {})
    with pytest.raises(ValueError, match=f"Unknown fields for note {note_id}: Missing"):
        anki_wrapper.update_note_fields(
            note_id,
            {"Front": "must not persist", "Missing": "invalid"},
        )
    with pytest.raises(NotFoundError):
        anki_wrapper.update_note_fields(999_999_999, {"Front": "missing"})

    assert dict(anki_wrapper.col.get_note(NoteId(note_id)).items()) == original

import json
import time
from pathlib import Path
from typing import cast
from unittest.mock import PropertyMock, patch

import pytest
from anki.cards import CardId
from mcp.types import AudioContent, ImageContent, TextContent

import anki_connect_server.review as review_module
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import Config
from anki_connect_server.review import ReviewCardPayload, ReviewManager, ReviewRating
from anki_connect_server.types import NoteInput


def _add_basic_card(
    wrapper: AnkiWrapper,
    front: str,
    back: str = "Answer",
    *,
    deck: str = "Default",
) -> int:
    note_id = wrapper.add_note(
        NoteInput(
            deckName=deck,
            modelName="Basic",
            fields={"Front": front, "Back": back},
        )
    )
    assert note_id is not None
    return wrapper.find_cards(f"nid:{note_id}")[0]


def _payload(result: object) -> ReviewCardPayload:
    structured = getattr(result, "structured_content", None)
    return ReviewCardPayload.model_validate(structured)


def _revlog_count(wrapper: AnkiWrapper) -> int:
    database = wrapper.col.db
    assert database is not None
    return cast(int, database.scalar("select count() from revlog"))


def test_queue_counts_parent_deck_and_selection_restoration(
    anki_wrapper: AnkiWrapper,
) -> None:
    anki_wrapper.create_deck("Other")
    anki_wrapper.create_deck("Languages::Spanish")
    _add_basic_card(anki_wrapper, "hola", deck="Languages::Spanish")
    other_id = anki_wrapper.col.decks.id_for_name("Other")
    assert other_id is not None
    anki_wrapper.col.decks.select(other_id)

    manager = ReviewManager(anki_wrapper)
    counts = manager.get_queue("Languages")
    result = manager.get_next_card("session", "Languages")
    payload = _payload(result)

    assert counts.model_dump() == {
        "deck": "Languages",
        "new": 1,
        "learning": 0,
        "review": 0,
        "total": 1,
    }
    assert payload.deck == "Languages::Spanish"
    assert payload.queue_kind == "new"
    assert anki_wrapper.col.decks.get_current_id() == other_id


def test_queue_reports_and_orders_new_learning_and_review_cards(
    anki_wrapper: AnkiWrapper,
) -> None:
    _add_basic_card(anki_wrapper, "new")
    learning_id = _add_basic_card(anki_wrapper, "learning")
    review_id = _add_basic_card(anki_wrapper, "review")
    assert anki_wrapper.answer_cards([{"cardId": learning_id, "ease": 1}]) == [True]
    anki_wrapper.col.sched.set_due_date([CardId(review_id)], "0")

    manager = ReviewManager(anki_wrapper)
    counts = manager.get_queue("Default")
    payload = _payload(manager.get_next_card("session", "Default"))

    assert (counts.new, counts.learning, counts.review, counts.total) == (1, 1, 1, 3)
    assert payload.queue_kind == "review"
    assert payload.card_id == review_id


@pytest.mark.parametrize(
    ("rating", "expected_ease"),
    [(ReviewRating.AGAIN, 1), (ReviewRating.GOOD, 3)],
)
def test_submit_uses_scheduler_records_time_and_supports_undo(
    tmp_path: Path,
    rating: ReviewRating,
    expected_ease: int,
) -> None:
    path = tmp_path / "persistent.anki2"
    settings = Config(collection_path=path)
    wrapper = AnkiWrapper(path, settings=settings)
    try:
        card_id = _add_basic_card(wrapper, f"Rate {rating}")
        manager = ReviewManager(wrapper)
        payload = _payload(manager.get_next_card("session", "Default"))
        assert payload.review_id is not None
        time.sleep(0.01)
        result = manager.submit("session", payload.review_id, rating)
        database = wrapper.col.db
        assert database is not None
        revlog = database.first("select ease, time from revlog where cid = ?", card_id)

        assert result.card_id == card_id
        assert result.rating == rating
        assert revlog is not None
        assert revlog[0] == expected_ease
        assert revlog[1] > 0
        assert wrapper.col.get_card(CardId(card_id)).queue == 1
        assert "Answer Card" in str(wrapper.col.undo_status())
    finally:
        wrapper.close()

    reopened = AnkiWrapper(path, settings=settings)
    try:
        assert _revlog_count(reopened) == 1
        assert reopened.col.get_card(CardId(card_id)).queue == 1
    finally:
        reopened.close()


def test_review_ids_are_session_bound_and_idempotent(anki_wrapper: AnkiWrapper) -> None:
    _add_basic_card(anki_wrapper, "Once")
    manager = ReviewManager(anki_wrapper)
    first = _payload(manager.get_next_card("session", "Default"))
    second = _payload(manager.get_next_card("session", "Default"))
    assert first.review_id is not None

    with pytest.raises(ValueError, match="different MCP session"):
        manager.submit("intruder", first.review_id, ReviewRating.GOOD)
    applied = manager.submit("session", first.review_id, ReviewRating.GOOD)
    retried = manager.submit("session", first.review_id, ReviewRating.GOOD)
    with pytest.raises(ValueError, match="different rating"):
        manager.submit("session", first.review_id, ReviewRating.AGAIN)

    assert second.review_id == first.review_id
    assert retried == applied
    assert _revlog_count(anki_wrapper) == 1


def test_review_ids_expire_without_mutation(anki_wrapper: AnkiWrapper) -> None:
    now = [100.0]
    _add_basic_card(anki_wrapper, "Expired")
    manager = ReviewManager(anki_wrapper, ttl_seconds=60, clock=lambda: now[0])
    payload = _payload(manager.get_next_card("session", "Default"))
    assert payload.review_id is not None
    now[0] += 61

    with pytest.raises(ValueError, match="expired"):
        manager.submit("session", payload.review_id, ReviewRating.GOOD)
    assert _revlog_count(anki_wrapper) == 0


def test_review_ids_reject_collection_reopen_and_card_changes(
    anki_wrapper: AnkiWrapper,
) -> None:
    card_id = _add_basic_card(anki_wrapper, "Stale")
    manager = ReviewManager(anki_wrapper)
    reopened = _payload(manager.get_next_card("reopen", "Default"))
    assert reopened.review_id is not None

    with (
        patch.object(
            AnkiWrapper,
            "collection_generation",
            new_callable=PropertyMock,
            return_value=anki_wrapper.collection_generation + 1,
        ),
        pytest.raises(ValueError, match="collection was reopened"),
    ):
        manager.submit("reopen", reopened.review_id, ReviewRating.GOOD)

    changed = _payload(manager.get_next_card("changed", "Default"))
    assert changed.review_id is not None
    anki_wrapper.col.sched.suspend_cards([CardId(card_id)])
    with pytest.raises(ValueError, match="card changed"):
        manager.submit("changed", changed.review_id, ReviewRating.GOOD)
    assert _revlog_count(anki_wrapper) == 0


def test_empty_queue_returns_structured_no_card(anki_wrapper: AnkiWrapper) -> None:
    payload = _payload(ReviewManager(anki_wrapper).get_next_card("session", "Default"))

    assert not payload.has_card
    assert payload.review_id is None
    assert payload.queue.total == 0
    assert payload.message is not None


def test_basic_and_cloze_rendering_is_readable(anki_wrapper: AnkiWrapper) -> None:
    _add_basic_card(anki_wrapper, "<div>First<br>Second</div>", "<b>Answer</b>")
    basic = _payload(ReviewManager(anki_wrapper).get_next_card("basic", "Default"))
    assert basic.question == "First\nSecond"
    assert basic.answer is not None
    assert "Answer" in basic.answer

    note_id = anki_wrapper.add_note(
        NoteInput(
            deckName="Default",
            modelName="Cloze",
            fields={"Text": "The capital is {{c1::Paris}}.", "Back Extra": "France"},
        )
    )
    assert note_id is not None
    cloze_card = anki_wrapper.find_cards(f"nid:{note_id}")[0]
    anki_wrapper.col.sched.set_due_date([CardId(cloze_card)], "0")
    cloze = _payload(ReviewManager(anki_wrapper).get_next_card("cloze", "Default"))
    assert cloze.question is not None
    assert "[...]" in cloze.question
    assert cloze.answer is not None
    assert "Paris" in cloze.answer


def test_media_manifest_and_standard_mcp_content_blocks(anki_wrapper: AnkiWrapper) -> None:
    files = {
        "front.png": b"\x89PNG\r\n",
        "front.jpg": b"\xff\xd8\xff",
        "back.svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>",
        "front.mp3": b"ID3audio",
        "back.wav": b"RIFFaudioWAVE",
        "back.ogg": b"OggSaudio",
    }
    for filename, data in files.items():
        anki_wrapper.col.media.write_data(filename, data)
    front = (
        'Question <img src="front.png"><img src="front.jpg"> '
        "[sound:front.mp3] [anki:tts lang=en_US]spoken[/anki:tts]"
    )
    back = (
        'Answer <img src="back.svg"> [sound:back.wav] [sound:back.ogg] '
        '<img src="https://example.com/remote.png"><img src="missing.png"> '
        '[sound:clip.mp4] [sound:notes.txt] <img src="data:image/png;base64,AAAA"> '
        '<img src="../secret.png">'
    )
    _add_basic_card(anki_wrapper, front, back)

    result = ReviewManager(anki_wrapper).get_next_card("session", "Default")
    payload = _payload(result)
    manifest = {entry.source: entry for entry in payload.media}

    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == result.structured_content
    assert sum(isinstance(block, ImageContent) for block in result.content) == 3
    assert sum(isinstance(block, AudioContent) for block in result.content) == 3
    for entry in payload.media:
        if entry.content_index is not None:
            assert result.content[entry.content_index].type in ("image", "audio")
    assert manifest["front.png"].sides == ["question", "answer"]
    assert manifest["back.svg"].sides == ["answer"]
    assert manifest["https://example.com/remote.png"].kind == "remote"
    assert manifest["missing.png"].kind == "missing"
    assert manifest["clip.mp4"].kind == "video"
    assert manifest["notes.txt"].kind == "unsupported"
    assert manifest["data:image/png;base64,AAAA"].kind == "unsupported"
    assert manifest["../secret.png"].kind == "unsupported"
    assert any(entry.kind == "tts" for entry in payload.media)


def test_media_size_limits_leave_visible_omission_entries(
    anki_wrapper: AnkiWrapper,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(review_module, "MAX_MEDIA_ITEM_BYTES", 5)
    monkeypatch.setattr(review_module, "MAX_MEDIA_TOTAL_BYTES", 8)
    anki_wrapper.col.media.write_data("too-large.png", b"123456")
    anki_wrapper.col.media.write_data("first.png", b"12345")
    anki_wrapper.col.media.write_data("second.png", b"12345")
    _add_basic_card(
        anki_wrapper,
        '<img src="too-large.png"><img src="first.png"><img src="second.png">',
    )

    payload = _payload(ReviewManager(anki_wrapper).get_next_card("session", "Default"))
    manifest = {entry.source: entry for entry in payload.media}

    assert manifest["too-large.png"].kind == "oversized"
    assert manifest["too-large.png"].content_index is None
    assert manifest["first.png"].kind == "image"
    assert manifest["second.png"].kind == "oversized"
    assert "10 MiB" in (manifest["second.png"].omitted_reason or "")

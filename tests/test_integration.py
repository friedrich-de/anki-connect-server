import base64
from pathlib import Path
from typing import cast

import pytest

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import Config
from anki_connect_server.types import (
    CardTemplateInput,
    ModelStylingUpdate,
    ModelTemplateUpdate,
    NoteInput,
)


def _note(front: str, back: str = "Answer", *, deck: str = "Default") -> NoteInput:
    return NoteInput(
        deckName=deck,
        modelName="Basic",
        fields={"Front": front, "Back": back},
    )


def _add_note(wrapper: AnkiWrapper, note: NoteInput) -> int:
    note_id = wrapper.add_note(note)
    assert note_id is not None
    return note_id


def test_deck_and_model_operations(anki_wrapper: AnkiWrapper) -> None:
    deck_id = anki_wrapper.create_deck("Spanish")
    assert anki_wrapper.deck_names_and_ids()["Spanish"] == deck_id

    anki_wrapper.create_model(
        "Vocabulary",
        ["Word", "Meaning"],
        [CardTemplateInput(Name="Card 1", Front="{{Word}}", Back="{{Meaning}}")],
        css=".card { color: navy; }",
    )
    assert anki_wrapper.model_field_names("Vocabulary") == ["Word", "Meaning"]
    assert anki_wrapper.model_styling("Vocabulary") == {"css": ".card { color: navy; }"}


def test_cloze_model_is_created_as_cloze(anki_wrapper: AnkiWrapper) -> None:
    anki_wrapper.create_model(
        "Cloze Test",
        ["Text"],
        [CardTemplateInput(Name="Cloze", Front="{{cloze:Text}}", Back="{{cloze:Text}}")],
        is_cloze=True,
    )
    model = anki_wrapper.col.models.by_name("Cloze Test")
    assert model is not None
    assert cast(int, model["type"]) == 1


def test_template_and_styling_updates_target_the_requested_model(
    anki_wrapper: AnkiWrapper,
) -> None:
    anki_wrapper.create_model(
        "Two Cards",
        ["Front", "Back"],
        [
            CardTemplateInput(Name="First", Front="{{Front}}", Back="{{Back}}"),
            CardTemplateInput(Name="Second", Front="{{Back}}", Back="unchanged"),
        ],
    )
    anki_wrapper.update_model_templates(
        ModelTemplateUpdate(
            name="Two Cards",
            templates={"First": {"Front": "updated {{Front}}", "Back": "answer"}},
        )
    )
    anki_wrapper.update_model_styling(
        ModelStylingUpdate(name="Two Cards", css=".card { color: green; }")
    )

    templates = anki_wrapper.model_templates("Two Cards")
    assert templates["First"] == {"Front": "updated {{Front}}", "Back": "answer"}
    assert templates["Second"] == {"Front": "{{Back}}", "Back": "unchanged"}
    assert anki_wrapper.model_styling("Two Cards") == {"css": ".card { color: green; }"}


def test_deck_configuration_round_trip(anki_wrapper: AnkiWrapper) -> None:
    original = anki_wrapper.get_deck_config("Default")
    original_id = original.get("id")
    assert isinstance(original_id, int)

    clone_id = anki_wrapper.clone_deck_config_id("Cloned Config", original_id)
    assert anki_wrapper.set_deck_config_id(["Default"], clone_id)
    assert anki_wrapper.get_deck_config("Default")["id"] == clone_id

    assert anki_wrapper.set_deck_config_id(["Default"], original_id)
    assert anki_wrapper.remove_deck_config_id(clone_id)


def test_note_card_and_tag_operations(anki_wrapper: AnkiWrapper) -> None:
    note_id = _add_note(anki_wrapper, _note("Question"))
    card_ids = anki_wrapper.find_cards(f"nid:{note_id}")

    anki_wrapper.add_tags([note_id], "one two")
    tags = anki_wrapper.notes_info([note_id])[0]["tags"]
    assert isinstance(tags, list)
    assert {tag for tag in tags if isinstance(tag, str)} == {"one", "two"}
    anki_wrapper.remove_tags([note_id], "one")
    assert anki_wrapper.cards_to_notes(card_ids) == [note_id]
    assert anki_wrapper.cards_info(card_ids)[0]["question"]
    assert anki_wrapper.suspend(card_ids)
    assert anki_wrapper.are_suspended(card_ids) == [True]
    assert anki_wrapper.unsuspend(card_ids)
    assert anki_wrapper.are_suspended(card_ids) == [False]


def test_can_add_notes_does_not_mutate_collection(anki_wrapper: AnkiWrapper) -> None:
    valid = _note("Candidate")
    invalid = NoteInput(deckName="Default", modelName="Missing", fields={"Front": "x"})
    before = anki_wrapper.find_notes("")

    assert anki_wrapper.can_add_notes([valid, invalid]) == [True, False]
    assert anki_wrapper.find_notes("") == before


def test_media_round_trip_and_path_safety(anki_wrapper: AnkiWrapper) -> None:
    encoded = base64.b64encode(b"hello").decode()
    anki_wrapper.store_media_file("hello.txt", encoded)
    assert anki_wrapper.retrieve_media_file("hello.txt") == encoded

    anki_wrapper.delete_media_file("hello.txt")
    assert anki_wrapper.retrieve_media_file("hello.txt") is None
    with pytest.raises(ValueError, match="must not contain a directory"):
        anki_wrapper.retrieve_media_file("../outside.txt")


def test_package_export_and_import(
    anki_wrapper: AnkiWrapper,
    tmp_path: Path,
) -> None:
    _add_note(anki_wrapper, _note("Exported"))
    package_path = tmp_path / "default.apkg"
    anki_wrapper.export_package("Default", str(package_path))
    assert package_path.is_file()

    imported_settings = Config(collection_path=tmp_path / "imported.anki2")
    imported = AnkiWrapper(imported_settings.collection_path, settings=imported_settings)
    try:
        result = imported.import_package(str(package_path))
        assert isinstance(result, dict)
        assert imported.find_notes("Exported")
    finally:
        imported.close()


def test_wrapper_close_is_idempotent(anki_wrapper: AnkiWrapper) -> None:
    anki_wrapper.close()
    anki_wrapper.close()

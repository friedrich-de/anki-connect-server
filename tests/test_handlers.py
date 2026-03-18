"""Tests for API handlers."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from api.handlers import (
    handle_version,
    handle_deck_names,
    handle_deck_names_and_ids,
    handle_create_deck,
    handle_model_names,
    handle_model_field_names,
    handle_add_note,
    handle_find_notes,
    handle_notes_info,
    handle_delete_notes,
    handle_find_cards,
    handle_cards_info,
    handle_suspend,
    handle_unsuspend,
    handle_are_suspended,
    handle_are_due,
    handle_get_intervals,
    handle_get_tags,
    handle_add_tags,
    handle_remove_tags,
    handle_get_media_dir_path,
    handle_store_media_file,
    handle_retrieve_media_file,
    handle_delete_media_file,
    handle_multi,
    dispatch,
    API_VERSION,
)


class TestMiscHandlers:
    """Test miscellaneous handlers."""

    @pytest.mark.asyncio
    async def test_handle_version(self, anki_wrapper):
        """Test version handler."""
        result = await handle_version(anki_wrapper, {})
        assert result == API_VERSION

    @pytest.mark.asyncio
    async def test_handle_deck_names(self, anki_wrapper):
        """Test deckNames handler."""
        anki_wrapper.deck_names.return_value = ["Default", "Spanish"]
        result = await handle_deck_names(anki_wrapper, {})
        assert result == ["Default", "Spanish"]

    @pytest.mark.asyncio
    async def test_handle_deck_names_and_ids(self, anki_wrapper):
        """Test deckNamesAndIds handler."""
        anki_wrapper.deck_names_and_ids.return_value = {"Default": 1, "Spanish": 2}
        result = await handle_deck_names_and_ids(anki_wrapper, {})
        assert result == {"Default": 1, "Spanish": 2}

    @pytest.mark.asyncio
    async def test_handle_create_deck(self, anki_wrapper):
        """Test createDeck handler."""
        anki_wrapper.create_deck.return_value = 12345
        result = await handle_create_deck(anki_wrapper, {"deck": "NewDeck"})
        assert result == 12345
        anki_wrapper.create_deck.assert_called_once_with("NewDeck")

    @pytest.mark.asyncio
    async def test_handle_get_decks(self, anki_wrapper):
        """Test getDecks handler."""
        anki_wrapper.get_decks.return_value = {"Default": [1, 2, 3]}
        from api.handlers import handle_get_decks
        result = await handle_get_decks(anki_wrapper, {"cards": [1, 2, 3]})
        assert result == {"Default": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_handle_delete_decks(self, anki_wrapper):
        """Test deleteDecks handler."""
        from api.handlers import handle_delete_decks
        await handle_delete_decks(anki_wrapper, {"decks": ["Deck1"], "cardsToo": True})
        anki_wrapper.delete_decks.assert_called_once_with(["Deck1"], True)

    @pytest.mark.asyncio
    async def test_handle_change_deck(self, anki_wrapper):
        """Test changeDeck handler."""
        from api.handlers import handle_change_deck
        await handle_change_deck(anki_wrapper, {"cards": [1, 2], "deck": "NewDeck"})
        anki_wrapper.change_deck.assert_called_once_with([1, 2], "NewDeck")


class TestModelHandlers:
    """Test model-related handlers."""

    @pytest.mark.asyncio
    async def test_handle_model_names(self, anki_wrapper):
        """Test modelNames handler."""
        anki_wrapper.model_names.return_value = ["Basic", "Cloze"]
        result = await handle_model_names(anki_wrapper, {})
        assert result == ["Basic", "Cloze"]

    @pytest.mark.asyncio
    async def test_handle_model_field_names(self, anki_wrapper):
        """Test modelFieldNames handler."""
        anki_wrapper.model_field_names.return_value = ["Front", "Back"]
        result = await handle_model_field_names(anki_wrapper, {"modelName": "Basic"})
        assert result == ["Front", "Back"]

    @pytest.mark.asyncio
    async def test_handle_model_fields_on_templates(self, anki_wrapper):
        """Test modelFieldsOnTemplates handler."""
        from api.handlers import handle_model_fields_on_templates
        anki_wrapper.model_fields_on_templates.return_value = {
            "Card 1": [["Front"], ["Back"]]
        }
        result = await handle_model_fields_on_templates(anki_wrapper, {"modelName": "Basic"})
        assert result == {"Card 1": [["Front"], ["Back"]]}

    @pytest.mark.asyncio
    async def test_handle_model_templates(self, anki_wrapper):
        """Test modelTemplates handler."""
        from api.handlers import handle_model_templates
        anki_wrapper.model_templates.return_value = {
            "Card 1": {"Front": "{{Front}}", "Back": "{{Back}}"}
        }
        result = await handle_model_templates(anki_wrapper, {"modelName": "Basic"})
        assert result == {"Card 1": {"Front": "{{Front}}", "Back": "{{Back}}"}}

    @pytest.mark.asyncio
    async def test_handle_model_styling(self, anki_wrapper):
        """Test modelStyling handler."""
        from api.handlers import handle_model_styling
        anki_wrapper.model_styling.return_value = {"css": ".card { font-size: 20px; }"}
        result = await handle_model_styling(anki_wrapper, {"modelName": "Basic"})
        assert result == {"css": ".card { font-size: 20px; }"}


class TestNoteHandlers:
    """Test note-related handlers."""

    @pytest.mark.asyncio
    async def test_handle_add_note(self, anki_wrapper):
        """Test addNote handler."""
        note = {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Hello", "Back": "World"}}
        anki_wrapper.add_note.return_value = 12345
        result = await handle_add_note(anki_wrapper, {"note": note})
        assert result == 12345

    @pytest.mark.asyncio
    async def test_handle_add_note_invalid(self, anki_wrapper):
        """Test addNote handler with invalid note."""
        anki_wrapper.add_note.return_value = None
        result = await handle_add_note(anki_wrapper, {"note": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_add_notes(self, anki_wrapper):
        """Test addNotes handler."""
        notes = [
            {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Hello"}},
            {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "World"}}
        ]
        anki_wrapper.add_notes.return_value = [123, 456]
        from api.handlers import handle_add_notes
        result = await handle_add_notes(anki_wrapper, {"notes": notes})
        assert result == [123, 456]

    @pytest.mark.asyncio
    async def test_handle_can_add_notes(self, anki_wrapper):
        """Test canAddNotes handler."""
        from api.handlers import handle_can_add_notes
        notes = [{"deckName": "Default", "modelName": "Basic", "fields": {"Front": "Hello"}}]
        anki_wrapper.can_add_notes.return_value = [True]
        result = await handle_can_add_notes(anki_wrapper, {"notes": notes})
        assert result == [True]

    @pytest.mark.asyncio
    async def test_handle_update_note_fields(self, anki_wrapper):
        """Test updateNoteFields handler."""
        from api.handlers import handle_update_note_fields
        note = {"id": 123, "fields": {"Front": "New Front"}}
        await handle_update_note_fields(anki_wrapper, {"note": note})
        anki_wrapper.update_note_fields.assert_called_once_with(note)

    @pytest.mark.asyncio
    async def test_handle_find_notes(self, anki_wrapper):
        """Test findNotes handler."""
        anki_wrapper.find_notes.return_value = [1, 2, 3, 4, 5]
        result = await handle_find_notes(anki_wrapper, {"query": "deck:Default"})
        assert result == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_handle_notes_info(self, anki_wrapper):
        """Test notesInfo handler."""
        notes_info = [{"noteId": 123, "modelName": "Basic", "tags": ["test"]}]
        anki_wrapper.notes_info.return_value = notes_info
        result = await handle_notes_info(anki_wrapper, {"notes": [123]})
        assert result == notes_info

    @pytest.mark.asyncio
    async def test_handle_delete_notes(self, anki_wrapper):
        """Test deleteNotes handler."""
        await handle_delete_notes(anki_wrapper, {"notes": [1, 2, 3]})
        anki_wrapper.delete_notes.assert_called_once_with([1, 2, 3])


class TestCardHandlers:
    """Test card-related handlers."""

    @pytest.mark.asyncio
    async def test_handle_find_cards(self, anki_wrapper):
        """Test findCards handler."""
        anki_wrapper.find_cards.return_value = [1, 2, 3]
        result = await handle_find_cards(anki_wrapper, {"query": "deck:Default"})
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_handle_cards_to_notes(self, anki_wrapper):
        """Test cardsToNotes handler."""
        from api.handlers import handle_cards_to_notes
        anki_wrapper.cards_to_notes.return_value = [1, 2]
        result = await handle_cards_to_notes(anki_wrapper, {"cards": [1, 2, 3]})
        assert result == [1, 2]

    @pytest.mark.asyncio
    async def test_handle_cards_info(self, anki_wrapper):
        """Test cardsInfo handler."""
        anki_wrapper.cards_info.return_value = [{"cardId": 1, "interval": 10}]
        result = await handle_cards_info(anki_wrapper, {"cards": [1]})
        assert result == [{"cardId": 1, "interval": 10}]

    @pytest.mark.asyncio
    async def test_handle_suspend(self, anki_wrapper):
        """Test suspend handler."""
        anki_wrapper.suspend.return_value = True
        result = await handle_suspend(anki_wrapper, {"cards": [1, 2, 3]})
        assert result is True
        anki_wrapper.suspend.assert_called_once_with([1, 2, 3])

    @pytest.mark.asyncio
    async def test_handle_unsuspend(self, anki_wrapper):
        """Test unsuspend handler."""
        anki_wrapper.unsuspend.return_value = True
        result = await handle_unsuspend(anki_wrapper, {"cards": [1, 2, 3]})
        assert result is True

    @pytest.mark.asyncio
    async def test_handle_are_suspended(self, anki_wrapper):
        """Test areSuspended handler."""
        anki_wrapper.are_suspended.return_value = [True, False]
        result = await handle_are_suspended(anki_wrapper, {"cards": [1, 2]})
        assert result == [True, False]

    @pytest.mark.asyncio
    async def test_handle_are_due(self, anki_wrapper):
        """Test areDue handler."""
        anki_wrapper.are_due.return_value = [True, False]
        result = await handle_are_due(anki_wrapper, {"cards": [1, 2]})
        assert result == [True, False]

    @pytest.mark.asyncio
    async def test_handle_get_intervals(self, anki_wrapper):
        """Test getIntervals handler."""
        anki_wrapper.get_intervals.return_value = [10, 20]
        result = await handle_get_intervals(anki_wrapper, {"cards": [1, 2], "complete": False})
        assert result == [10, 20]


class TestTagHandlers:
    """Test tag-related handlers."""

    @pytest.mark.asyncio
    async def test_handle_get_tags(self, anki_wrapper):
        """Test getTags handler."""
        anki_wrapper.get_tags.return_value = ["tag1", "tag2", "tag3"]
        result = await handle_get_tags(anki_wrapper, {})
        assert result == ["tag1", "tag2", "tag3"]

    @pytest.mark.asyncio
    async def test_handle_add_tags(self, anki_wrapper):
        """Test addTags handler."""
        await handle_add_tags(anki_wrapper, {"notes": [1, 2], "tags": "new_tag"})
        anki_wrapper.add_tags.assert_called_once_with([1, 2], "new_tag")

    @pytest.mark.asyncio
    async def test_handle_remove_tags(self, anki_wrapper):
        """Test removeTags handler."""
        await handle_remove_tags(anki_wrapper, {"notes": [1, 2], "tags": "old_tag"})
        anki_wrapper.remove_tags.assert_called_once_with([1, 2], "old_tag")


class TestMediaHandlers:
    """Test media-related handlers."""

    @pytest.mark.asyncio
    async def test_handle_get_media_dir_path(self, anki_wrapper):
        """Test getMediaDirPath handler."""
        anki_wrapper.get_media_dir_path.return_value = "/path/to/media"
        result = await handle_get_media_dir_path(anki_wrapper, {})
        assert result == "/path/to/media"

    @pytest.mark.asyncio
    async def test_handle_store_media_file(self, anki_wrapper):
        """Test storeMediaFile handler."""
        await handle_store_media_file(anki_wrapper, {"filename": "test.txt", "data": "SGVsbG8="})
        anki_wrapper.store_media_file.assert_called_once_with("test.txt", "SGVsbG8=")

    @pytest.mark.asyncio
    async def test_handle_retrieve_media_file(self, anki_wrapper):
        """Test retrieveMediaFile handler."""
        anki_wrapper.retrieve_media_file.return_value = "SGVsbG8="
        result = await handle_retrieve_media_file(anki_wrapper, {"filename": "test.txt"})
        assert result == "SGVsbG8="

    @pytest.mark.asyncio
    async def test_handle_delete_media_file(self, anki_wrapper):
        """Test deleteMediaFile handler."""
        await handle_delete_media_file(anki_wrapper, {"filename": "test.txt"})
        anki_wrapper.delete_media_file.assert_called_once_with("test.txt")


class TestMultiHandler:
    """Test multi-action handler."""

    @pytest.mark.asyncio
    async def test_handle_multi(self, anki_wrapper):
        """Test multi handler."""
        anki_wrapper.deck_names.return_value = ["Default"]
        anki_wrapper.model_names.return_value = ["Basic"]
        
        actions = [
            {"action": "deckNames", "params": {}},
            {"action": "modelNames", "params": {}}
        ]
        
        result = await handle_multi(anki_wrapper, {"actions": actions})
        assert result == [["Default"], ["Basic"]]

    @pytest.mark.asyncio
    async def test_handle_multi_with_invalid_action(self, anki_wrapper):
        """Test multi handler with invalid action."""
        actions = [{"action": "invalidAction", "params": {}}]
        result = await handle_multi(anki_wrapper, {"actions": actions})
        assert "error" in str(result[0])


class TestDispatch:
    """Test dispatch function."""

    @pytest.mark.asyncio
    async def test_dispatch_unknown_action(self, anki_wrapper):
        """Test dispatch with unknown action."""
        with pytest.raises(ValueError, match="Unsupported action"):
            await dispatch("unknownAction", {}, anki_wrapper)

    @pytest.mark.asyncio
    async def test_dispatch_valid_action(self, anki_wrapper):
        """Test dispatch with valid action."""
        anki_wrapper.deck_names.return_value = ["Default"]
        result = await dispatch("deckNames", {}, anki_wrapper)
        assert result == ["Default"]
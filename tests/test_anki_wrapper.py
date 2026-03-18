"""Tests for anki_wrapper module."""

import pytest
from unittest.mock import MagicMock, patch
from anki.notes import Note
from anki.decks import DeckId
from anki.cards import CardId


class TestAnkiWrapper:
    """Test AnkiWrapper class."""

    def test_deck_names(self, anki_wrapper):
        """Test getting deck names."""
        anki_wrapper.col.decks.all_names.return_value = ["Default", "Spanish", "Japanese"]
        result = anki_wrapper.deck_names()
        assert result == ["Default", "Spanish", "Japanese"]
        anki_wrapper.col.decks.all_names.assert_called_once()

    def test_deck_names_and_ids(self, anki_wrapper):
        """Test getting deck names and IDs."""
        anki_wrapper.col.decks.all_names_and_ids.return_value = {
            1: "Default",
            2: "Spanish",
            3: "Japanese"
        }
        result = anki_wrapper.deck_names_and_ids()
        assert result == {"Default": 1, "Spanish": 2, "Japanese": 3}

    def test_create_deck(self, anki_wrapper):
        """Test creating a deck."""
        anki_wrapper.col.decks.id.return_value = 12345
        result = anki_wrapper.create_deck("NewDeck")
        assert result == 12345
        anki_wrapper.col.decks.id.assert_called_once_with("NewDeck")

    def test_delete_decks(self, anki_wrapper):
        """Test deleting decks."""
        anki_wrapper.col.decks.id.side_effect = [1, 2, 3]
        anki_wrapper.delete_decks(["Deck1", "Deck2", "Deck3"], cards_too=True)
        assert anki_wrapper.col.decks.delete_given_decks.call_count == 1

    def test_change_deck(self, anki_wrapper):
        """Test changing deck of cards."""
        anki_wrapper.col.decks.id.return_value = 123
        anki_wrapper.change_deck([1, 2, 3], "NewDeck")
        anki_wrapper.col.decks.change_deck.assert_called_once()

    def test_model_names(self, anki_wrapper):
        """Test getting model names."""
        anki_wrapper.col.models.all_names.return_value = ["Basic", "Basic (Reversed)", "Cloze"]
        result = anki_wrapper.model_names()
        assert result == ["Basic", "Basic (Reversed)", "Cloze"]

    def test_model_names_and_ids(self, anki_wrapper):
        """Test getting model names and IDs."""
        anki_wrapper.col.models.all_names_and_ids.return_value = {
            1: "Basic",
            2: "Cloze"
        }
        result = anki_wrapper.model_names_and_ids()
        assert result == {"Basic": 1, "Cloze": 2}

    def test_model_field_names(self, anki_wrapper):
        """Test getting field names for a model."""
        mock_model = {
            "fields": {
                "Front": {},
                "Back": {}
            }
        }
        anki_wrapper.col.models.get.return_value = mock_model
        result = anki_wrapper.model_field_names("Basic")
        assert result == ["Front", "Back"]

    def test_model_field_names_invalid_model(self, anki_wrapper):
        """Test getting field names for invalid model."""
        anki_wrapper.col.models.get.return_value = None
        result = anki_wrapper.model_field_names("InvalidModel")
        assert result == []

    def test_add_note(self, anki_wrapper, sample_note):
        """Test adding a note."""
        mock_note = MagicMock()
        mock_note.id = 12345
        anki_wrapper.col.models.get.return_value = {"name": "Basic"}
        anki_wrapper.col.decks.id.return_value = 1
        with patch.object(Note, "__init__", return_value=None):
            with patch.object(Note, "_to_backend_note", return_value=MagicMock()):
                anki_wrapper.col.add_note = MagicMock(return_value=MagicMock(changes=MagicMock(note_id=12345)))
                result = anki_wrapper.add_note(sample_note)
                assert result == 12345

    def test_add_note_invalid_model(self, anki_wrapper, sample_note):
        """Test adding a note with invalid model."""
        anki_wrapper.col.models.get.return_value = None
        result = anki_wrapper.add_note(sample_note)
        assert result is None

    def test_find_notes(self, anki_wrapper):
        """Test finding notes."""
        anki_wrapper.col.find_notes.return_value = [1, 2, 3, 4, 5]
        result = anki_wrapper.find_notes("deck:Default")
        assert result == [1, 2, 3, 4, 5]
        anki_wrapper.col.find_notes.assert_called_once_with("deck:Default")

    def test_find_cards(self, anki_wrapper):
        """Test finding cards."""
        anki_wrapper.col.find_cards.return_value = [1, 2, 3]
        result = anki_wrapper.find_cards("deck:Default")
        assert result == [1, 2, 3]

    def test_cards_to_notes(self, anki_wrapper):
        """Test converting cards to notes."""
        anki_wrapper.col.cards_to_notes.return_value = iter([1, 2, 3])
        result = anki_wrapper.cards_to_notes([1, 2, 3])
        assert set(result) == {1, 2, 3}

    def test_notes_info(self, anki_wrapper):
        """Test getting notes info."""
        mock_note = MagicMock()
        mock_note.id = 123
        mock_note.mid = 1
        mock_note.tags = ["tag1", "tag2"]
        mock_note.__getitem__ = lambda self, key: {"Front": "hello", "Back": "world"}.get(key, "")
        mock_note.__iter__ = lambda self: iter(["Front", "Back"])
        
        mock_model = {"name": "Basic"}
        
        def get_note_side_effect(note_id):
            if note_id == 123:
                return mock_note
            return None
        
        anki_wrapper.col.get_note.side_effect = get_note_side_effect
        anki_wrapper.col.models.get.return_value = mock_model
        
        result = anki_wrapper.notes_info([123])
        assert len(result) == 1
        assert result[0]["noteId"] == 123

    def test_delete_notes(self, anki_wrapper):
        """Test deleting notes."""
        anki_wrapper.delete_notes([1, 2, 3])
        anki_wrapper.col.remove_notes.assert_called_once()

    def test_suspend_cards(self, anki_wrapper):
        """Test suspending cards."""
        mock_result = MagicMock()
        mock_result.count = 1
        anki_wrapper.col.sched.suspend_cards.return_value = mock_result
        result = anki_wrapper.suspend([1, 2, 3])
        assert result is True

    def test_unsuspend_cards(self, anki_wrapper):
        """Test unsuspending cards."""
        mock_result = MagicMock()
        mock_result.count = 1
        anki_wrapper.col.sched.unsuspend_cards.return_value = mock_result
        result = anki_wrapper.unsuspend([1, 2, 3])
        assert result is True

    def test_are_suspended(self, anki_wrapper):
        """Test checking if cards are suspended."""
        mock_card = MagicMock()
        mock_card.queue = -1
        anki_wrapper.col.get_card.return_value = mock_card
        result = anki_wrapper.are_suspended([1])
        assert result == [True]

    def test_are_due(self, anki_wrapper):
        """Test checking if cards are due."""
        mock_card = MagicMock()
        mock_card.due = 0
        anki_wrapper.col.get_card.return_value = mock_card
        result = anki_wrapper.are_due([1])
        assert result == [True]

    def test_get_intervals(self, anki_wrapper):
        """Test getting card intervals."""
        mock_card = MagicMock()
        mock_card.ivl = 10
        anki_wrapper.col.get_card.return_value = mock_card
        result = anki_wrapper.get_intervals([1], complete=False)
        assert result == [10]

    def test_get_media_dir_path(self, anki_wrapper):
        """Test getting media directory path."""
        anki_wrapper.col.media.dir.return_value = "/path/to/media"
        result = anki_wrapper.get_media_dir_path()
        assert result == "/path/to/media"

    def test_store_and_retrieve_media_file(self, anki_wrapper):
        """Test storing and retrieving media files."""
        import base64
        test_data = "SGVsbG8gV29ybGQh"  # "Hello World!" in base64
        anki_wrapper.store_media_file("test.txt", test_data)
        anki_wrapper.col.media.write_data.assert_called_once()
        
        anki_wrapper.col.media.read_data.return_value = b"Hello World!"
        result = anki_wrapper.retrieve_media_file("test.txt")
        assert result == test_data

    def test_delete_media_file(self, anki_wrapper):
        """Test deleting media file."""
        anki_wrapper.delete_media_file("test.txt")
        anki_wrapper.col.media.delete_file.assert_called_once_with("test.txt")

    def test_get_tags(self, anki_wrapper):
        """Test getting all tags."""
        anki_wrapper.col.tags.all.return_value = ["tag1", "tag2", "tag3"]
        result = anki_wrapper.get_tags()
        assert result == ["tag1", "tag2", "tag3"]

    def test_add_tags(self, anki_wrapper):
        """Test adding tags to notes."""
        anki_wrapper.add_tags([1, 2, 3], "new_tag")
        anki_wrapper.col.tags.add_tags.assert_called_once()

    def test_remove_tags(self, anki_wrapper):
        """Test removing tags from notes."""
        anki_wrapper.remove_tags([1, 2, 3], "old_tag")
        anki_wrapper.col.tags.remove_tags.assert_called_once()


class TestSyncToAnkiWeb:
    """Test sync functionality."""

    def test_sync_requires_credentials(self, anki_wrapper):
        """Test that sync raises error without credentials."""
        from config import Config
        with patch.object(Config, "ANKIWEB_USER", None):
            with patch.object(Config, "ANKIWEB_PASS", None):
                with pytest.raises(ValueError, match="ANKICONNECT_ANKIWEB_USER"):
                    anki_wrapper.sync_to_ankiweb()

    def test_sync_success(self, anki_wrapper):
        """Test successful sync."""
        from config import Config
        mock_auth = MagicMock()
        mock_result = MagicMock()
        
        with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
            with patch.object(Config, "ANKIWEB_PASS", "password"):
                with patch.object(Config, "ANKIWEB_URL", None):
                    anki_wrapper.col.sync_login.return_value = mock_auth
                    anki_wrapper.col.sync_collection.return_value = mock_result
                    
                    result = anki_wrapper.sync_to_ankiweb()
                    
                    anki_wrapper.col.sync_login.assert_called_once()
                    anki_wrapper.col.sync_collection.assert_called_once()

    def test_sync_custom_endpoint(self, anki_wrapper):
        """Test sync with custom endpoint."""
        from config import Config
        mock_auth = MagicMock()
        
        with patch.object(Config, "ANKIWEB_USER", "test@example.com"):
            with patch.object(Config, "ANKIWEB_PASS", "password"):
                with patch.object(Config, "ANKIWEB_URL", "https://sync.myserver.com"):
                    anki_wrapper.col.sync_login.return_value = mock_auth
                    anki_wrapper.col.sync_collection.return_value = MagicMock()
                    
                    anki_wrapper.sync_to_ankiweb()
                    
                    anki_wrapper.col.sync_login.assert_called_once_with(
                        username="test@example.com",
                        password="password",
                        endpoint="https://sync.myserver.com"
                    )
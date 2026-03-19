"""Integration tests using real AnkiWrapper."""

import os
import tempfile
import pytest


@pytest.fixture
def temp_collection():
    """Create a temporary collection for testing."""
    os.environ["ANKICONNECT_COLLECTION_PATH"] = "/tmp/test_collection.anki21"
    
    with tempfile.NamedTemporaryFile(suffix=".anki21", delete=False) as f:
        collection_path = f.name
    
    from anki_wrapper import AnkiWrapper
    wrapper = AnkiWrapper(collection_path)
    
    yield wrapper
    
    wrapper.close()
    if os.path.exists(collection_path):
        os.remove(collection_path)


class TestAnkiWrapperIntegration:
    """Integration tests for AnkiWrapper."""

    def test_create_and_list_decks(self, temp_collection):
        """Test creating and listing decks."""
        deck_id = temp_collection.create_deck("TestDeck")
        assert deck_id > 0
        
        decks = temp_collection.deck_names()
        assert "TestDeck" in decks

    def test_create_multiple_decks(self, temp_collection):
        """Test creating multiple decks."""
        temp_collection.create_deck("Deck1")
        temp_collection.create_deck("Deck2")
        
        decks = temp_collection.deck_names()
        assert "Deck1" in decks
        assert "Deck2" in decks

    def test_deck_names_and_ids(self, temp_collection):
        """Test getting deck names and IDs."""
        deck_id = temp_collection.create_deck("IDTestDeck")
        
        decks = temp_collection.deck_names_and_ids()
        assert "IDTestDeck" in decks
        assert decks["IDTestDeck"] == deck_id

    def test_delete_deck(self, temp_collection):
        """Test deleting a deck."""
        temp_collection.create_deck("ToDelete")
        temp_collection.delete_decks(["ToDelete"])
        
        decks = temp_collection.deck_names()
        assert "ToDelete" not in decks

    def test_list_models(self, temp_collection):
        """Test listing note models."""
        models = temp_collection.model_names()
        assert "Basic" in models

    def test_model_field_names(self, temp_collection):
        """Test getting field names for a model."""
        fields = temp_collection.model_field_names("Basic")
        assert "Front" in fields
        assert "Back" in fields

    def test_get_media_dir_path(self, temp_collection):
        """Test getting media directory path."""
        media_path = temp_collection.get_media_dir_path()
        assert media_path is not None
        assert len(media_path) > 0

    def test_get_api_version(self):
        """Test API version constant."""
        from api.handlers import API_VERSION
        assert API_VERSION == 6
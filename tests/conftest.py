import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

os.environ["ANKI_COLLECTION_PATH"] = "/tmp/test_collection.anki21"


@pytest.fixture
def mock_collection():
    """Create a mock Anki collection."""
    with patch("anki_wrapper.Collection") as mock_col:
        mock_instance = MagicMock()
        mock_col.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def anki_wrapper(mock_collection):
    """Create AnkiWrapper with mocked collection."""
    from anki_wrapper import AnkiWrapper
    with patch("anki_wrapper.Collection"):
        wrapper = AnkiWrapper("/tmp/test.anki21")
        wrapper.col = mock_collection
        return wrapper


@pytest.fixture
def temp_collection_path():
    """Create a temporary collection file path."""
    with tempfile.NamedTemporaryFile(suffix=".anki21", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def sample_note():
    """Sample note data for testing."""
    return {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {
            "Front": "Hello",
            "Back": "World"
        },
        "tags": ["test", "api"]
    }


@pytest.fixture
def sample_deck_config():
    """Sample deck configuration for testing."""
    return {
        "id": 1,
        "name": "Default",
        "new": {
            "perDay": 20,
            "delays": [1, 10]
        },
        "rev": {
            "perDay": 100
        }
    }
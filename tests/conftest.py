from collections.abc import Iterator
from pathlib import Path

import pytest

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import Config


@pytest.fixture(autouse=True)
def isolate_test_working_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Prevent repository credentials in .env from leaking into tests."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def settings(tmp_path: Path) -> Config:
    return Config(collection_path=tmp_path / "test.anki2")


@pytest.fixture
def anki_wrapper(settings: Config) -> Iterator[AnkiWrapper]:
    wrapper = AnkiWrapper(settings.collection_path, settings=settings)
    try:
        yield wrapper
    finally:
        wrapper.close()

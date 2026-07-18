from pathlib import Path

import pytest

from anki_connect_server.config import Config, get_config


def test_config_defaults(tmp_path: Path) -> None:
    config = Config(collection_path=tmp_path / "collection.anki2")

    assert config.port == 8765
    assert config.bind == "127.0.0.1"
    assert config.ankiweb_user is None


def test_config_custom_values(tmp_path: Path) -> None:
    config = Config(
        collection_path=tmp_path / "collection.anki2",
        port=9000,
        bind="192.0.2.1",
        ankiweb_user="user@example.com",
        ankiweb_pass="secret",
    )

    assert config.port == 9000
    assert config.bind == "192.0.2.1"
    assert config.ankiweb_user == "user@example.com"
    assert "secret" not in repr(config)


def test_removed_full_upload_environment_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ANKICONNECT_FULL_UPLOAD", "true")

    config = Config(collection_path=tmp_path / "collection.anki2")

    assert config.collection_path == tmp_path / "collection.anki2"
    assert "full_upload" not in Config.model_fields


def test_collection_path_from_canonical_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    collection_path = tmp_path / "environment.anki2"
    monkeypatch.delenv("ANKICONNECT_COLLECTION_PATH", raising=False)
    monkeypatch.setenv("ANKICONNECT_COLLECTION_PATH", str(collection_path))

    assert Config().collection_path == collection_path


def test_legacy_collection_path_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANKICONNECT_COLLECTION_PATH", raising=False)
    monkeypatch.setenv("ANKI_COLLECTION_PATH", str(tmp_path / "legacy.anki2"))

    with pytest.raises(ValueError, match="ANKICONNECT_COLLECTION_PATH is required"):
        Config()


def test_collection_path_is_required(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANKICONNECT_COLLECTION_PATH", raising=False)

    with pytest.raises(ValueError, match="ANKICONNECT_COLLECTION_PATH is required"):
        Config()


def test_collection_path_requires_anki2_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"\.anki2 extension"):
        Config(collection_path=tmp_path / "collection.anki21")


def test_get_config_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ANKICONNECT_COLLECTION_PATH", str(tmp_path / "cached.anki2"))
    get_config.cache_clear()
    try:
        assert get_config() is get_config()
    finally:
        get_config.cache_clear()

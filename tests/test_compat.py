"""AnkiConnect compatibility over HTTP, as Yomitan and the Subtitle Miner use it."""

import asyncio
import base64
import hashlib
from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.api import create_app
from anki_connect_server.config import Config
from anki_connect_server.handlers import API_KEY_ERROR
from anki_connect_server.notes import DUPLICATE_ERROR, EMPTY_ERROR
from anki_connect_server.types import JsonObject, JsonValue

KEY = "test-key-0123456789"
PNG = base64.b64encode(b"\x89PNG fake picture").decode()
MP3 = base64.b64encode(b"ID3 fake audio").decode()


@pytest.fixture
def keyed_settings(tmp_path: Path) -> Config:
    return Config(
        collection_path=tmp_path / "keyed.anki2",
        api_key=SecretStr(KEY),
        max_request_bytes=2 * 1024 * 1024,
        busy_timeout=0.2,
    )


@pytest.fixture
def keyed_wrapper(keyed_settings: Config) -> Iterator[AnkiWrapper]:
    wrapper = AnkiWrapper(keyed_settings.collection_path, settings=keyed_settings)
    try:
        yield wrapper
    finally:
        wrapper.close()


@asynccontextmanager
async def _client(wrapper: AnkiWrapper) -> AsyncGenerator[AsyncClient]:
    application = create_app(lambda: wrapper, wrapper.settings, close_wrapper=False)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client,
    ):
        yield client


async def _call(
    client: AsyncClient,
    action: str,
    version: object = 6,
    key: object = KEY,
    **params: object,
) -> JsonValue:
    body: dict[str, object] = {"action": action, "params": params}
    if version is not None:
        body["version"] = version
    if key is not None:
        body["key"] = key
    response = await client.post("/", json=body)
    assert response.status_code == 200
    return cast(JsonValue, response.json())


async def _result(client: AsyncClient, action: str, **params: object) -> JsonValue:
    reply = cast(JsonObject, await _call(client, action, **params))
    assert reply["error"] is None, reply
    return reply["result"]


async def _error(client: AsyncClient, action: str, **params: object) -> str:
    reply = cast(JsonObject, await _call(client, action, **params))
    assert reply["result"] is None
    return cast(str, reply["error"])


def _basic(front: str, back: str = "", **extra: JsonValue) -> JsonObject:
    note: JsonObject = {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {"Front": front, "Back": back},
    }
    note.update(extra)
    return note


# Authentication


@pytest.mark.asyncio
async def test_api_key_is_required_in_body_or_bearer_header(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        assert await _call(client, "deckNames", key=None) == {
            "result": None,
            "error": API_KEY_ERROR,
        }
        assert await _call(client, "deckNames", key="wrong") == {
            "result": None,
            "error": API_KEY_ERROR,
        }
        assert await _call(client, "version", key=None) == {
            "result": None,
            "error": API_KEY_ERROR,
        }
        assert await _result(client, "deckNames") == ["Default"]
        bearer = await client.post(
            "/",
            json={"action": "deckNames", "version": 6},
            headers={"Authorization": f"Bearer {KEY}"},
        )
        assert bearer.json() == {"result": ["Default"], "error": None}


@pytest.mark.asyncio
async def test_request_permission_needs_no_key_and_reports_it(
    keyed_wrapper: AnkiWrapper, anki_wrapper: AnkiWrapper
) -> None:
    async with _client(keyed_wrapper) as client:
        assert await _call(client, "requestPermission", key=None) == {
            "result": {"permission": "granted", "requireApikey": True, "version": 6},
            "error": None,
        }
    async with _client(anki_wrapper) as client:
        assert await _call(client, "requestPermission", key=None) == {
            "result": {"permission": "granted", "requireApikey": False, "version": 6},
            "error": None,
        }


# Protocol


@pytest.mark.asyncio
async def test_reply_shape_follows_the_request_version(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        assert await _call(client, "deckNames", version=None) == ["Default"]
        assert await _call(client, "deckNames", version=2) == ["Default"]
        assert await _call(client, "createDeck", version=4, deck="Mining") is not None
        assert await _call(client, "deckNames", version="6") == {
            "result": ["Default", "Mining"],
            "error": None,
        }
        assert await _call(client, "notAnAction", version=2) == {
            "result": None,
            "error": "unsupported action",
        }
        assert await _call(client, "addNote", version=2, note=_basic("")) == {
            "result": None,
            "error": EMPTY_ERROR,
        }


@pytest.mark.asyncio
async def test_multi_keeps_each_items_version_and_error(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        actions: list[JsonValue] = [
            {"action": "deckNames"},
            {"action": "deckNames", "version": 6},
            {"action": "modelFieldNames", "version": 6, "params": {"modelName": "Basic"}},
            {"action": "missing", "version": 6},
            {"action": "addNote", "params": {"note": _basic("")}},
        ]
        assert await _result(client, "multi", actions=actions) == [
            ["Default"],
            {"result": ["Default"], "error": None},
            {"result": ["Front", "Back"], "error": None},
            {"result": None, "error": "unsupported action"},
            {"result": None, "error": EMPTY_ERROR},
        ]


@pytest.mark.asyncio
async def test_bodies_parse_whatever_the_content_type(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        response = await client.post(
            "/",
            content=f'{{"action":"deckNames","version":6,"key":"{KEY}"}}',
            headers={"Content-Type": "text/plain;charset=UTF-8"},
        )
        banner = await client.get("/")
        not_object = await client.post("/", content="[1]")
    assert response.json() == {"result": ["Default"], "error": None}
    assert banner.text == "AnkiConnect v.6"
    assert not_object.json() == {"result": None, "error": "request must be a JSON object"}


@pytest.mark.asyncio
async def test_oversized_requests_are_refused(keyed_wrapper: AnkiWrapper) -> None:
    big = base64.b64encode(b"x" * (3 * 1024 * 1024)).decode()
    async with _client(keyed_wrapper) as client:
        response = await client.post(
            "/",
            json={"action": "storeMediaFile", "key": KEY, "params": {"filename": "a", "data": big}},
        )
    assert response.status_code == 413
    assert response.json() == {"result": None, "error": "request body is too large"}
    assert not (Path(keyed_wrapper.col.media.dir()) / "a").exists()


def _preflight(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }


@pytest.mark.asyncio
async def test_cors_allows_extensions_and_configured_origins_only(
    keyed_wrapper: AnkiWrapper,
) -> None:
    keyed_wrapper.settings.cors_origins = ["https://jellyfin.example"]
    async with _client(keyed_wrapper) as client:
        extension = await client.options("/", headers=_preflight("moz-extension://4b1d-a2c3"))
        configured = await client.post(
            "/",
            json={"action": "deckNames", "version": 6, "key": KEY},
            headers={"Origin": "https://jellyfin.example"},
        )
        other = await client.post(
            "/",
            json={"action": "deckNames", "version": 6, "key": KEY},
            headers={"Origin": "https://evil.example"},
        )
        lookalikes = [
            await client.options("/", headers=_preflight(origin))
            for origin in (
                "chrome-extension://id.evil.example",
                "https://chrome-extension.evil.example",
            )
        ]
    assert extension.status_code == 200
    assert extension.headers["access-control-allow-origin"] == "moz-extension://4b1d-a2c3"
    assert configured.headers["access-control-allow-origin"] == "https://jellyfin.example"
    assert "access-control-allow-origin" not in other.headers
    assert all("access-control-allow-origin" not in item.headers for item in lookalikes)


@pytest.mark.asyncio
async def test_extension_origins_can_be_turned_off(keyed_wrapper: AnkiWrapper) -> None:
    keyed_wrapper.settings.cors_extensions = False
    async with _client(keyed_wrapper) as client:
        refused = await client.options("/", headers=_preflight("chrome-extension://yomitan-id"))
    assert "access-control-allow-origin" not in refused.headers


@pytest.mark.asyncio
async def test_busy_collection_fails_after_the_timeout(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client, keyed_wrapper.gate.hold():
        error = await _error(client, "deckNames")
        assert "busy" in error
        # Actions that do not touch the collection never wait.
        assert await _result(client, "version") == 6


# Media


@pytest.mark.asyncio
async def test_store_media_file_returns_the_stored_name(keyed_wrapper: AnkiWrapper) -> None:
    media = Path(keyed_wrapper.col.media.dir())
    first = base64.b64encode(b"first").decode()
    second = base64.b64encode(b"second").decode()
    async with _client(keyed_wrapper) as client:
        assert (
            await _result(client, "storeMediaFile", filename="clip.mp3", data=first) == "clip.mp3"
        )
        # deleteExisting defaults to true and replaces the file under the same name.
        assert await _result(client, "storeMediaFile", filename="clip.mp3", data=second) == (
            "clip.mp3"
        )
        assert (media / "clip.mp3").read_bytes() == b"second"
        renamed = await _result(
            client, "storeMediaFile", filename="clip.mp3", data=first, deleteExisting=False
        )
        assert renamed != "clip.mp3"
        assert (media / cast(str, renamed)).read_bytes() == b"first"
        assert await _result(client, "storeMediaFile", filename="dir/shot.webp", data=first) == (
            "shot.webp"
        )
        skip = hashlib.md5(b"first").hexdigest()  # noqa: S324
        assert (
            await _result(client, "storeMediaFile", filename="skip.mp3", data=first, skipHash=skip)
            is None
        )
        assert not (media / "skip.mp3").exists()
        assert "base64" in await _error(client, "storeMediaFile", filename="x.mp3", data="@@")
        assert "path or URL" in await _error(
            client, "storeMediaFile", filename="x.mp3", path="/etc/passwd"
        )
        assert "path or URL" in await _error(
            client, "storeMediaFile", filename="x.mp3", url="http://127.0.0.1/"
        )
        assert await _result(client, "retrieveMediaFile", filename="clip.mp3") == second
        assert await _result(client, "retrieveMediaFile", filename="missing.mp3") is False
        names = cast(list[str], await _result(client, "getMediaFilesNames", pattern="clip*"))
        assert "clip.mp3" in names
        assert "shot.webp" not in names


# Notes


@pytest.mark.asyncio
async def test_add_note_uses_ankiconnect_validation(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        note_id = await _result(client, "addNote", note=_basic("日本語", tags="one two"))
        assert isinstance(note_id, int)
        assert await _error(client, "addNote", note=_basic("日本語")) == DUPLICATE_ERROR
        assert isinstance(
            await _result(
                client, "addNote", note=_basic("日本語", options={"allowDuplicate": "true"})
            ),
            int,
        )
        assert await _error(client, "addNote", note=_basic(" ")) == EMPTY_ERROR
        assert (
            await _error(client, "addNote", note={**_basic("x"), "deckName": "Nope"})
            == "deck was not found: Nope"
        )
        assert (
            await _error(client, "addNote", note={**_basic("x"), "modelName": "Nope"})
            == "model was not found: Nope"
        )
        # Field names match loosely and unknown fields are ignored.
        loose_id = await _result(
            client,
            "addNote",
            note={
                "deckName": "Default",
                "modelName": "Basic",
                "fields": {" front ": "loose", "BACK": "b", "Unknown": "ignored"},
            },
        )
        info = cast(list[JsonObject], await _result(client, "notesInfo", notes=[loose_id]))
        assert info[0]["fields"] == {
            "Front": {"value": "loose", "order": 0},
            "Back": {"value": "b", "order": 1},
        }
        assert await _result(client, "getNoteTags", note=note_id) == ["one", "two"]


@pytest.mark.asyncio
async def test_duplicate_scope_deck(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        await _result(client, "createDeck", deck="Mining")
        await _result(client, "addNote", note=_basic("word"))
        deck_scope: JsonObject = {"duplicateScope": "deck"}
        in_mining = {**_basic("word", options=deck_scope), "deckName": "Mining"}
        assert await _result(client, "canAddNotesWithErrorDetail", notes=[in_mining]) == [
            {"canAdd": True}
        ]
        await _result(client, "addNote", note=in_mining)
        assert await _result(
            client, "canAddNotesWithErrorDetail", notes=[in_mining, _basic("fresh")]
        ) == [{"canAdd": False, "error": DUPLICATE_ERROR}, {"canAdd": True}]
        assert await _result(client, "canAddNotes", notes=[in_mining]) == [False]
        elsewhere = {
            **in_mining,
            "options": {"duplicateScope": "deck", "duplicateScopeOptions": {"deckName": "Gone"}},
        }
        assert await _result(client, "canAddNote", note=elsewhere) is True


@pytest.mark.asyncio
async def test_add_note_with_inline_media(keyed_wrapper: AnkiWrapper) -> None:
    media = Path(keyed_wrapper.col.media.dir())
    async with _client(keyed_wrapper) as client:
        note = _basic(
            "",
            "meaning",
            picture=[{"filename": "shot.png", "data": PNG, "fields": ["Front"]}],
            audio={"filename": "line.mp3", "data": MP3, "fields": "back"},
        )
        assert await _result(client, "canAddNoteWithErrorDetail", note=note) == {"canAdd": True}
        assert not (media / "shot.png").exists()
        note_id = await _result(client, "addNote", note=note)
        info = cast(list[JsonObject], await _result(client, "notesInfo", notes=[note_id]))
    fields = cast(JsonObject, info[0]["fields"])
    assert cast(JsonObject, fields["Front"])["value"] == '<img src="shot.png">'
    assert cast(JsonObject, fields["Back"])["value"] == "meaning[sound:line.mp3]"
    assert (media / "shot.png").read_bytes() == base64.b64decode(PNG)
    assert (media / "line.mp3").read_bytes() == base64.b64decode(MP3)


@pytest.mark.asyncio
async def test_add_notes_is_all_or_nothing(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        ids = await _result(client, "addNotes", notes=[_basic("a"), _basic("b")])
        assert isinstance(ids, list)
        assert len(ids) == 2
        error = await _error(client, "addNotes", notes=[_basic("c"), _basic("a"), _basic("")])
        assert error == str([DUPLICATE_ERROR, EMPTY_ERROR])
        error = await _error(client, "addNotes", notes=[_basic("d"), _basic("d")])
        assert error == str([DUPLICATE_ERROR])
        assert await _result(client, "findNotes", query="Front:c or Front:d") == []
        assert await _result(client, "addNotes", notes=[]) == []


@pytest.mark.asyncio
async def test_note_updates(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        source = _basic("word", "before", tags=["yomitan"])
        note_id = await _result(client, "addNote", note=source)
        # Yomitan spreads its whole note input into updateNoteFields; tags are ignored.
        assert (
            await _result(
                client,
                "updateNoteFields",
                note={
                    **source,
                    "id": note_id,
                    "fields": {"back": "after"},
                    "tags": ["ignored"],
                    "picture": {"filename": "p.png", "data": PNG, "fields": ["Back"]},
                },
            )
            is None
        )
        info = cast(list[JsonObject], await _result(client, "notesInfo", notes=[note_id]))
        assert cast(JsonObject, info[0]["fields"])["Back"] == {
            "value": 'after<img src="p.png">',
            "order": 1,
        }
        assert info[0]["tags"] == ["yomitan"]
        await _result(client, "updateNote", note={"id": str(note_id), "tags": "new tags"})
        assert await _result(client, "getNoteTags", note=note_id) == ["new", "tags"]
        await _result(client, "updateNoteTags", note=note_id, tags=["only"])
        assert await _result(client, "getNoteTags", note=note_id) == ["only"]
        assert await _error(client, "updateNoteFields", note={"id": 1, "fields": {}}) == (
            "note was not found: 1"
        )
        assert await _error(client, "updateNote", note={"id": note_id}) == (
            "note must contain fields or tags"
        )


@pytest.mark.asyncio
async def test_lookups_keep_input_order_and_mark_missing_items(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        note_id = await _result(client, "addNote", note=_basic("lookup", tags=["t"]))
        assert await _result(client, "findNotes") == []
        assert await _result(client, "findNotes", query="added:1") == [note_id]
        infos = cast(list[JsonObject], await _result(client, "notesInfo", notes=[note_id, 999]))
        assert infos[1] == {}
        assert set(infos[0]) == {
            "noteId",
            "profile",
            "modelName",
            "tags",
            "fields",
            "mod",
            "cards",
        }
        by_query = cast(list[JsonObject], await _result(client, "notesInfo", query="lookup"))
        assert by_query[0]["noteId"] == note_id
        cards = cast(list[int], infos[0]["cards"])
        assert await _result(client, "findCards", query=f"nid:{note_id}") == cards
        card_infos = cast(list[JsonObject], await _result(client, "cardsInfo", cards=[*cards, 9]))
        assert card_infos[1] == {}
        assert card_infos[0]["note"] == note_id
        assert isinstance(card_infos[0]["flags"], int)
        assert card_infos[0]["queue"] == 0
        assert await _result(client, "cardsInfo", cards=cards, fields=["cardId", "queue"]) == [
            {"cardId": cards[0], "queue": 0}
        ]
        assert await _result(client, "areSuspended", cards=[cards[0], 9]) == [False, None]
        assert await _result(client, "suspend", cards=cards[0]) is True
        assert await _result(
            client, "apiReflect", scopes=["actions"], actions=["addNote", "guiBrowse"]
        ) == {"scopes": ["actions"], "actions": ["addNote"]}
        assert await _result(client, "apiReflect", scopes=[]) == {"scopes": []}


@pytest.mark.asyncio
async def test_package_paths_stay_inside_the_collection_folder(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        error = await _error(client, "exportPackage", deck="Default", path="../outside.apkg")
        assert "inside" in error
        assert await _result(client, "exportPackage", deck="Default", path="deck.apkg") is True
    assert (keyed_wrapper.collection_path.parent / "deck.apkg").exists()


# Client flows


@pytest.mark.asyncio
async def test_subtitle_miner_flow(keyed_wrapper: AnkiWrapper) -> None:
    """The calls the Subtitle Miner plugin makes against a server with a key."""
    async with _client(keyed_wrapper) as client:
        assert await _call(client, "requestPermission", key=None) == {
            "result": {"permission": "granted", "requireApikey": True, "version": 6},
            "error": None,
        }
        assert await _result(client, "version") == 6
        assert await _result(client, "deckNames") == ["Default"]
        assert "Basic" in cast(list[str], await _result(client, "modelNames"))
        assert await _result(client, "modelFieldNames", modelName="Basic") == ["Front", "Back"]
        image = await _result(client, "storeMediaFile", filename="ep01_0412.webp", data=PNG)
        audio = await _result(client, "storeMediaFile", filename="ep01_0412.opus", data=MP3)
        note_id = await _result(
            client,
            "addNote",
            note=_basic(f'<img src="{image}">', f"[sound:{audio}]", tags=["subtitle-miner"]),
        )
        newest = cast(list[int], await _result(client, "findNotes", query="added:1"))
        assert max(newest) == note_id
        await _result(
            client,
            "updateNoteFields",
            note={"id": note_id, "fields": {"Back": f"line [sound:{audio}]"}},
        )
        info = cast(list[JsonObject], await _result(client, "notesInfo", notes=[note_id]))
        assert cast(JsonObject, info[0]["fields"])["Back"] == {
            "value": "line [sound:ep01_0412.opus]",
            "order": 1,
        }
        assert await _result(client, "canAddNotes", notes=[_basic("fresh")]) == [True]


@pytest.mark.asyncio
async def test_yomitan_flow(keyed_wrapper: AnkiWrapper) -> None:
    """Yomitan sends version 2 requests, so replies are bare results."""
    async with _client(keyed_wrapper) as client:

        async def invoke(action: str, **params: object) -> JsonValue:
            return await _call(client, action, version=2, **params)

        assert await invoke("version") == 6
        assert await invoke("modelFieldNames", modelName="Basic") == ["Front", "Back"]
        filename = await invoke("storeMediaFile", filename="yomitan_audio.mp3", data=MP3)
        assert filename == "yomitan_audio.mp3"
        source = _basic(
            "日本語",
            f"[sound:{filename}]",
            tags=["yomitan"],
            options={
                "allowDuplicate": False,
                "duplicateScope": "collection",
                "duplicateScopeOptions": {
                    "deckName": None,
                    "checkChildren": False,
                    "checkAllModels": False,
                },
            },
        )
        note_id = await invoke("addNote", note=source)
        assert isinstance(note_id, int)
        assert await invoke("canAddNotesWithErrorDetail", notes=[source]) == [
            {"canAdd": False, "error": DUPLICATE_ERROR}
        ]
        actions: list[JsonValue] = [
            {"action": "findNotes", "params": {"query": f'nid:{note_id} "front:{word}"'}}
            for word in ("日本語", "other")
        ]
        assert await invoke("multi", actions=actions) == [[note_id], []]
        infos = cast(list[JsonObject], await invoke("notesInfo", notes=[note_id, 999]))
        assert infos[0]["tags"] == ["yomitan"]
        assert infos[1] == {}
        assert await invoke("guiBrowse", query=f"nid:{note_id}") == {
            "result": None,
            "error": "unsupported action",
        }


@pytest.mark.asyncio
async def test_concurrent_requests_are_serialized(keyed_wrapper: AnkiWrapper) -> None:
    async with _client(keyed_wrapper) as client:
        replies = await asyncio.gather(
            *(_call(client, "addNote", note=_basic(f"parallel {index}")) for index in range(20))
        )
    assert all(cast(JsonObject, reply)["error"] is None for reply in replies)
    assert len(keyed_wrapper.find_notes("parallel")) == 20

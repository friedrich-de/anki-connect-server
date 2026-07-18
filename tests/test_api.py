from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import patch

import pytest
from anki.cards import CardId
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.api import create_app
from anki_connect_server.types import JsonObject, NoteInput


@asynccontextmanager
async def _app_client(anki_wrapper: AnkiWrapper) -> AsyncGenerator[AsyncClient]:
    application = create_app(lambda: anki_wrapper)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
        ) as client,
    ):
        yield client


@pytest.mark.asyncio
async def test_root_supports_ankiconnect_requests(anki_wrapper: AnkiWrapper) -> None:
    async with _app_client(anki_wrapper) as client:
        response = await client.post("/", json={"action": "version", "version": 6})

    assert response.status_code == 200
    assert cast(JsonObject, response.json()) == {"result": 6, "error": None}


@pytest.mark.asyncio
async def test_removed_api_alias_returns_not_found(anki_wrapper: AnkiWrapper) -> None:
    async with _app_client(anki_wrapper) as client:
        response = await client.post("/api", json={"action": "version"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_health_endpoint(anki_wrapper: AnkiWrapper) -> None:
    async with _app_client(anki_wrapper) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_api_runs_representative_action(anki_wrapper: AnkiWrapper) -> None:
    request = {
        "action": "addNote",
        "params": {
            "note": {
                "deckName": "Default",
                "modelName": "Basic",
                "fields": {"Front": "Question", "Back": "Answer"},
            }
        },
    }
    async with _app_client(anki_wrapper) as client:
        response = await client.post("/", json=request)

    data = cast(JsonObject, response.json())
    assert response.status_code == 200
    assert isinstance(data["result"], int)
    assert data["error"] is None


@pytest.mark.asyncio
async def test_answer_cards_validates_before_mutation_and_preserves_order(
    anki_wrapper: AnkiWrapper,
) -> None:
    note_id = anki_wrapper.add_note(
        NoteInput(
            deckName="Default",
            modelName="Basic",
            fields={"Front": "Untouched", "Back": "Answer"},
        )
    )
    assert note_id is not None
    card_id = anki_wrapper.find_cards(f"nid:{note_id}")[0]

    async with _app_client(anki_wrapper) as client:
        invalid_response = await client.post(
            "/",
            json={
                "action": "answerCards",
                "params": {
                    "answers": [
                        {"cardId": card_id, "ease": 3},
                        {"cardId": card_id, "ease": 5},
                    ]
                },
            },
        )
        queue = anki_wrapper.col.get_card(CardId(card_id)).queue
        valid_response = await client.post(
            "/",
            json={
                "action": "answerCards",
                "params": {
                    "answers": [
                        {"cardId": card_id, "ease": 3},
                        {"cardId": 1, "ease": 1},
                    ]
                },
            },
        )

    data = cast(JsonObject, invalid_response.json())
    assert data["result"] is None
    assert data["error"] == "ease must be one of 1, 2, 3, or 4"
    assert queue == 0
    assert valid_response.json() == {"result": [True, False], "error": None}


@pytest.mark.asyncio
async def test_unknown_action_uses_ankiconnect_error_envelope(
    anki_wrapper: AnkiWrapper,
) -> None:
    async with _app_client(anki_wrapper) as client:
        response = await client.post("/", json={"action": "unknown"})

    data = cast(JsonObject, response.json())
    assert response.status_code == 200
    assert data["result"] is None
    assert data["error"] == "Unsupported action: unknown"


@pytest.mark.asyncio
async def test_invalid_json_is_rejected(anki_wrapper: AnkiWrapper) -> None:
    async with _app_client(anki_wrapper) as client:
        response = await client.post(
            "/",
            content="not-json",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_uninitialized_server_returns_clear_error() -> None:
    application = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        response = await client.post("/", json={"action": "version"})

    assert response.json() == {"result": None, "error": "Server not initialized"}


@pytest.mark.asyncio
async def test_lifespan_closes_wrapper(anki_wrapper: AnkiWrapper) -> None:
    application: FastAPI = create_app(lambda: anki_wrapper)
    with patch.object(anki_wrapper, "close") as close:
        async with application.router.lifespan_context(application):
            assert application.state.anki_wrapper is anki_wrapper

    close.assert_called_once_with()
    assert application.state.anki_wrapper is None

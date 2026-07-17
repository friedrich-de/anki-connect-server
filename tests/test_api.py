from collections.abc import Iterator
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient

from anki_connect_server import wrapper
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.api import app
from anki_connect_server.types import JsonObject


@pytest.fixture(autouse=True)
def initialized_app(anki_wrapper: AnkiWrapper) -> Iterator[None]:
    original = wrapper.maybe_get_anki_wrapper()
    wrapper.set_wrapper(anki_wrapper)
    try:
        yield
    finally:
        wrapper.set_wrapper(original)


@pytest.mark.parametrize("path", ["/", "/api"])
@pytest.mark.asyncio
async def test_api_paths_support_ankiconnect_requests(path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(path, json={"action": "version", "version": 6})

    assert response.status_code == 200
    assert cast(JsonObject, response.json()) == {"result": 6, "error": None}


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


@pytest.mark.asyncio
async def test_api_runs_representative_action() -> None:
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json=request)

    data = cast(JsonObject, response.json())
    assert response.status_code == 200
    assert isinstance(data["result"], int)
    assert data["error"] is None


@pytest.mark.asyncio
async def test_unknown_action_uses_ankiconnect_error_envelope() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/", json={"action": "unknown"})

    data = cast(JsonObject, response.json())
    assert response.status_code == 200
    assert data["result"] is None
    assert data["error"] == "Unsupported action: unknown"


@pytest.mark.asyncio
async def test_invalid_json_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/",
            content="not-json",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_uninitialized_server_returns_clear_error() -> None:
    current = wrapper.maybe_get_anki_wrapper()
    wrapper.set_wrapper(None)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/", json={"action": "version"})
    finally:
        wrapper.set_wrapper(current)

    assert response.json() == {"result": None, "error": "Server not initialized"}

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from anki_connect_server import wrapper
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import get_config
from anki_connect_server.handlers import dispatch
from anki_connect_server.types import JsonObject, JsonValue


@asynccontextmanager
async def app_lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    settings = get_config()
    wrapper.set_wrapper(AnkiWrapper(settings.collection_path, settings=settings))
    try:
        yield
    finally:
        wrapper.close_wrapper()


app = FastAPI(
    title="AnkiConnect Server",
    description="Headless AnkiConnect-compatible REST API server with AnkiWeb sync",
    version="0.2.0",
    lifespan=app_lifespan,
)


class AnkiConnectRequest(BaseModel):
    action: str
    version: int = 6
    params: JsonObject = Field(default_factory=dict)


class AnkiConnectResponse(BaseModel):
    result: JsonValue = None
    error: str | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/", response_model=AnkiConnectResponse)
@app.post("/api", response_model=AnkiConnectResponse)
async def handle_request(req: AnkiConnectRequest) -> AnkiConnectResponse:
    anki_wrapper = wrapper.maybe_get_anki_wrapper()
    if anki_wrapper is None:
        return AnkiConnectResponse(error="Server not initialized")

    try:
        result = await dispatch(req.action, req.params, anki_wrapper)
        return AnkiConnectResponse(result=result)
    except Exception as exc:
        return AnkiConnectResponse(error=str(exc))


def run_server() -> None:
    """Run the FastAPI server."""
    import uvicorn

    settings = get_config()
    uvicorn.run(app, host=settings.bind, port=settings.port)


if __name__ == "__main__":
    run_server()

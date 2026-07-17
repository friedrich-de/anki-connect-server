from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, Field

from anki_connect_server import ANKICONNECT_API_VERSION, __version__
from anki_connect_server.anki_wrapper import AnkiWrapper, WrapperFactory, create_anki_wrapper
from anki_connect_server.config import get_config
from anki_connect_server.handlers import dispatch
from anki_connect_server.types import JsonObject, JsonValue


class AnkiConnectRequest(BaseModel):
    action: str
    version: int = ANKICONNECT_API_VERSION
    params: JsonObject = Field(default_factory=dict)


class AnkiConnectResponse(BaseModel):
    result: JsonValue = None
    error: str | None = None


router = APIRouter()


def get_request_wrapper(request: Request) -> AnkiWrapper | None:
    value = getattr(request.app.state, "anki_wrapper", None)
    return value if isinstance(value, AnkiWrapper) else None


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@router.post("/", response_model=AnkiConnectResponse)
async def handle_request(
    req: AnkiConnectRequest,
    anki_wrapper: Annotated[AnkiWrapper | None, Depends(get_request_wrapper)],
) -> AnkiConnectResponse:
    if anki_wrapper is None:
        return AnkiConnectResponse(error="Server not initialized")

    try:
        result = await dispatch(req.action, req.params, anki_wrapper)
        return AnkiConnectResponse(result=result)
    except Exception as exc:
        return AnkiConnectResponse(error=str(exc))


def create_app(wrapper_factory: WrapperFactory = create_anki_wrapper) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        anki_wrapper = wrapper_factory()
        application.state.anki_wrapper = anki_wrapper
        try:
            yield
        finally:
            anki_wrapper.close()
            application.state.anki_wrapper = None

    application = FastAPI(
        title="AnkiConnect Server",
        description="Headless AnkiConnect-compatible REST API server with AnkiWeb sync",
        version=__version__,
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


app = create_app()


def run_server() -> None:
    """Run the FastAPI server."""
    import uvicorn

    settings = get_config()
    uvicorn.run(app, host=settings.bind, port=settings.port)

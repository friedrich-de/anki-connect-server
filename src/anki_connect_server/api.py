import asyncio
import hmac
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from anki_connect_server import ANKICONNECT_API_VERSION, __version__
from anki_connect_server.anki_wrapper import AnkiWrapper, WrapperFactory, create_anki_wrapper
from anki_connect_server.autosync import AutoSync, AutoSyncState
from anki_connect_server.config import Config, get_config
from anki_connect_server.gate import CollectionBusyError
from anki_connect_server.handlers import (
    API_KEY_ERROR,
    NO_COLLECTION_ACTIONS,
    execute_request,
    reply,
)
from anki_connect_server.types import JsonValue

logger = logging.getLogger(__name__)

EXTENSION_ORIGIN_PATTERN = r"(chrome-extension|moz-extension|safari-web-extension)://[A-Za-z0-9_-]+"

router = APIRouter()


class RequestTooLargeError(ValueError):
    pass


def _wrapper(request: Request) -> AnkiWrapper | None:
    value = getattr(request.app.state, "anki_wrapper", None)
    return value if isinstance(value, AnkiWrapper) else None


def _settings(request: Request) -> Config | None:
    value = getattr(request.app.state, "settings", None)
    return value if isinstance(value, Config) else None


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise RequestTooLargeError
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise RequestTooLargeError
        chunks.append(chunk)
    return b"".join(chunks)


def _matches(provided: object, expected: str) -> bool:
    return isinstance(provided, str) and hmac.compare_digest(
        provided.encode("utf-8"), expected.encode("utf-8")
    )


def _authorized(request: Request, payload: dict[str, JsonValue], expected: str) -> bool:
    """Accept AnkiConnect's body ``key`` or an ``Authorization: Bearer`` header."""
    if _matches(payload.get("key"), expected):
        return True
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and _matches(token.strip(), expected)


def _version_of(payload: dict[str, JsonValue]) -> int:
    value = payload.get("version")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return 4 if value is None else ANKICONNECT_API_VERSION


def _json(content: JsonValue, status_code: int = 200) -> Response:
    return JSONResponse(content=content, status_code=status_code)


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    auto_sync = getattr(request.app.state, "auto_sync", None)
    state = auto_sync.state if isinstance(auto_sync, AutoSync) else AutoSyncState.OFF
    return {"status": "healthy", "autoSync": str(state)}


@router.api_route("/", methods=["GET", "POST"])
async def handle_request(request: Request) -> Response:
    """Serve the AnkiConnect legacy protocol at the root path.

    Like AnkiConnect, every reply uses HTTP 200 with its JSON body, whatever the
    content type of the request; a GET without a body returns a banner.
    """
    settings = _settings(request)
    anki_wrapper = _wrapper(request)
    if settings is None or anki_wrapper is None:
        return _json({"result": None, "error": "Server not initialized"})
    try:
        body = await _read_body(request, settings.max_request_bytes)
    except RequestTooLargeError:
        return _json({"result": None, "error": "request body is too large"}, 413)
    if request.method == "GET" and not body.strip():
        return PlainTextResponse(f"AnkiConnect v.{ANKICONNECT_API_VERSION}")
    try:
        payload: JsonValue = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json({"result": None, "error": "request body must be JSON"})
    if not isinstance(payload, dict):
        return _json({"result": None, "error": "request must be a JSON object"})

    action = payload.get("action")
    expected_key = settings.api_key_value
    if (
        expected_key is not None
        and action != "requestPermission"
        and not _authorized(request, payload, expected_key)
    ):
        logger.warning("Rejected a request with a missing or wrong API key")
        return _json({"result": None, "error": API_KEY_ERROR})

    if isinstance(action, str) and action in NO_COLLECTION_ACTIONS:
        return _json(execute_request(payload, anki_wrapper))
    try:
        result = await anki_wrapper.gate.run(lambda: execute_request(payload, anki_wrapper))
    except CollectionBusyError as error:
        result = reply(_version_of(payload), error=str(error))
    return _json(result)


def create_app(
    wrapper_factory: WrapperFactory = create_anki_wrapper,
    settings: Config | None = None,
    *,
    close_wrapper: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None]:
        anki_wrapper = wrapper_factory()
        application.state.anki_wrapper = anki_wrapper
        application.state.settings = settings or anki_wrapper.settings
        task: asyncio.Task[None] | None = None
        resolved = application.state.settings
        if resolved.auto_sync:
            auto_sync = AutoSync(
                anki_wrapper,
                delay=resolved.auto_sync_delay,
                interval=resolved.auto_sync_interval,
            )
            application.state.auto_sync = auto_sync
            task = asyncio.create_task(auto_sync.run(), name="auto-sync")
        if resolved.api_key_value is None and resolved.bind not in (
            "127.0.0.1",
            "localhost",
            "::1",
        ):
            logger.warning(
                "The AnkiConnect API listens on %s without an API key; set "
                "ANKICONNECT_API_KEY before exposing it to other machines",
                resolved.bind,
            )
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            application.state.auto_sync = None
            if close_wrapper:
                anki_wrapper.close()
            application.state.anki_wrapper = None

    application = FastAPI(
        title="AnkiConnect Server",
        description="Headless AnkiConnect-compatible API server with AnkiWeb sync",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.include_router(router)
    origins = settings.cors_origins if settings is not None else []
    extensions = settings.cors_extensions if settings is not None else False
    if origins or extensions:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_origin_regex=EXTENSION_ORIGIN_PATTERN if extensions else None,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
            max_age=600,
        )
    return application


def run_server() -> None:
    """Run the AnkiConnect API server."""
    import uvicorn

    settings = get_config()
    application = create_app(lambda: create_anki_wrapper(settings), settings)
    uvicorn.run(application, host=settings.bind, port=settings.port)

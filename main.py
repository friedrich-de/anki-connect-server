import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request
from pydantic import BaseModel

from config import config, Config
from anki_wrapper import AnkiWrapper
from api.handlers import dispatch


wrapper: Optional[AnkiWrapper] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global wrapper
    config.validate()
    wrapper = AnkiWrapper(config.COLLECTION_PATH)
    yield
    if wrapper:
        wrapper.close()


app = FastAPI(
    title="AnkiConnect Server",
    description="Headless AnkiConnect-compatible REST API server with AnkiWeb sync",
    version="0.1.0",
    lifespan=lifespan,
)


class AnkiConnectRequest(BaseModel):
    action: str
    version: int = 6
    params: dict = {}


class AnkiConnectResponse(BaseModel):
    result: Any
    error: Optional[str] = None


@app.get("/")
async def root():
    return {"message": "AnkiConnect Server is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/", response_model=AnkiConnectResponse)
async def handle_request(req: AnkiConnectRequest):
    if not wrapper:
        return {"result": None, "error": "Server not initialized"}

    try:
        result = await dispatch(req.action, req.params, wrapper)
        return {"result": result, "error": None}
    except Exception as e:
        return {"result": None, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.BIND, port=config.PORT)
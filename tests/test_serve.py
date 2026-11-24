import asyncio
import socket
import sys
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from pydantic import SecretStr

from anki_connect_server.config import Config
from anki_connect_server.serve import mcp_url, serve, supervise_tunnel
from anki_connect_server.tunnel import build_tunnel_command


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def _wait_for(url: str) -> httpx.Response:
    async with httpx.AsyncClient() as client:
        for _ in range(100):
            try:
                return await client.get(url)
            except httpx.TransportError:
                await asyncio.sleep(0.05)
    raise AssertionError(f"{url} did not answer")


@pytest.mark.asyncio
async def test_serve_shares_one_collection_between_api_and_loopback_mcp(tmp_path: Path) -> None:
    settings = Config(
        collection_path=tmp_path / "served.anki2",
        port=_free_port(),
        mcp_port=_free_port(),
        api_key=SecretStr("served-key"),
    )
    stop = asyncio.Event()
    server = asyncio.create_task(serve(settings, stop=stop, log_level="warning"))
    try:
        health = await _wait_for(f"http://127.0.0.1:{settings.port}/health")
        assert health.json() == {"status": "healthy", "autoSync": "off"}
        async with httpx.AsyncClient() as client:
            created = await client.post(
                f"http://127.0.0.1:{settings.port}/",
                json={
                    "action": "addNote",
                    "version": 6,
                    "key": "served-key",
                    "params": {
                        "note": {
                            "deckName": "Default",
                            "modelName": "Basic",
                            "fields": {"Front": "served", "Back": ""},
                        }
                    },
                },
            )
        note_id = created.json()["result"]
        assert isinstance(note_id, int)

        async with Client(mcp_url(settings)) as mcp:
            found = await mcp.call_tool("search_notes", {"query": "served"})
        assert note_id in [note["note_id"] for note in (found.structured_content or {})["notes"]]
    finally:
        stop.set()
        await asyncio.wait_for(server, 10)


@pytest.mark.asyncio
async def test_tunnel_client_is_restarted_and_stopped(tmp_path: Path) -> None:
    marker = tmp_path / "starts"
    script = (
        "import pathlib, sys, time\n"
        f"path = pathlib.Path({str(marker)!r})\n"
        "count = int(path.read_text()) if path.exists() else 0\n"
        "path.write_text(str(count + 1))\n"
        "sys.exit(1) if count == 0 else time.sleep(60)\n"
    )
    stop = asyncio.Event()
    task = asyncio.create_task(
        supervise_tunnel([sys.executable, "-c", script], {}, stop, lambda: True)
    )
    for _ in range(100):
        if marker.exists() and marker.read_text() == "2":
            break
        await asyncio.sleep(0.05)
    assert marker.read_text() == "2"
    stop.set()
    await asyncio.wait_for(task, 15)


def test_tunnel_command_can_target_the_loopback_mcp_url() -> None:
    assert build_tunnel_command("tunnel-client", mcp_url="http://127.0.0.1:8766/mcp") == [
        "tunnel-client",
        "run",
        "--control-plane.api-key",
        "env:CONTROL_PLANE_API_KEY",
        "--mcp.server-url",
        "http://127.0.0.1:8766/mcp",
    ]
    with pytest.raises(ValueError, match="exactly one"):
        build_tunnel_command("tunnel-client")

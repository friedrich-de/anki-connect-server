"""Serve the AnkiConnect API and MCP from one process that owns the collection.

An Anki collection must not be opened by two processes. ``serve`` therefore runs
the AnkiConnect HTTP API, an MCP endpoint reachable only on loopback, automatic
sync, and optionally OpenAI's tunnel-client (pointed at that loopback MCP
endpoint) around a single open collection.
"""

import asyncio
import logging
import signal
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from contextlib import contextmanager, suppress

import uvicorn

from anki_connect_server.anki_wrapper import create_anki_wrapper
from anki_connect_server.api import create_app
from anki_connect_server.config import Config
from anki_connect_server.mcp_server import create_mcp_server
from anki_connect_server.tunnel import (
    TunnelConfig,
    build_tunnel_command,
    build_tunnel_environment,
    resolve_tunnel_client,
)

logger = logging.getLogger(__name__)

MCP_HOST = "127.0.0.1"
MCP_PATH = "/mcp"
TUNNEL_STOP_SECONDS = 10.0
MAX_TUNNEL_RESTART_SECONDS = 60.0


class _Server(uvicorn.Server):
    """A uvicorn server that leaves signal handling to ``serve``."""

    @contextmanager
    def capture_signals(self) -> Generator[None]:
        yield


def mcp_url(settings: Config) -> str:
    return f"http://{MCP_HOST}:{settings.mcp_port}{MCP_PATH}"


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), TUNNEL_STOP_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()


async def supervise_tunnel(
    command: Sequence[str],
    environment: Mapping[str, str],
    stop: asyncio.Event,
    ready: Callable[[], bool],
) -> None:
    """Keep tunnel-client running until ``stop`` is set, restarting it with backoff."""
    while not ready():
        if stop.is_set():
            return
        await asyncio.sleep(0.1)
    delay = 1.0
    while not stop.is_set():
        started = time.monotonic()
        process = await asyncio.create_subprocess_exec(*command, env=dict(environment))
        waiter = asyncio.ensure_future(process.wait())
        stopper = asyncio.ensure_future(stop.wait())
        await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
        stopper.cancel()
        if stop.is_set():
            waiter.cancel()
            await _stop_process(process)
            return
        if time.monotonic() - started > MAX_TUNNEL_RESTART_SECONDS:
            delay = 1.0
        logger.warning(
            "tunnel-client exited with status %s; restarting in %.0f s",
            process.returncode,
            delay,
        )
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), delay)
        delay = min(delay * 2, MAX_TUNNEL_RESTART_SECONDS)


async def serve(
    settings: Config,
    *,
    tunnel: bool = False,
    tunnel_settings: TunnelConfig | None = None,
    log_level: str = "info",
    stop: asyncio.Event | None = None,
) -> None:
    """Serve until SIGINT or SIGTERM arrives, ``stop`` is set, or a server fails."""
    tunnel_command: list[str] | None = None
    tunnel_environment: dict[str, str] | None = None
    if tunnel:
        resolved_tunnel = tunnel_settings or TunnelConfig()
        tunnel_command = build_tunnel_command(
            resolve_tunnel_client(resolved_tunnel), mcp_url=mcp_url(settings)
        )
        tunnel_environment = build_tunnel_environment(resolved_tunnel, settings)

    wrapper = create_anki_wrapper(settings)
    try:
        api_app = create_app(lambda: wrapper, settings, close_wrapper=False)
        mcp_app = create_mcp_server(lambda: wrapper, close_wrapper=False).http_app(path=MCP_PATH)
        api = _Server(
            uvicorn.Config(api_app, host=settings.bind, port=settings.port, log_level=log_level)
        )
        mcp = _Server(
            uvicorn.Config(mcp_app, host=MCP_HOST, port=settings.mcp_port, log_level=log_level)
        )

        stop = stop or asyncio.Event()
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(signal_number, stop.set)

        tasks = [
            asyncio.create_task(api.serve(), name="api"),
            asyncio.create_task(mcp.serve(), name="mcp"),
        ]
        if tunnel_command is not None and tunnel_environment is not None:
            tasks.append(
                asyncio.create_task(
                    supervise_tunnel(tunnel_command, tunnel_environment, stop, lambda: mcp.started),
                    name="tunnel",
                )
            )
        stopper = asyncio.create_task(stop.wait(), name="stop")
        await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
        stop.set()
        api.should_exit = True
        mcp.should_exit = True
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signal_number)
        for task, result in zip(tasks, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("%s stopped with an error: %r", task.get_name(), result)
    finally:
        wrapper.close()


def run_serve(*, tunnel: bool) -> None:
    from anki_connect_server.config import get_config

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(serve(get_config(), tunnel=tunnel))

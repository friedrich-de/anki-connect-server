"""CLI entry point for anki-connect-server."""

import argparse
import sys
from collections.abc import Sequence


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anki-connect-server",
        description="Headless AnkiConnect-compatible REST API server with MCP support",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("api", help="Run the AnkiConnect API server")
    subparsers.add_parser("mcp", help="Run the MCP server")
    tunnel_parser = subparsers.add_parser(
        "tunnel",
        help="Connect the MCP server through OpenAI Secure MCP Tunnel",
    )
    tunnel_parser.add_argument(
        "--doctor",
        action="store_true",
        help="Validate the tunnel and MCP configuration without starting the daemon",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()

    args = parser.parse_args(argv)

    if args.command == "api":
        from anki_connect_server.api import run_server

        run_server()
    elif args.command == "mcp":
        from anki_connect_server.mcp_server import run

        run()
    elif args.command == "tunnel":
        from anki_connect_server.tunnel import run_tunnel

        try:
            run_tunnel(doctor=bool(args.doctor))
        except (OSError, RuntimeError, ValueError) as exc:
            parser.exit(1, f"{parser.prog}: error: {exc}\n")
    else:
        parser.print_help()
        sys.exit(2)

"""CLI entry point for anki-connect-server."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="anki-connect-server",
        description="Headless AnkiConnect-compatible REST API server with MCP support",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("api", help="Run the AnkiConnect API server")
    subparsers.add_parser("mcp", help="Run the MCP server")

    args = parser.parse_args()

    if args.command == "api":
        from anki_connect_server.api import run_server

        run_server()
    elif args.command == "mcp":
        from anki_connect_server.mcp_server import run

        run()
    else:
        parser.print_help()
        sys.exit(2)

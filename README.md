# AnkiConnect Server

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

A headless server that exposes a useful subset of the AnkiConnect version 6 protocol, an
MCP server for AI assistants, and on-demand AnkiWeb synchronization. It accesses an Anki
collection directly, so the desktop application does not need to be running.

## Features

- AnkiConnect-compatible JSON API at `POST /`
- MCP tools for decks, models, notes, cards, media, packages, and synchronization
- Outbound-only OpenAI Secure MCP Tunnel support for the stdio MCP server
- Direct headless access to an Anki collection without Qt
- On-demand collection and media synchronization with AnkiWeb
- Local Docker image and persistent data-directory support

This project implements the actions listed below; it does not claim complete parity with every
action provided by the AnkiConnect desktop add-on.

## Setup

Install [uv](https://docs.astral.sh/uv/), clone the repository, and create the environment:

```bash
git clone https://github.com/friedrich-de/anki-connect-server.git
cd anki-connect-server
uv sync --locked
cp .env.example .env
```

Set `ANKICONNECT_COLLECTION_PATH` in `.env`, then start any interface:

```bash
uv run anki-connect-server api
uv run anki-connect-server mcp
uv run anki-connect-server tunnel
```

Do not open the same collection concurrently in this server and another Anki process.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `ANKICONNECT_COLLECTION_PATH` | Yes | — | Path to the `.anki2` collection file |
| `ANKICONNECT_PORT` | No | `8765` | API server port |
| `ANKICONNECT_BIND` | No | `127.0.0.1` | API bind address |
| `ANKICONNECT_ANKIWEB_USER` | For sync | — | AnkiWeb username |
| `ANKICONNECT_ANKIWEB_PASS` | For sync | — | AnkiWeb password |
| `ANKICONNECT_ANKIWEB_URL` | No | AnkiWeb | Custom sync-server URL |
| `ANKICONNECT_FULL_UPLOAD` | No | `false` | Permit a full upload when AnkiWeb requests one |
| `CONTROL_PLANE_TUNNEL_ID` | For tunnel | — | OpenAI Secure MCP Tunnel ID |
| `CONTROL_PLANE_API_KEY` | For tunnel | — | Runtime API key with Tunnels Read + Use |
| `TUNNEL_CLIENT_PATH` | No | `tunnel-client` | Tunnel client executable name or path |

The API has no authentication layer. Keep it bound to a trusted interface or place it behind an
authenticated reverse proxy with TLS.

### Migration notes

- Use `POST /`; the former `POST /api` alias has been removed.
- Use `ANKICONNECT_COLLECTION_PATH`; the former `ANKI_COLLECTION_PATH` alias has been removed.

## AnkiConnect-compatible API

Send version 6 requests to `POST /`:

```json
{
  "action": "deckNames",
  "version": 6,
  "params": {}
}
```

Responses retain the AnkiConnect envelope:

```json
{
  "result": ["Default"],
  "error": null
}
```

Example:

```bash
curl --request POST http://localhost:8765/ \
  --header 'Content-Type: application/json' \
  --data '{"action":"createDeck","version":6,"params":{"deck":"Spanish"}}'
```

Supported actions are:

- General: `version`, `multi`, `sync`, `syncStatus`, `syncMedia`, `importPackage`, `exportPackage`
- Decks: `deckNames`, `deckNamesAndIds`, `getDecks`, `createDeck`, `changeDeck`, `deleteDecks`,
  `getDeckConfig`, `saveDeckConfig`, `setDeckConfigId`, `cloneDeckConfigId`,
  `removeDeckConfigId`
- Models: `modelNames`, `modelNamesAndIds`, `modelFieldNames`, `modelFieldsOnTemplates`,
  `createModel`, `modelTemplates`, `modelStyling`, `updateModelTemplates`, `updateModelStyling`
- Notes: `addNote`, `addNotes`, `canAddNotes`, `updateNoteFields`, `addTags`, `removeTags`,
  `getTags`, `findNotes`, `notesInfo`, `deleteNotes`
- Cards: `findCards`, `cardsToNotes`, `cardsInfo`, `suspend`, `unsuspend`, `areSuspended`,
  `areDue`, `getIntervals`
- Media: `getMediaDirPath`, `storeMediaFile`, `retrieveMediaFile`, `deleteMediaFile`

The health endpoint is available at `GET /health`.

## MCP server

The `mcp` command runs over stdio. Its tool names are:

- Decks: `get_deck_names`, `get_deck_names_and_ids`, `create_deck`, `delete_decks`,
  `change_deck`, `get_deck_config`
- Models: `get_model_names`, `get_model_field_names`, `get_model_templates`,
  `get_model_styling`
- Notes and cards: `add_note`, `find_notes`, `get_notes_info`, `delete_notes`, `find_cards`,
  `get_cards_info`, `suspend_cards`, `unsuspend_cards`, `are_suspended`, `are_due`,
  `get_card_intervals`, `cards_to_notes`
- Tags and media: `get_all_tags`, `add_tags`, `remove_tags`, `get_media_dir_path`,
  `store_media_file`, `retrieve_media_file`, `delete_media_file`
- Packages and sync: `import_package`, `export_package`, `sync`, `sync_media`,
  `get_sync_status`, `get_api_version`

For a local MCP host, point the configuration at this source checkout:

```json
{
  "mcpServers": {
    "anki-connect-server": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/anki-connect-server",
        "run",
        "anki-connect-server",
        "mcp"
      ],
      "env": {
        "ANKICONNECT_COLLECTION_PATH": "/absolute/path/to/collection.anki2"
      }
    }
  }
}
```

## OpenAI Secure MCP Tunnel

The `tunnel` command makes the stdio MCP server reachable through OpenAI's outbound-only
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). It loads
the tunnel ID and runtime key from `.env`, keeps the key out of command-line arguments, and lets
the official `tunnel-client` supervise `anki-connect-server mcp` as its private MCP process.

The devcontainer and local Docker image include a checksum-verified, pinned release of the
official client. For a source checkout outside those containers, download `tunnel-client` from
the [official releases](https://github.com/openai/tunnel-client/releases/latest), put it on
`PATH`, or set `TUNNEL_CLIENT_PATH` to the executable.

Add the credentials created in OpenAI Platform tunnel settings to `.env`:

```dotenv
CONTROL_PLANE_TUNNEL_ID=tunnel_0123456789abcdef0123456789abcdef
CONTROL_PLANE_API_KEY=your_runtime_api_key
```

Validate the local command, credentials, permissions, and control-plane connection first, then
start the foreground tunnel daemon:

```bash
uv run anki-connect-server tunnel --doctor
uv run anki-connect-server tunnel
```

Keep the second command running for connector discovery and tool calls. The tunnel-client health
and administration UI uses `http://127.0.0.1:8080/ui` by default. The MCP server remains on stdio,
and the tunnel opens no inbound internet listener; its control-plane traffic uses outbound HTTPS.

## Local Docker use

Build the image from this checkout:

```bash
docker build --tag anki-connect-server:local .
mkdir -p anki-data
docker run --rm \
  --publish 127.0.0.1:8765:8765 \
  --volume "$PWD/anki-data:/data" \
  anki-connect-server:local
```

Mounting the full `/data` directory persists the collection and its media. The image defaults to
`ANKICONNECT_COLLECTION_PATH=/data/collection.anki2` and creates the collection when necessary.
The published port is bound to host loopback, so it is available only to local clients and reverse
proxies running on the host. Keep `ANKICONNECT_BIND=0.0.0.0` inside the container so that container
port forwarding can reach the server.

An equivalent Compose service uses the local Dockerfile:

```yaml
services:
  anki-connect-server:
    build: .
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - ./anki-data:/data
    restart: unless-stopped
```

To expose the image's stdio MCP server to an MCP host, use an interactive one-shot container:

```bash
docker run --rm --interactive \
  --volume "$PWD/anki-data:/data" \
  anki-connect-server:local \
  anki-connect-server mcp
```

To run the OpenAI tunnel from the image, pass the tunnel credentials from `.env`, override the
host collection path with the image's `/data` path, and optionally publish the tunnel health UI:

```bash
docker run --rm --init \
  --env-file .env \
  --env ANKICONNECT_COLLECTION_PATH=/data/collection.anki2 \
  --env HEALTH_LISTEN_ADDR=0.0.0.0:8080 \
  --publish 127.0.0.1:8080:8080 \
  --volume "$PWD/anki-data:/data" \
  anki-connect-server:local \
  anki-connect-server tunnel
```

## Development checks

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

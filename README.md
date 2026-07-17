# AnkiConnect Server

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

A headless server that exposes a useful subset of the AnkiConnect version 6 protocol, an
MCP server for AI assistants, and on-demand AnkiWeb synchronization. It accesses an Anki
collection directly, so the desktop application does not need to be running.

## Features

- AnkiConnect-compatible JSON API at `POST /`
- MCP tools for decks, models, notes, cards, media, packages, and synchronization
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

Set `ANKICONNECT_COLLECTION_PATH` in `.env`, then start either interface:

```bash
uv run anki-connect-server api
uv run anki-connect-server mcp
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

## Development checks

```bash
uv lock --check
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

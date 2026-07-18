# AnkiConnect Server

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

A headless server that exposes a useful subset of the AnkiConnect version 6 protocol, an
MCP server for AI assistants, and on-demand AnkiWeb synchronization. It accesses an Anki
collection directly, so the desktop application does not need to be running.

## Features

- AnkiConnect-compatible JSON API at `POST /`
- MCP tools for decks, models, notes, cards, interactive review, media, packages, and sync
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
| `CONTROL_PLANE_TUNNEL_ID` | For tunnel | — | OpenAI Secure MCP Tunnel ID |
| `CONTROL_PLANE_API_KEY` | For tunnel | — | Runtime API key with Tunnels Read + Use |
| `TUNNEL_CLIENT_PATH` | No | `tunnel-client` | Tunnel client executable name or path |

The API has no authentication layer. Keep it bound to a trusted interface or place it behind an
authenticated reverse proxy with TLS.

### Migration notes

- Use `POST /`; the former `POST /api` alias has been removed.
- Use `ANKICONNECT_COLLECTION_PATH`; the former `ANKI_COLLECTION_PATH` alias has been removed.
- `ANKICONNECT_FULL_UPLOAD` has been removed. Full collection uploads are always prohibited.

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
- Cards: `findCards`, `cardsToNotes`, `cardsInfo`, `answerCards`, `suspend`, `unsuspend`,
  `areSuspended`, `areDue`, `getIntervals`
- Media: `getMediaDirPath`, `storeMediaFile`, `retrieveMediaFile`, `deleteMediaFile`

The health endpoint is available at `GET /health`.

## MCP server

The `mcp` command runs over stdio. Its tool names are:

- Decks: `get_deck_names`, `create_deck`, `delete_decks`, `change_deck`, `get_deck_config`
- Models: `get_model_names`, `get_model_field_names`, `get_model_templates`,
  `get_model_styling`
- Notes and cards: `add_note`, `search_notes`, `delete_notes`, `find_cards`, `inspect_cards`,
  `suspend_cards`, `unsuspend_cards`, `are_due`
- Interactive review: `get_review_queue`, `get_next_review_card`, `submit_review`
- Tags and media: `get_all_tags`, `add_tags`, `remove_tags`, `store_media_file`,
  `retrieve_media_file`, `delete_media_file`
- Packages and sync: `import_package`, `export_package`, `sync`

### Synchronization

The MCP `sync` tool synchronizes collection data and media in one foreground operation. Its call
remains pending until both phases finish, and compatible MCP clients receive progress messages
while it runs. A successful result reports whether the collection had no changes, was merged, or
was replaced by a full download, together with the final media counters.

Normal synchronization can merge local changes into AnkiWeb. When Anki reports a conflict or a
remote-only collection, this server always downloads and replaces local collection data; it never
performs a full upload that replaces AnkiWeb. If AnkiWeb is empty and only an upload is possible,
the tool fails and preserves the local collection. Media continues to use Anki's normal
bidirectional merge behavior.

The HTTP compatibility actions remain available. `sync` includes collection data and media and
waits for both; `syncMedia` waits for media completion; `syncStatus` reports whether another
collection sync is required and is not a runtime progress endpoint.

### Efficient discovery and inspection

Use `search_notes` for broad discovery. It returns at most 20 short, cleaned previews by default;
use `limit` and `offset` to page through up to 100 results at a time, or set `content="fields"`
to retrieve every non-empty cleaned field for that page. Presentation HTML is removed and media
is represented by concise text markers without embedding or reading binary files.

After narrowing the result to note or card IDs, use `inspect_cards` for selected details. Its
default response contains identity, state, and scheduling only. Request any combination of
`timestamps`, `history`, or `fields`, or request `all`; history defaults to the newest 20 entries.
The tool reports missing IDs explicitly and loads fields shared by sibling cards only once.

Use `find_cards` only when a card-scoped Anki query is required, such as finding suspended cards
or selecting a particular card template. Rendered questions, answers, and binary image/audio MCP
content remain exclusive to the interactive review workflow.

The optimized tools replace several former low-level MCP tools:

| Former MCP tool | Replacement |
| --- | --- |
| `find_notes`, `get_notes_info` | `search_notes`, using `content="fields"` when needed |
| `get_cards_info` | `inspect_cards` with only the required properties |
| `cards_to_notes` | `inspect_cards` with `identity` |
| `are_suspended` | `inspect_cards` with `state` |
| `get_card_intervals` | `inspect_cards` with `scheduling` |
| `get_deck_names_and_ids` | `get_deck_names`; no MCP operation requires deck IDs |
| `get_media_dir_path` | Removed; server filesystem paths are not exposed to MCP clients |
| `get_api_version` | Removed; the AnkiConnect protocol version is not an MCP concern |
| `sync_media`, `get_sync_status` | `sync`, which includes media and waits for completion |

Their corresponding AnkiConnect HTTP actions remain supported.

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

### Interactive deck review

Ask the connected model, for example, “Review my Spanish deck with me now.” The model uses Anki's
current scheduler queue, asks one card at a time, waits for your response, compares it with the
rendered answer, and immediately records the rating before advancing. Incorrect, missing, or
materially wrong answers are rated `again`; correct or semantically equivalent answers are rated
`good`. The model uses `hard` or `easy` only when you explicitly supply that rating.

`get_next_review_card` returns the question and answer together to reduce round trips, but the MCP
instructions prohibit revealing the answer before you respond. Local card images and audio are
included as standard MCP content when supported; unavailable media remains visible in a manifest.
Review IDs are session-bound, expire after one hour, and make identical submission retries safe.

Ratings are written to the local collection after every answer. They are not sent to AnkiWeb until
you explicitly call the existing `sync` tool or `sync` API action.

For AnkiConnect clients, the equivalent compatibility action accepts the standard ease values:

```json
{
  "action": "answerCards",
  "version": 6,
  "params": {
    "answers": [
      {"cardId": 1234567890, "ease": 3}
    ]
  }
}
```

Ease values `1`, `2`, `3`, and `4` mean Again, Hard, Good, and Easy. The result contains one
boolean per input answer in the same order; a missing card produces `false`.

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

For the shortest tunnel setup, clone the repository, copy the environment template, and fill in
the two `CONTROL_PLANE_*` values:

```bash
git clone https://github.com/friedrich-de/anki-connect-server.git
cd anki-connect-server
cp .env.example .env
# Edit .env and fill CONTROL_PLANE_TUNNEL_ID and CONTROL_PLANE_API_KEY.
docker compose up --build --detach
docker compose logs --follow
```

Compose builds the image locally, reads `.env` into the container, runs `anki-connect-server
tunnel`, persists the collection under `./anki-data`, and exposes the tunnel-client UI only at
`http://127.0.0.1:8080/ui`. Check readiness with `docker compose ps`. Stop the service without
removing its data with:

```bash
docker compose down
```

The Compose file overrides `ANKICONNECT_COLLECTION_PATH` with `/data/collection.anki2`, so the
host path in `.env` is used only when running directly from the source checkout.

To run the REST API instead, build and start the image directly:

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

# AnkiConnect Server

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

> This project is a headless AnkiConnect and MCP service intended to run on a server. If you want
> a local MCP server that runs inside Anki as an add-on, use
> [`friedrich-de/mcp-ankiconnect-chatgpt`](https://github.com/friedrich-de/mcp-ankiconnect-chatgpt).

This is a substantially diverged fork of
[`glechic/anki-connect-server`](https://github.com/glechic/anki-connect-server). The upstream
project established the headless, direct-collection foundation. This fork retains that foundation
but is independently developed as an agent-first Anki service with a curated MCP interface, safe
on-demand synchronization, and containerized remote deployment. It does not require the Anki
desktop application or Qt.

## What this fork provides

- An AnkiConnect version 6 API that mining tools such as Yomitan can use in place of the desktop
  add-on: cards and their media go straight to the server, protected by an API key
- Automatic AnkiWeb synchronization after changes, so mined cards reach your other devices without
  a desktop Anki running, and a full-sync policy that never drops unsynced cards
- One `serve` process that owns the collection and runs the HTTP API, the MCP endpoint for the
  ChatGPT tunnel, and automatic sync together
- A curated, strictly typed MCP tool surface designed for AI agents rather than a one-to-one REST
  mirror
- Scheduler-backed interactive deck review with session-safe ratings and image/audio card content
- Bounded note search and sparse card inspection to avoid wasting model context
- One foreground MCP `sync` operation for collection and media, with progress reporting, that
  never replaces AnkiWeb with a full upload
- Outbound-only OpenAI Secure MCP Tunnel support for remote ChatGPT access
- Local Docker and Compose deployment with persistent collection and media storage
- Current Anki APIs, strict Pyright typing, Ruff formatting, and tested Python 3.12/3.14 support

This project implements the actions listed below; it does not claim complete parity with every
action provided by the AnkiConnect desktop add-on. Actions that need the Anki window (`gui*`) do
not exist on a headless server.

## Setup

Install [uv](https://docs.astral.sh/uv/), clone the repository, and create the environment:

```bash
git clone https://github.com/friedrich-de/anki-connect-server.git
cd anki-connect-server
uv sync --locked
cp .env.example .env
```

Set `ANKICONNECT_COLLECTION_PATH` and `ANKICONNECT_API_KEY` in `.env`, then start an interface:

```bash
uv run anki-connect-server serve            # AnkiConnect API + loopback MCP + automatic sync
uv run anki-connect-server serve --tunnel   # the same, plus OpenAI's tunnel-client for ChatGPT
uv run anki-connect-server api              # AnkiConnect API only
uv run anki-connect-server mcp              # MCP over stdio for a local MCP host
uv run anki-connect-server tunnel           # tunnel-client with a private stdio MCP, no API
```

An Anki collection must be opened by one process only. Run one of these commands per collection,
and do not open the same collection in another Anki process at the same time. `serve` exists so
that the API, MCP and sync can share one collection.

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `ANKICONNECT_COLLECTION_PATH` | Yes | — | Path to the `.anki2` collection file |
| `ANKICONNECT_PORT` | No | `8765` | API server port |
| `ANKICONNECT_BIND` | No | `127.0.0.1` | API bind address |
| `ANKICONNECT_API_KEY` | When reachable | — | Key every AnkiConnect client must send |
| `ANKICONNECT_CORS_ORIGINS` | No | — | Comma-separated web origins allowed to call the API |
| `ANKICONNECT_CORS_EXTENSIONS` | No | `true` | Allow browser-extension origins such as Yomitan's |
| `ANKICONNECT_MAX_REQUEST_BYTES` | No | 128 MiB | Largest accepted request body |
| `ANKICONNECT_BUSY_TIMEOUT` | No | `30` | Seconds a request waits while a sync holds the collection |
| `ANKICONNECT_ANKIWEB_USER` | For sync | — | AnkiWeb username |
| `ANKICONNECT_ANKIWEB_PASS` | For sync | — | AnkiWeb password |
| `ANKICONNECT_ANKIWEB_URL` | No | AnkiWeb | Custom sync-server URL |
| `ANKICONNECT_AUTO_SYNC` | No | `false` | Sync with AnkiWeb by itself (`api` and `serve`) |
| `ANKICONNECT_AUTO_SYNC_DELAY` | No | `30` | Quiet seconds after a change before syncing |
| `ANKICONNECT_AUTO_SYNC_INTERVAL` | No | `600` | Seconds between syncs that pull changes; `0` turns them off |
| `ANKICONNECT_MCP_PORT` | No | `8766` | Loopback port of the MCP endpoint that `serve` runs |
| `CONTROL_PLANE_TUNNEL_ID` | For tunnel | — | OpenAI Secure MCP Tunnel ID |
| `CONTROL_PLANE_API_KEY` | For tunnel | — | Runtime API key with Tunnels Read + Use |
| `TUNNEL_CLIENT_PATH` | No | `tunnel-client` | Tunnel client executable name or path |

### Security

Set `ANKICONNECT_API_KEY` whenever anything other than the local machine can reach the API. Like
AnkiConnect, every request must then carry the key as `"key"` in its JSON body (an
`Authorization: Bearer` header works as well); only `requestPermission` answers without it, so
clients can find out that a key is needed. A missing or wrong key gets AnkiConnect's
`valid api key must be provided` error. Without a key the server logs a warning when it listens on
anything other than loopback. Put the server behind TLS, for example a reverse proxy or a
Cloudflare Tunnel, before you send the key over the internet.

Browsers only let a web page call the API when its origin is allowed. Browser extensions are
allowed by default, as in AnkiConnect; add the origins of web pages that call the API directly to
`ANKICONNECT_CORS_ORIGINS`. Server-side clients are not affected by CORS.

Because the server's files are not the client's files, a few actions are narrower than in the
desktop add-on: `storeMediaFile` accepts `data` (base64) only and refuses `path` and `url`, and
`importPackage` and `exportPackage` accept only paths inside the collection's folder.

### Migration notes

- The Docker image now runs `anki-connect-server serve`, and Compose runs `serve --tunnel`, so the
  AnkiConnect API is available next to the ChatGPT tunnel. Set `ANKICONNECT_API_KEY` first.
- A full sync that AnkiWeb asks for no longer replaces unsynced local changes; see
  [Synchronization](#synchronization).
- A request without `version` gets version 4 replies (bare results), as in AnkiConnect. Send
  `"version": 6` for the `{"result": ..., "error": ...}` envelope.
- Use `POST /`; the former `POST /api` alias has been removed.
- Use `ANKICONNECT_COLLECTION_PATH`; the former `ANKI_COLLECTION_PATH` alias has been removed.
- `ANKICONNECT_FULL_UPLOAD` has been removed. Full collection uploads are always prohibited.

## AnkiConnect-compatible API

Send version 6 requests to `POST /`:

```json
{
  "action": "deckNames",
  "version": 6,
  "key": "your-api-key",
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

Replies follow AnkiConnect: errors are always enveloped, results are bare for versions below 5,
`multi` answers each action in its own version, and the error texts are AnkiConnect's (for
example `cannot create note because it is a duplicate` or `deck was not found: X`). The server
accepts any content type, so browser clients may send `text/plain` to avoid a CORS preflight.

Example:

```bash
curl --request POST http://localhost:8765/ \
  --header 'Content-Type: application/json' \
  --data '{"action":"createDeck","version":6,"key":"your-api-key","params":{"deck":"Spanish"}}'
```

Supported actions are:

- General: `version`, `requestPermission`, `apiReflect`, `multi`, `sync`, `syncStatus`,
  `syncMedia`, `importPackage`, `exportPackage`
- Decks: `deckNames`, `deckNamesAndIds`, `deckNameFromId`, `getDecks`, `createDeck`, `changeDeck`,
  `deleteDecks`, `getDeckConfig`, `saveDeckConfig`, `setDeckConfigId`, `cloneDeckConfigId`,
  `removeDeckConfigId`
- Models: `modelNames`, `modelNamesAndIds`, `modelNameFromId`, `modelFieldNames`,
  `modelFieldsOnTemplates`, `createModel`, `modelTemplates`, `modelStyling`,
  `updateModelTemplates`, `updateModelStyling`
- Notes: `addNote`, `addNotes`, `canAddNote`, `canAddNotes`, `canAddNoteWithErrorDetail`,
  `canAddNotesWithErrorDetail`, `updateNoteFields`, `updateNote`, `updateNoteTags`, `getNoteTags`,
  `addTags`, `removeTags`, `getTags`, `findNotes`, `notesInfo`, `deleteNotes`
- Cards: `findCards`, `cardsToNotes`, `cardsInfo`, `answerCards`, `suspend`, `unsuspend`,
  `areSuspended`, `areDue`, `getIntervals`
- Media: `getMediaDirPath`, `getMediaFilesNames`, `storeMediaFile`, `retrieveMediaFile`,
  `deleteMediaFile`

`addNote` and `addNotes` follow AnkiConnect's duplicate options (`allowDuplicate`,
`duplicateScope` with `deckName` and `checkChildren`, `checkAllModels`) and take `audio`, `video`
and `picture` attachments as base64 `data`; the stored media is referenced in the named fields.
`addNotes` adds all notes or none. `storeMediaFile` returns the name it stored.

`GET /health` reports `{"status": "healthy", "autoSync": "<state>"}`, where the state is `off`,
`starting`, `syncing`, `ok`, `failing` or `blocked`. `GET /` answers `AnkiConnect v.6`, as the
add-on does.

### Using it from Yomitan

In Yomitan's settings, under Anki, set the AnkiConnect server address to this server (for example
`https://anki.example.org`), paste the API key into the API key field, and turn on Anki
integration. Yomitan then adds cards, their audio and their pictures straight to the server, and
automatic sync takes them to AnkiWeb. Duplicate checks, the deck and note-type lists and
"view added note" lookups work as with the add-on; opening a note in the Anki browser does not,
since there is no Anki window.

## MCP server

The `mcp` command runs over stdio. Its tool names are:

- Decks: `get_deck_names`, `create_deck`, `delete_decks`, `change_deck`, `get_deck_config`
- Models: `get_model_names`, `get_model_field_names`, `get_model_templates`,
  `get_model_styling`
- Notes and cards: `add_note`, `search_notes`, `update_note_fields`, `delete_notes`, `find_cards`,
  `inspect_cards`, `suspend_cards`, `unsuspend_cards`, `are_due`
- Interactive review: `get_review_queue`, `get_next_review_card`, `submit_review`
- Tags and media: `get_all_tags`, `add_tags`, `remove_tags`, `store_media_file`,
  `retrieve_media_file`, `delete_media_file`
- Packages and sync: `import_package`, `export_package`, `sync`

### Synchronization

The MCP `sync` tool synchronizes collection data and media in one foreground operation. Its call
remains pending until both phases finish, and compatible MCP clients receive progress messages
while it runs. A successful result reports whether the collection had no changes, was merged, or
was replaced by a full download, together with the final media counters.

Normal synchronization merges local changes into AnkiWeb and AnkiWeb's changes into the server.
The server never performs a full upload that replaces AnkiWeb; if AnkiWeb is empty and only an
upload is possible, the sync fails and preserves the local collection. When AnkiWeb asks for a full
sync (after a schema change elsewhere, for example), the server downloads AnkiWeb's collection only
if it holds no unsynced changes of its own. If it does, such as cards mined since the last sync, it
stops with a conflict error instead of dropping them. Sync those cards from somewhere else first
(for example export them), or call `sync` with `discard_local_changes` (MCP) or
`"discardLocalChanges": true` (HTTP) to accept AnkiWeb's copy. Media uses Anki's normal
bidirectional merge.

The HTTP compatibility actions remain available. `sync` includes collection data and media and
waits for both; `syncMedia` waits for media completion; `syncStatus` reports whether another
collection sync is required and is not a runtime progress endpoint.

#### Automatic sync

With `ANKICONNECT_AUTO_SYNC=true` and AnkiWeb credentials, `serve` and `api` sync by themselves:
once at start, `ANKICONNECT_AUTO_SYNC_DELAY` seconds after the collection was last changed (and at
most five times that delay into a long mining session), and every `ANKICONNECT_AUTO_SYNC_INTERVAL`
seconds to pull reviews and edits made on other devices. Failures are retried with growing pauses
of up to 15 minutes. A full-sync conflict as described above pauses automatic sync (`blocked` in
`/health`) and is retried every ten minutes until it is resolved. While a sync runs, other requests
wait for it, up to `ANKICONNECT_BUSY_TIMEOUT` seconds, and then get a "collection is busy" error.

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

### Editing note fields

Anki cards render fields stored on their parent note. To edit card content, first use
`search_notes(content="fields")`, or resolve a known card with
`inspect_cards(properties=["identity", "fields"])`. Then call `update_note_fields` with the note
ID and only the fields the user requested:

```json
{
  "note_id": 1700000000000,
  "fields": {
    "Back": "Corrected answer with <b>verbatim Anki HTML</b>"
  }
}
```

Omitted fields remain unchanged, while an empty string clears a field. Values are stored exactly
as supplied; editing a note changes the rendered content of all sibling cards and uses Anki's
native behavior for generated cloze cards without intentionally changing review scheduling. To
reference new local media, call `store_media_file` first and use its filename in the field. Edits
remain local until the next sync, automatic or by `sync`.

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
Review IDs belong to the collection (one server serves one user, and MCP clients on the stateless
2026-07-28 protocol have no lasting session), expire after one hour, and make identical submission
retries safe.

Ratings are written to the local collection after every answer. They reach AnkiWeb with the next
automatic sync, or when you call the `sync` tool or `sync` API action.

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

`serve --tunnel` and `tunnel` make the MCP server reachable through OpenAI's outbound-only
[Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels). Both load
the tunnel ID and runtime key from `.env` and keep the key out of command-line arguments.

- `serve --tunnel` runs the MCP server over HTTP on `127.0.0.1:8766/mcp` inside the same process
  as the AnkiConnect API and points the official `tunnel-client` at it. The client is restarted
  with growing pauses if it exits. Use this when you also want the API.
- `tunnel` lets `tunnel-client` supervise `anki-connect-server mcp` as its private stdio process.
  It runs no AnkiConnect API, and the collection must not be open anywhere else meanwhile.

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

Keep the second command (or `serve --tunnel`) running for connector discovery and tool calls.
The tunnel-client health and administration UI uses `http://127.0.0.1:8080/ui` by default. The MCP
server listens on stdio or on loopback only, and the tunnel opens no inbound internet listener; its
control-plane traffic uses outbound HTTPS.

## Local Docker use

For the shortest setup, clone the repository, copy the environment template, and fill in the API
key, the AnkiWeb login with `ANKICONNECT_AUTO_SYNC=true`, and the two `CONTROL_PLANE_*` values:

```bash
git clone https://github.com/friedrich-de/anki-connect-server.git
cd anki-connect-server
cp .env.example .env
# Edit .env: ANKICONNECT_API_KEY, AnkiWeb login, ANKICONNECT_AUTO_SYNC, CONTROL_PLANE_*.
docker compose up --build --detach
docker compose logs --follow
```

Compose builds the image locally, reads `.env` into the container, runs `anki-connect-server serve
--tunnel`, persists the collection under `./anki-data`, publishes the AnkiConnect API at
`http://127.0.0.1:8765` and the tunnel-client UI at `http://127.0.0.1:8080/ui`, both on host
loopback only. Put a TLS reverse proxy or a Cloudflare Tunnel in front of port 8765 to reach it from
other machines. Without the ChatGPT tunnel, change the Compose command to `["anki-connect-server",
"serve"]`. Check readiness with `docker compose ps`. Stop the service without removing its data
with:

```bash
docker compose down
```

The Compose file overrides `ANKICONNECT_COLLECTION_PATH` with `/data/collection.anki2`, so the
host path in `.env` is used only when running directly from the source checkout.

To run the image directly, build and start it; it runs `serve` (API and loopback MCP) by default:

```bash
docker build --tag anki-connect-server:local .
mkdir -p anki-data
docker run --rm \
  --publish 127.0.0.1:8765:8765 \
  --env ANKICONNECT_API_KEY=your-api-key \
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

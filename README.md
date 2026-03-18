# AnkiConnect Server

Headless AnkiConnect-compatible REST API server with AnkiWeb sync support.

## Features

- Full AnkiConnect API compatibility (version 6)
- Headless operation - no Qt/GUI required
- AnkiWeb sync support
- Custom sync server support (optional)
- Built with FastAPI and uvicorn

## Requirements

- Python 3.9+
- uv (package manager)

## Installation

```bash
# Clone and install dependencies
cd anki-connect-server
uv pip install -e .
```

## Configuration

Set environment variables before running:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANKI_COLLECTION_PATH` | Yes | - | Path to `.anki21` collection file |
| `ANKICONNECT_PORT` | No | 8765 | Server port |
| `ANKICONNECT_BIND` | No | 127.0.0.1 | Bind address |
| `ANKICONNECT_ANKIWEB_USER` | No | - | AnkiWeb username (for sync) |
| `ANKICONNECT_ANKIWEB_PASS` | No | - | AnkiWeb password (for sync) |
| `ANKIWEB_URL` | No | - | Custom sync server URL (default: AnkiWeb) |

## Usage

### Development

```bash
uv run uvicorn main:app --reload --port 8765
```

### Production

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8765
```

### Docker

```dockerfile
FROM python:3.11-slim
RUN pip install uv
WORKDIR /app
COPY . .
RUN uv pip install --system -e .
ENV ANKI_COLLECTION_PATH=/data/collection.anki21
EXPOSE 8765
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8765"]
```

## API Examples

### Get deck names

```bash
curl -X POST http://localhost:8765 \
  -H "Content-Type: application/json" \
  -d '{"action": "deckNames", "version": 6}'
```

### Create a deck

```bash
curl -X POST http://localhost:8765 \
  -H "Content-Type: application/json" \
  -d '{"action": "createDeck", "version": 6, "params": {"deck": "My New Deck"}}'
```

### Add a note

```bash
curl -X POST http://localhost:8765 \
  -H "Content-Type: application/json" \
  -d '{
    "action": "addNote",
    "version": 6,
    "params": {
      "note": {
        "deckName": "Default",
        "modelName": "Basic",
        "fields": {
          "Front": "Hello",
          "Back": "World"
        },
        "tags": ["api"]
      }
    }
  }'
```

### Sync with AnkiWeb

```bash
curl -X POST http://localhost:8765 \
  -H "Content-Type: application/json" \
  -d '{"action": "sync", "version": 6}'
```

## Supported Actions

### Misc
- `version`, `sync`, `multi`, `importPackage`, `exportPackage`

### Decks
- `deckNames`, `deckNamesAndIds`, `createDeck`, `deleteDecks`, `changeDeck`
- `getDeckConfig`, `saveDeckConfig`, `setDeckConfigId`, `cloneDeckConfigId`, `removeDeckConfigId`

### Models
- `modelNames`, `modelNamesAndIds`, `modelFieldNames`, `modelFieldsOnTemplates`
- `createModel`, `modelTemplates`, `modelStyling`, `updateModelTemplates`, `updateModelStyling`

### Notes
- `addNote`, `addNotes`, `canAddNotes`, `updateNoteFields`
- `findNotes`, `notesInfo`, `deleteNotes`
- `addTags`, `removeTags`, `getTags`

### Cards
- `findCards`, `cardsToNotes`, `cardsInfo`
- `suspend`, `unsuspend`, `areSuspended`, `areDue`, `getIntervals`

### Media
- `storeMediaFile`, `retrieveMediaFile`, `deleteMediaFile`, `getMediaDirPath`

## License

GNU AGPL v3
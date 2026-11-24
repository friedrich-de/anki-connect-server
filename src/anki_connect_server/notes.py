"""AnkiConnect-compatible note validation, creation, updates, and inline media.

The error strings and duplicate rules follow the AnkiConnect add-on's legacy API,
because clients such as Yomitan recognize existing notes by them.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, cast

from anki.collection import AddNoteRequest, StripHtmlMode
from anki.decks import DeckId
from anki.errors import NotFoundError
from anki.notes import Note, NoteFieldsCheckResult, NoteId
from anki.utils import checksum

from anki_connect_server.types import JsonObject, JsonValue

if TYPE_CHECKING:
    from anki_connect_server.anki_wrapper import AnkiWrapper

EMPTY_ERROR = "cannot create note because it is empty"
DUPLICATE_ERROR = "cannot create note because it is a duplicate"
UNKNOWN_ERROR = "cannot create note for unknown reason"
UNSUPPORTED_MEDIA_SOURCE = (
    "media from a path or URL is not supported by this server; send the file as base64 data"
)

_NORMAL = int(NoteFieldsCheckResult.NORMAL)
_EMPTY = int(NoteFieldsCheckResult.EMPTY)
_DUPLICATE = int(NoteFieldsCheckResult.DUPLICATE)

type MediaKind = Literal["audio", "video", "picture"]
_MEDIA_KINDS: tuple[MediaKind, ...] = ("audio", "video", "picture")


class NoteError(ValueError):
    """A note request that cannot be carried out, with an AnkiConnect message."""


def parse_bool(value: JsonValue, name: str, default: bool = False) -> bool:
    """Accept booleans, 0/1, and the strings true/false/0/1, as AnkiConnect does."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "0", "1"):
        return value.strip().lower() in ("true", "1")
    raise NoteError(f'option parameter "{name}" must be boolean')


def parse_int(value: JsonValue, name: str) -> int:
    """Accept integers, integral floats, and decimal strings."""
    if isinstance(value, bool):
        raise NoteError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    raise NoteError(f"{name} must be an integer")


def parse_tags(value: JsonValue) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list) and all(isinstance(tag, str) for tag in value):
        return [tag for tag in cast(list[str], value) if tag.strip()]
    raise NoteError("tags must be a list of strings")


def _field_value(value: JsonValue, name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise NoteError(f'field "{name}" must be a string')
    return value


def _loose(name: str) -> str:
    return name.strip().casefold()


def resolve_field(field_names: Sequence[str], name: str) -> str | None:
    """Return the note type field a client name refers to, if exactly one fits."""
    if name in field_names:
        return name
    matches = [field_name for field_name in field_names if _loose(field_name) == _loose(name)]
    return matches[0] if len(matches) == 1 else None


def match_fields(field_names: Sequence[str], supplied: Mapping[str, JsonValue]) -> dict[str, str]:
    """Map client field names onto note type fields.

    Exact names win; otherwise names match case-insensitively and ignoring
    surrounding whitespace. Unknown names are ignored, and two different loose
    names for one field are refused.
    """
    result = {
        name: _field_value(value, name) for name, value in supplied.items() if name in field_names
    }
    loose: dict[str, str] = {}
    for name, value in supplied.items():
        if name in field_names:
            continue
        target = resolve_field(field_names, name)
        if target is None or target in result:
            continue
        if target in loose:
            raise NoteError(f'conflicting values for field "{target}"')
        loose[target] = _field_value(value, name)
    result.update(loose)
    return result


@dataclass
class MediaAttachment:
    kind: MediaKind
    filename: str
    data: bytes
    fields: list[str]
    skip_hash: str | None = None
    delete_existing: bool = False

    def reference(self, filename: str) -> str:
        if self.kind == "picture":
            return f'<img src="{filename}">'
        return f"[sound:{filename}]"


def decode_base64(data: str) -> bytes:
    try:
        return base64.b64decode("".join(data.split()), validate=True)
    except (binascii.Error, ValueError) as error:
        raise NoteError("media data must be valid base64") from error


def _parse_attachment(kind: MediaKind, value: JsonValue) -> MediaAttachment:
    if not isinstance(value, dict):
        raise NoteError(f"{kind} must contain objects")
    filename = value.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise NoteError(f"{kind} filename must be a nonempty string")
    data = value.get("data")
    if not isinstance(data, str) or not data:
        if value.get("path") or value.get("url"):
            raise NoteError(UNSUPPORTED_MEDIA_SOURCE)
        raise NoteError(f"{kind} needs base64 data")
    targets = value.get("fields")
    if targets is None:
        fields: list[str] = []
    elif isinstance(targets, str):
        fields = [targets]
    elif isinstance(targets, list) and all(isinstance(item, str) for item in targets):
        fields = cast(list[str], targets)
    else:
        raise NoteError(f"{kind} fields must be a string or a list of strings")
    skip_hash = value.get("skipHash")
    return MediaAttachment(
        kind=kind,
        filename=filename,
        data=decode_base64(data),
        fields=fields,
        skip_hash=skip_hash if isinstance(skip_hash, str) and skip_hash else None,
        delete_existing=parse_bool(value.get("deleteExisting"), "deleteExisting"),
    )


def parse_attachments(source: JsonObject) -> list[MediaAttachment]:
    attachments: list[MediaAttachment] = []
    for kind in _MEDIA_KINDS:
        value = source.get(kind)
        if value is None:
            continue
        items = value if isinstance(value, list) else [value]
        attachments.extend(_parse_attachment(kind, item) for item in items)
    return attachments


def media_basename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in (".", ".."):
        raise NoteError("media filename must name a file")
    return name


def store_media(
    wrapper: AnkiWrapper,
    filename: str,
    data: bytes,
    *,
    delete_existing: bool,
    skip_hash: str | None = None,
) -> str | None:
    """Store media bytes and return the actual file name Anki used.

    Returns None when skip_hash equals the MD5 digest of the data, as AnkiConnect
    does. Without delete_existing, a name that is taken by different content is
    renamed by Anki; with it, the existing file is replaced.
    """
    if skip_hash is not None and hashlib.md5(data).hexdigest() == skip_hash.lower():  # noqa: S324
        return None
    name = media_basename(filename)
    path = wrapper.media_path(name)
    if delete_existing and path.exists():
        wrapper.col.media.trash_files([name])
    return wrapper.col.media.write_data(name, data)


@dataclass
class DuplicateOptions:
    allow_duplicate: bool = False
    scope: str = "collection"
    deck_name: str | None = None
    check_children: bool = False
    check_all_models: bool = False

    @classmethod
    def parse(cls, value: JsonValue) -> DuplicateOptions:
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise NoteError("options must be an object")
        scope_options = value.get("duplicateScopeOptions")
        if scope_options is None:
            scope_options = {}
        if not isinstance(scope_options, dict):
            raise NoteError("duplicateScopeOptions must be an object")
        deck_name = scope_options.get("deckName")
        scope = value.get("duplicateScope")
        return cls(
            allow_duplicate=parse_bool(value.get("allowDuplicate"), "allowDuplicate"),
            scope=scope if isinstance(scope, str) else "collection",
            deck_name=deck_name if isinstance(deck_name, str) else None,
            check_children=parse_bool(
                scope_options.get("checkChildren"), "duplicateScopeOptions.checkChildren"
            ),
            check_all_models=parse_bool(
                scope_options.get("checkAllModels"), "duplicateScopeOptions.checkAllModels"
            ),
        )


@dataclass
class PreparedNote:
    note: Note
    deck_id: DeckId
    base_fields: dict[str, str]
    options: DuplicateOptions
    attachments: list[MediaAttachment] = field(default_factory=list[MediaAttachment])

    def apply_fields(self, references: Mapping[str, list[str]]) -> None:
        """Reset the note to its text fields, then append media references."""
        for name in self.note.keys():  # noqa: SIM118 - Note is not a dict
            self.note[name] = self.base_fields.get(name, "")
        for name, values in references.items():
            self.note[name] += "".join(values)

    def references(self, names: Sequence[str | None]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        field_names = self.note.keys()
        for attachment, name in zip(self.attachments, names, strict=True):
            if name is None:
                continue
            for target in attachment.fields:
                resolved = resolve_field(field_names, target)
                if resolved is not None:
                    result.setdefault(resolved, []).append(attachment.reference(name))
        return result

    def provisional_references(self) -> dict[str, list[str]]:
        return self.references([media_basename(item.filename) for item in self.attachments])


def prepare_note(wrapper: AnkiWrapper, source: JsonValue) -> PreparedNote:
    if not isinstance(source, dict):
        raise NoteError("note must be an object")
    model_name = source.get("modelName")
    deck_name = source.get("deckName")
    if not isinstance(model_name, str):
        raise NoteError("modelName must be a string")
    if not isinstance(deck_name, str):
        raise NoteError("deckName must be a string")
    col = wrapper.col
    model = col.models.by_name(model_name)
    if model is None:
        raise NoteError(f"model was not found: {model_name}")
    deck_id = col.decks.id_for_name(deck_name)
    if deck_id is None:
        raise NoteError(f"deck was not found: {deck_name}")
    fields = source.get("fields")
    if fields is None:
        fields = {}
    if not isinstance(fields, dict):
        raise NoteError("fields must be an object")
    note = Note(col, model)
    prepared = PreparedNote(
        note=note,
        deck_id=deck_id,
        base_fields=match_fields(note.keys(), fields),
        options=DuplicateOptions.parse(source.get("options")),
        attachments=parse_attachments(source),
    )
    note.tags = parse_tags(source.get("tags"))
    prepared.apply_fields(prepared.provisional_references())
    return prepared


def field_checksum(wrapper: AnkiWrapper, text: str) -> int:
    """Anki's checksum of a first field, as stored in the notes table.

    ``anki.utils.field_checksum`` needs Anki Desktop's language setup, so the
    collection's own backend strips the HTML here.
    """
    stripped = wrapper.col._backend.strip_html(  # pyright: ignore[reportPrivateUsage]
        text=text, mode=StripHtmlMode.PRESERVE_MEDIA_FILENAMES
    )
    return int(checksum(stripped)[:8], 16)


def duplicate_or_empty(wrapper: AnkiWrapper, prepared: PreparedNote) -> int:
    """Return Anki's field check state for a new note under the requested scope."""
    options = prepared.options
    note = prepared.note
    if options.scope != "deck" and not options.check_all_models:
        return int(note.fields_check())
    first = note.fields[0] if note.fields else ""
    if not first.strip():
        return _EMPTY
    col = wrapper.col
    deck_ids: set[int] | None = None
    if options.scope == "deck":
        deck_id = prepared.deck_id
        if options.deck_name is not None:
            named = col.decks.id_for_name(options.deck_name)
            if named is None:
                return _NORMAL
            deck_id = named
        if options.check_children:
            deck_ids = {int(value) for value in col.decks.deck_and_child_ids(deck_id)}
        else:
            deck_ids = {int(deck_id)}
    query = "select id from notes where csum = ?"
    arguments: list[int] = [field_checksum(wrapper, first)]
    if not options.check_all_models:
        query += " and mid = ?"
        arguments.append(int(note.mid))
    database = wrapper.db()
    for note_id in database.list(query, *arguments):
        if deck_ids is None:
            return _DUPLICATE
        card_decks = database.list("select did from cards where nid = ?", note_id)
        if any(int(value) in deck_ids for value in card_decks):
            return _DUPLICATE
    return _NORMAL


def check_note(wrapper: AnkiWrapper, prepared: PreparedNote) -> str | None:
    state = duplicate_or_empty(wrapper, prepared)
    if state == _EMPTY:
        return EMPTY_ERROR
    if state == _DUPLICATE:
        return None if prepared.options.allow_duplicate else DUPLICATE_ERROR
    if state != _NORMAL:
        return UNKNOWN_ERROR
    return None


def validate_note(wrapper: AnkiWrapper, source: JsonValue) -> JsonObject:
    """Return AnkiConnect's canAdd/error record without changing anything."""
    try:
        error = check_note(wrapper, prepare_note(wrapper, source))
    except NoteError as exc:
        error = str(exc)
    return {"canAdd": True} if error is None else {"canAdd": False, "error": error}


def _store_attachments(wrapper: AnkiWrapper, prepared: PreparedNote) -> None:
    names = [
        store_media(
            wrapper,
            item.filename,
            item.data,
            delete_existing=item.delete_existing,
            skip_hash=item.skip_hash,
        )
        for item in prepared.attachments
    ]
    prepared.apply_fields(prepared.references(names))


def add_note(wrapper: AnkiWrapper, source: JsonValue) -> int:
    prepared = prepare_note(wrapper, source)
    error = check_note(wrapper, prepared)
    if error is not None:
        raise NoteError(error)
    _store_attachments(wrapper, prepared)
    wrapper.col.add_note(prepared.note, prepared.deck_id)
    return int(prepared.note.id)


def _batch_key(wrapper: AnkiWrapper, prepared: PreparedNote) -> tuple[object, ...]:
    note = prepared.note
    first = note.fields[0] if note.fields else ""
    model: object = None if prepared.options.check_all_models else int(note.mid)
    deck: object = int(prepared.deck_id) if prepared.options.scope == "deck" else None
    return (model, deck, field_checksum(wrapper, first))


def add_notes(wrapper: AnkiWrapper, sources: Sequence[JsonValue]) -> list[int]:
    """Add every note in one collection transaction, or none of them.

    Any failed check rejects the batch with the list of error messages in input
    order, as AnkiConnect does; duplicates inside the batch count as duplicates.
    """
    prepared: list[PreparedNote] = []
    errors: dict[int, str] = {}
    seen: set[tuple[object, ...]] = set()
    for index, source in enumerate(sources):
        try:
            item = prepare_note(wrapper, source)
        except NoteError as exc:
            errors[index] = str(exc)
            continue
        error = check_note(wrapper, item)
        key = _batch_key(wrapper, item)
        if error is None and not item.options.allow_duplicate and key in seen:
            error = DUPLICATE_ERROR
        seen.add(key)
        if error is not None:
            errors[index] = error
        prepared.append(item)
    if errors:
        raise NoteError(str([errors[index] for index in sorted(errors)]))
    for item in prepared:
        _store_attachments(wrapper, item)
    if prepared:
        wrapper.col.add_notes(
            [AddNoteRequest(note=item.note, deck_id=item.deck_id) for item in prepared]
        )
    return [int(item.note.id) for item in prepared]


def _get_note(wrapper: AnkiWrapper, value: JsonValue) -> Note:
    note_id = parse_int(value, "note id")
    try:
        return wrapper.col.get_note(NoteId(note_id))
    except NotFoundError as error:
        raise NoteError(f"note was not found: {note_id}") from error


def update_note(wrapper: AnkiWrapper, source: JsonValue, *, include_tags: bool) -> None:
    """Apply supplied fields, inline media, and (optionally) tags in one note update.

    updateNoteFields ignores tags, as AnkiConnect does, because clients such as
    Yomitan spread their whole note input into it. updateNote replaces the tags
    when they are supplied.
    """
    if not isinstance(source, dict):
        raise NoteError("note must be an object")
    note = _get_note(wrapper, source.get("id"))
    supplied_fields = source.get("fields")
    if supplied_fields is not None and not isinstance(supplied_fields, dict):
        raise NoteError("fields must be an object")
    attachments = parse_attachments(source)
    supplied_tags = source.get("tags") if include_tags else None
    tags = parse_tags(supplied_tags) if supplied_tags is not None else None
    if supplied_fields is None and not attachments and tags is None:
        raise NoteError(
            "note must contain fields or tags" if include_tags else "fields are required"
        )

    field_names = note.keys()
    for name, value in match_fields(field_names, supplied_fields or {}).items():
        note[name] = value
    for item in attachments:
        name = store_media(
            wrapper,
            item.filename,
            item.data,
            delete_existing=item.delete_existing,
            skip_hash=item.skip_hash,
        )
        if name is None:
            continue
        for target in item.fields:
            resolved = resolve_field(field_names, target)
            if resolved is not None:
                note[resolved] += item.reference(name)
    if tags is not None:
        note.tags = tags
    wrapper.col.update_note(note)


def set_note_tags(wrapper: AnkiWrapper, note_value: JsonValue, tags_value: JsonValue) -> None:
    note = _get_note(wrapper, note_value)
    note.tags = parse_tags(tags_value)
    wrapper.col.update_note(note)


def note_tags(wrapper: AnkiWrapper, value: JsonValue) -> list[str]:
    return list(_get_note(wrapper, value).tags)


def notes_info(wrapper: AnkiWrapper, note_ids: Sequence[int]) -> list[JsonObject]:
    """Return AnkiConnect note records in input order; a missing note is {}."""
    col = wrapper.col
    profile = wrapper.collection_path.stem
    result: list[JsonObject] = []
    for note_id in note_ids:
        try:
            note = col.get_note(NoteId(note_id))
        except NotFoundError:
            result.append({})
            continue
        model = col.models.get(note.mid)
        fields: JsonObject = {
            name: {"value": value, "order": index}
            for index, (name, value) in enumerate(note.items())
        }
        result.append(
            {
                "noteId": int(note.id),
                "profile": profile,
                "modelName": str(model["name"]) if model is not None else "",
                "tags": list(note.tags),
                "fields": fields,
                "mod": int(note.mod),
                "cards": [int(card_id) for card_id in note.card_ids()],
            }
        )
    return result

"""AnkiConnect legacy actions and request handling.

Handlers are plain functions that touch the collection; callers run them in a
worker thread while holding the collection gate (see ``gate.py``).
"""

import fnmatch
import logging
import re
from collections.abc import Callable
from typing import cast

from anki_connect_server import ANKICONNECT_API_VERSION
from anki_connect_server import notes as note_actions
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.types import (
    CardAnswerInput,
    CardTemplateInput,
    JsonObject,
    JsonValue,
    ModelStylingUpdate,
    ModelTemplateUpdate,
)

logger = logging.getLogger(__name__)

LEGACY_DEFAULT_VERSION = 4
MAX_MULTI_DEPTH = 16
API_KEY_ERROR = "valid api key must be provided"
UNSUPPORTED_ACTION = "unsupported action"


class ValidationError(ValueError):
    pass


class UnsupportedActionError(ValueError):
    pass


def require_params(params: JsonObject, *required_keys: str) -> None:
    missing = [key for key in required_keys if key not in params or params[key] is None]
    if missing:
        raise ValidationError(f"Missing required parameters: {', '.join(missing)}")


def _get_str(params: JsonObject, key: str, default: str | None = None) -> str:
    value = params.get(key, default)
    if value is None and default is not None:
        value = default
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    return value


def _get_optional_str(params: JsonObject, key: str) -> str | None:
    value = params.get(key)
    if value is not None and not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    return value


def _get_bool(params: JsonObject, key: str, default: bool = False) -> bool:
    try:
        return note_actions.parse_bool(params.get(key), key, default)
    except note_actions.NoteError as error:
        raise ValidationError(f"{key} must be a boolean") from error


def _as_int(value: JsonValue) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    return None


def _get_int(params: JsonObject, key: str, default: int | None = None) -> int:
    value = params.get(key, default)
    if value is None and default is not None:
        value = default
    number = _as_int(value)
    if number is None:
        raise ValidationError(f"{key} must be an integer")
    return number


def _get_object(params: JsonObject, key: str, *, required: bool = False) -> JsonObject:
    if required:
        require_params(params, key)
    value = params.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"{key} must be an object")
    return value


def _get_list(params: JsonObject, key: str, *, required: bool = False) -> list[JsonValue]:
    if required:
        require_params(params, key)
    value = params.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{key} must be a list")
    return value


def _get_id_list(params: JsonObject, key: str, *, required: bool = False) -> list[int]:
    """Read a list of IDs; a single ID and decimal strings are accepted."""
    if required:
        require_params(params, key)
    value = params.get(key)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    result: list[int] = []
    for item in values:
        number = _as_int(item)
        if number is None:
            raise ValidationError(f"{key} must contain only integers")
        result.append(number)
    return result


def _get_str_list(params: JsonObject, key: str, *, required: bool = False) -> list[str]:
    if required:
        require_params(params, key)
    value = params.get(key)
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    if any(not isinstance(item, str) for item in values):
        raise ValidationError(f"{key} must contain only strings")
    return cast(list[str], values)


def _string_map(value: JsonValue, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(item, str) for item in value.values()):
        raise ValidationError(f"{name} must be an object containing string values")
    return {key: item for key, item in value.items() if isinstance(item, str)}


def _parse_card_templates(params: JsonObject) -> list[CardTemplateInput]:
    result: list[CardTemplateInput] = []
    for value in _get_list(params, "cardTemplates", required=True):
        if not isinstance(value, dict):
            raise ValidationError("cardTemplates must contain only objects")
        result.append(
            CardTemplateInput(
                Name=_get_str(value, "Name", ""),
                Front=_get_str(value, "Front", ""),
                Back=_get_str(value, "Back", ""),
            )
        )
    return result


def _parse_card_answers(params: JsonObject) -> list[CardAnswerInput]:
    require_params(params, "answers")
    if set(params) != {"answers"}:
        raise ValidationError("answerCards params must contain exactly answers")
    answers: list[CardAnswerInput] = []
    for value in _get_list(params, "answers", required=True):
        if not isinstance(value, dict):
            raise ValidationError("answers must contain only objects")
        if set(value) != {"cardId", "ease"}:
            raise ValidationError("each answer must contain exactly cardId and ease")
        card_id = _get_int(value, "cardId")
        ease = _get_int(value, "ease")
        if ease not in (1, 2, 3, 4):
            raise ValidationError("ease must be one of 1, 2, 3, or 4")
        answers.append(CardAnswerInput(cardId=card_id, ease=ease))
    return answers


def _parse_template_update(params: JsonObject) -> ModelTemplateUpdate:
    model = _get_object(params, "model", required=True)
    name = _get_str(model, "name")
    raw_templates = _get_object(model, "templates", required=True)
    templates: dict[str, dict[str, str]] = {}
    for template_name, value in raw_templates.items():
        templates[template_name] = _string_map(value, f"templates.{template_name}")
    return ModelTemplateUpdate(name=name, templates=templates)


def _parse_styling_update(params: JsonObject) -> ModelStylingUpdate:
    model = _get_object(params, "model", required=True)
    return ModelStylingUpdate(name=_get_str(model, "name"), css=_get_str(model, "css"))


def _note_list(params: JsonObject) -> list[JsonValue]:
    require_params(params, "notes")
    value = params["notes"]
    if not isinstance(value, list):
        raise ValidationError("notes must be a list")
    return value


# Miscellaneous


def handle_version(_wrapper: AnkiWrapper, _params: JsonObject) -> int:
    return ANKICONNECT_API_VERSION


def handle_request_permission(wrapper: AnkiWrapper, _params: JsonObject) -> JsonObject:
    """Grant access; the API key and CORS origins are the server's access rules."""
    return {
        "permission": "granted",
        "requireApikey": wrapper.settings.api_key_value is not None,
        "version": ANKICONNECT_API_VERSION,
    }


def handle_api_reflect(_wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    scopes = _get_str_list(params, "scopes")
    if "actions" not in scopes:
        return {"scopes": []}
    requested = params.get("actions")
    names = list(ACTION_HANDLERS)
    if requested is not None:
        wanted = _get_str_list(params, "actions")
        names = [name for name in wanted if name in ACTION_HANDLERS]
    return {"scopes": ["actions"], "actions": cast(list[JsonValue], names)}


def handle_sync(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    result = wrapper.sync_to_ankiweb(
        _get_optional_str(params, "username"),
        _get_optional_str(params, "password"),
        _get_optional_str(params, "endpoint"),
        discard_local_changes=_get_bool(params, "discardLocalChanges"),
    )
    return cast(JsonObject, result.model_dump(mode="json", exclude_none=True))


def handle_sync_status(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return wrapper.sync_status(
        _get_optional_str(params, "username"),
        _get_optional_str(params, "password"),
        _get_optional_str(params, "endpoint"),
    )


def handle_sync_media(wrapper: AnkiWrapper, params: JsonObject) -> str:
    return wrapper.sync_media_only(
        _get_optional_str(params, "username"),
        _get_optional_str(params, "password"),
        _get_optional_str(params, "endpoint"),
    )


# Decks


def handle_deck_names(wrapper: AnkiWrapper, _params: JsonObject) -> list[str]:
    return wrapper.deck_names()


def handle_deck_names_and_ids(wrapper: AnkiWrapper, _params: JsonObject) -> dict[str, int]:
    return wrapper.deck_names_and_ids()


def handle_deck_name_from_id(wrapper: AnkiWrapper, params: JsonObject) -> str:
    return wrapper.deck_name_from_id(_get_int(params, "deckId"))


def handle_get_decks(wrapper: AnkiWrapper, params: JsonObject) -> dict[str, list[int]]:
    return wrapper.get_decks(_get_id_list(params, "cards"))


def handle_create_deck(wrapper: AnkiWrapper, params: JsonObject) -> int:
    require_params(params, "deck")
    deck = _get_str(params, "deck")
    if not deck:
        raise ValidationError("Deck name cannot be empty")
    return wrapper.create_deck(deck)


def handle_change_deck(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.change_deck(_get_id_list(params, "cards", required=True), _get_str(params, "deck"))


def handle_delete_decks(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.delete_decks(
        _get_str_list(params, "decks", required=True),
        _get_bool(params, "cardsToo"),
    )


def handle_get_deck_config(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return wrapper.get_deck_config(_get_str(params, "deck"))


def handle_save_deck_config(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.save_deck_config(_get_object(params, "config", required=True))


def handle_set_deck_config_id(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.set_deck_config_id(
        _get_str_list(params, "decks", required=True),
        _get_int(params, "configId"),
    )


def handle_clone_deck_config_id(wrapper: AnkiWrapper, params: JsonObject) -> int:
    return wrapper.clone_deck_config_id(
        _get_str(params, "name"),
        _get_int(params, "cloneFrom"),
    )


def handle_remove_deck_config_id(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.remove_deck_config_id(_get_int(params, "configId"))


# Models


def handle_model_names(wrapper: AnkiWrapper, _params: JsonObject) -> list[str]:
    return wrapper.model_names()


def handle_model_names_and_ids(wrapper: AnkiWrapper, _params: JsonObject) -> dict[str, int]:
    return wrapper.model_names_and_ids()


def handle_model_name_from_id(wrapper: AnkiWrapper, params: JsonObject) -> str:
    return wrapper.model_name_from_id(_get_int(params, "modelId"))


def handle_model_field_names(wrapper: AnkiWrapper, params: JsonObject) -> list[str]:
    return wrapper.model_field_names(_get_str(params, "modelName"))


def handle_model_fields_on_templates(
    wrapper: AnkiWrapper, params: JsonObject
) -> dict[str, list[list[str]]]:
    return wrapper.model_fields_on_templates(_get_str(params, "modelName"))


def handle_create_model(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.create_model(
        _get_str(params, "modelName"),
        _get_str_list(params, "inOrderFields", required=True),
        _parse_card_templates(params),
        _get_str(params, "css", ""),
        _get_bool(params, "isCloze"),
    )


def handle_model_templates(wrapper: AnkiWrapper, params: JsonObject) -> dict[str, dict[str, str]]:
    return wrapper.model_templates(_get_str(params, "modelName"))


def handle_model_styling(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return wrapper.model_styling(_get_str(params, "modelName"))


def handle_update_model_templates(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.update_model_templates(_parse_template_update(params))


def handle_update_model_styling(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.update_model_styling(_parse_styling_update(params))


# Notes


def handle_add_note(wrapper: AnkiWrapper, params: JsonObject) -> int:
    require_params(params, "note")
    return note_actions.add_note(wrapper, params["note"])


def handle_add_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[int]:
    return note_actions.add_notes(wrapper, _note_list(params))


def handle_can_add_note(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    require_params(params, "note")
    return note_actions.validate_note(wrapper, params["note"])["canAdd"] is True


def handle_can_add_note_with_error_detail(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    require_params(params, "note")
    return note_actions.validate_note(wrapper, params["note"])


def handle_can_add_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[bool]:
    return [
        note_actions.validate_note(wrapper, note)["canAdd"] is True for note in _note_list(params)
    ]


def handle_can_add_notes_with_error_detail(
    wrapper: AnkiWrapper, params: JsonObject
) -> list[JsonObject]:
    return [note_actions.validate_note(wrapper, note) for note in _note_list(params)]


def handle_update_note_fields(wrapper: AnkiWrapper, params: JsonObject) -> None:
    require_params(params, "note")
    note_actions.update_note(wrapper, params["note"], include_tags=False)


def handle_update_note(wrapper: AnkiWrapper, params: JsonObject) -> None:
    require_params(params, "note")
    note_actions.update_note(wrapper, params["note"], include_tags=True)


def handle_update_note_tags(wrapper: AnkiWrapper, params: JsonObject) -> None:
    require_params(params, "note")
    note_actions.set_note_tags(wrapper, params["note"], params.get("tags"))


def handle_get_note_tags(wrapper: AnkiWrapper, params: JsonObject) -> list[str]:
    require_params(params, "note")
    return note_actions.note_tags(wrapper, params["note"])


def handle_add_tags(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.add_tags(_get_id_list(params, "notes", required=True), _get_str(params, "tags"))


def handle_remove_tags(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.remove_tags(
        _get_id_list(params, "notes", required=True),
        _get_str(params, "tags"),
    )


def handle_get_tags(wrapper: AnkiWrapper, _params: JsonObject) -> list[str]:
    return wrapper.get_tags()


def handle_find_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[int]:
    query = _get_optional_str(params, "query")
    return [] if query is None else wrapper.find_notes(query)


def handle_notes_info(wrapper: AnkiWrapper, params: JsonObject) -> list[JsonObject]:
    if params.get("notes") is None:
        query = _get_optional_str(params, "query")
        note_ids = [] if query is None else wrapper.find_notes(query)
    else:
        note_ids = _get_id_list(params, "notes")
    return note_actions.notes_info(wrapper, note_ids)


def handle_delete_notes(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.delete_notes(_get_id_list(params, "notes", required=True))


# Cards


def handle_find_cards(wrapper: AnkiWrapper, params: JsonObject) -> list[int]:
    query = _get_optional_str(params, "query")
    return [] if query is None else wrapper.find_cards(query)


def handle_cards_to_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[int]:
    return wrapper.cards_to_notes(_get_id_list(params, "cards", required=True))


def handle_cards_info(wrapper: AnkiWrapper, params: JsonObject) -> list[JsonObject]:
    selected = params.get("fields")
    properties = None if selected is None else set(_get_str_list(params, "fields"))
    return wrapper.cards_info(_get_id_list(params, "cards", required=True), properties)


def handle_answer_cards(wrapper: AnkiWrapper, params: JsonObject) -> list[bool]:
    return wrapper.answer_cards(_parse_card_answers(params))


def handle_suspend(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.suspend(_get_id_list(params, "cards", required=True))


def handle_unsuspend(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.unsuspend(_get_id_list(params, "cards", required=True))


def handle_are_suspended(wrapper: AnkiWrapper, params: JsonObject) -> list[bool | None]:
    return wrapper.are_suspended(_get_id_list(params, "cards", required=True))


def handle_are_due(wrapper: AnkiWrapper, params: JsonObject) -> list[bool]:
    return wrapper.are_due(_get_id_list(params, "cards", required=True))


def handle_get_intervals(wrapper: AnkiWrapper, params: JsonObject) -> list[JsonValue]:
    return wrapper.get_intervals(
        _get_id_list(params, "cards", required=True),
        _get_bool(params, "complete"),
    )


# Media


def handle_get_media_dir_path(wrapper: AnkiWrapper, _params: JsonObject) -> str:
    return wrapper.get_media_dir_path()


def handle_get_media_files_names(wrapper: AnkiWrapper, params: JsonObject) -> list[str]:
    pattern = _get_str(params, "pattern", "*")
    return sorted(
        path.name
        for path in wrapper.media_dir().iterdir()
        if path.is_file() and fnmatch.fnmatchcase(path.name, pattern)
    )


def handle_store_media_file(wrapper: AnkiWrapper, params: JsonObject) -> str | None:
    filename = _get_str(params, "filename")
    data = params.get("data")
    if not isinstance(data, str) or not data:
        if params.get("path") or params.get("url"):
            raise ValidationError(note_actions.UNSUPPORTED_MEDIA_SOURCE)
        raise ValidationError("data must be a nonempty base64 string")
    skip_hash = _get_optional_str(params, "skipHash")
    return note_actions.store_media(
        wrapper,
        filename,
        note_actions.decode_base64(data),
        delete_existing=_get_bool(params, "deleteExisting", default=True),
        skip_hash=skip_hash or None,
    )


def handle_retrieve_media_file(wrapper: AnkiWrapper, params: JsonObject) -> str | bool:
    value = wrapper.retrieve_media_file(_get_str(params, "filename"))
    return False if value is None else value


def handle_delete_media_file(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.delete_media_file(_get_str(params, "filename"))


# Packages


def handle_import_package(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return wrapper.import_package(_get_str(params, "path"))


def handle_export_package(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    wrapper.export_package(
        _get_str(params, "deck"),
        _get_str(params, "path"),
        _get_bool(params, "includeSched"),
    )
    return True


def handle_multi(wrapper: AnkiWrapper, params: JsonObject, depth: int = 0) -> list[JsonValue]:
    """Run nested requests in order; each keeps its own version and error slot.

    The outer request is authenticated once, so nested requests need no key.
    """
    actions = _get_list(params, "actions", required=True)
    if any(not isinstance(value, dict) for value in actions):
        raise ValidationError("actions must contain only objects")
    return [execute_request(value, wrapper, depth=depth + 1) for value in actions]


type Handler = Callable[[AnkiWrapper, JsonObject], object]

ACTION_HANDLERS: dict[str, Handler] = {
    "version": handle_version,
    "requestPermission": handle_request_permission,
    "apiReflect": handle_api_reflect,
    "sync": handle_sync,
    "syncStatus": handle_sync_status,
    "syncMedia": handle_sync_media,
    "deckNames": handle_deck_names,
    "deckNamesAndIds": handle_deck_names_and_ids,
    "deckNameFromId": handle_deck_name_from_id,
    "getDecks": handle_get_decks,
    "createDeck": handle_create_deck,
    "changeDeck": handle_change_deck,
    "deleteDecks": handle_delete_decks,
    "getDeckConfig": handle_get_deck_config,
    "saveDeckConfig": handle_save_deck_config,
    "setDeckConfigId": handle_set_deck_config_id,
    "cloneDeckConfigId": handle_clone_deck_config_id,
    "removeDeckConfigId": handle_remove_deck_config_id,
    "modelNames": handle_model_names,
    "modelNamesAndIds": handle_model_names_and_ids,
    "modelNameFromId": handle_model_name_from_id,
    "modelFieldNames": handle_model_field_names,
    "modelFieldsOnTemplates": handle_model_fields_on_templates,
    "createModel": handle_create_model,
    "modelTemplates": handle_model_templates,
    "modelStyling": handle_model_styling,
    "updateModelTemplates": handle_update_model_templates,
    "updateModelStyling": handle_update_model_styling,
    "addNote": handle_add_note,
    "addNotes": handle_add_notes,
    "canAddNote": handle_can_add_note,
    "canAddNoteWithErrorDetail": handle_can_add_note_with_error_detail,
    "canAddNotes": handle_can_add_notes,
    "canAddNotesWithErrorDetail": handle_can_add_notes_with_error_detail,
    "updateNoteFields": handle_update_note_fields,
    "updateNote": handle_update_note,
    "updateNoteTags": handle_update_note_tags,
    "getNoteTags": handle_get_note_tags,
    "addTags": handle_add_tags,
    "removeTags": handle_remove_tags,
    "getTags": handle_get_tags,
    "findNotes": handle_find_notes,
    "notesInfo": handle_notes_info,
    "deleteNotes": handle_delete_notes,
    "findCards": handle_find_cards,
    "cardsToNotes": handle_cards_to_notes,
    "cardsInfo": handle_cards_info,
    "answerCards": handle_answer_cards,
    "suspend": handle_suspend,
    "unsuspend": handle_unsuspend,
    "areSuspended": handle_are_suspended,
    "areDue": handle_are_due,
    "getIntervals": handle_get_intervals,
    "getMediaDirPath": handle_get_media_dir_path,
    "getMediaFilesNames": handle_get_media_files_names,
    "storeMediaFile": handle_store_media_file,
    "retrieveMediaFile": handle_retrieve_media_file,
    "deleteMediaFile": handle_delete_media_file,
    "importPackage": handle_import_package,
    "exportPackage": handle_export_package,
    "multi": handle_multi,
}

# Actions that never touch the collection and so never wait for it.
NO_COLLECTION_ACTIONS = frozenset({"version", "requestPermission", "apiReflect"})


def parse_version(value: JsonValue) -> int:
    if value is None:
        return LEGACY_DEFAULT_VERSION
    number = _as_int(value)
    if number is None:
        raise ValidationError("version must be an integer")
    return number


def parse_params(value: JsonValue) -> JsonObject:
    if value is None or value == []:
        return {}
    if not isinstance(value, dict):
        raise ValidationError("params must be an object")
    return value


def execute(action: str, params: JsonObject, wrapper: AnkiWrapper, *, depth: int = 0) -> JsonValue:
    """Run one action and return its result, raising ValueError on failure."""
    handler = ACTION_HANDLERS.get(action)
    if handler is None:
        logger.warning("Unsupported action requested: %s", action)
        raise UnsupportedActionError(UNSUPPORTED_ACTION)
    if depth > MAX_MULTI_DEPTH:
        raise ValidationError("multi nesting limit exceeded")
    try:
        if action == "multi":
            return cast(JsonValue, handle_multi(wrapper, params, depth))
        return cast(JsonValue, handler(wrapper, params))
    except (ValidationError, note_actions.NoteError) as exc:
        logger.info("Rejected %s: %s", action, exc)
        raise ValueError(str(exc)) from exc


def reply(version: int, result: JsonValue = None, error: str | None = None) -> JsonValue:
    """Shape a reply the way AnkiConnect does for the request's version.

    Versions 4 and below return the bare result on success; errors and every
    reply from version 5 on use the result/error envelope.
    """
    if error is not None:
        return {"result": None, "error": error}
    if version <= LEGACY_DEFAULT_VERSION:
        return result
    return {"result": result, "error": None}


def execute_request(request: JsonValue, wrapper: AnkiWrapper, *, depth: int = 0) -> JsonValue:
    """Run one legacy request object and return its AnkiConnect reply."""
    version = LEGACY_DEFAULT_VERSION
    try:
        if not isinstance(request, dict):
            raise ValidationError("request must be a JSON object")
        version = parse_version(request.get("version"))
        action = request.get("action")
        if not isinstance(action, str):
            raise UnsupportedActionError(UNSUPPORTED_ACTION)
        result = execute(action, parse_params(request.get("params")), wrapper, depth=depth)
    except Exception as exc:
        if not isinstance(exc, ValueError):
            logger.exception("AnkiConnect request failed")
        return reply(version, error=str(exc) or exc.__class__.__name__)
    return reply(version, result)


async def dispatch(action: str, params: JsonObject, wrapper: AnkiWrapper) -> JsonValue:
    """Run one action through the collection gate; raises ValueError on failure."""
    return await wrapper.gate.run(lambda: execute(action, params, wrapper))

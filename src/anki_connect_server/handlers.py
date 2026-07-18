import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import cast

from anki_connect_server import ANKICONNECT_API_VERSION
from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.types import (
    CardAnswerInput,
    CardTemplateInput,
    JsonObject,
    JsonValue,
    ModelStylingUpdate,
    ModelTemplateUpdate,
    NoteInput,
)

logger = logging.getLogger(__name__)


class ValidationError(ValueError):
    pass


def require_params(params: JsonObject, *required_keys: str) -> None:
    missing = [key for key in required_keys if key not in params or params[key] is None]
    if missing:
        raise ValidationError(f"Missing required parameters: {', '.join(missing)}")


def _get_str(params: JsonObject, key: str, default: str | None = None) -> str:
    value = params.get(key, default)
    if not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    return value


def _get_optional_str(params: JsonObject, key: str) -> str | None:
    value = params.get(key)
    if value is not None and not isinstance(value, str):
        raise ValidationError(f"{key} must be a string")
    return value


def _get_bool(params: JsonObject, key: str, default: bool = False) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise ValidationError(f"{key} must be a boolean")
    return value


def _get_int(params: JsonObject, key: str, default: int | None = None) -> int:
    value = params.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{key} must be an integer")
    return value


def _get_object(params: JsonObject, key: str, *, required: bool = False) -> JsonObject:
    if required:
        require_params(params, key)
    value = params.get(key, {})
    if not isinstance(value, dict):
        raise ValidationError(f"{key} must be an object")
    return value


def _get_list(params: JsonObject, key: str, *, required: bool = False) -> list[JsonValue]:
    if required:
        require_params(params, key)
    value = params.get(key, [])
    if not isinstance(value, list):
        raise ValidationError(f"{key} must be a list")
    return value


def _get_int_list(params: JsonObject, key: str, *, required: bool = False) -> list[int]:
    values = _get_list(params, key, required=required)
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise ValidationError(f"{key} must contain only integers")
    return [value for value in values if isinstance(value, int) and not isinstance(value, bool)]


def _get_str_list(params: JsonObject, key: str, *, required: bool = False) -> list[str]:
    values = _get_list(params, key, required=required)
    if any(not isinstance(value, str) for value in values):
        raise ValidationError(f"{key} must contain only strings")
    return [value for value in values if isinstance(value, str)]


def _string_map(value: JsonValue, name: str) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(item, str) for item in value.values()):
        raise ValidationError(f"{name} must be an object containing string values")
    return {key: item for key, item in value.items() if isinstance(item, str)}


def _parse_note(value: JsonValue) -> NoteInput:
    if not isinstance(value, dict):
        raise ValidationError("note must be an object")
    require_params(value, "deckName", "modelName", "fields")
    note = NoteInput(
        deckName=_get_str(value, "deckName"),
        modelName=_get_str(value, "modelName"),
        fields=_string_map(value["fields"], "fields"),
    )
    if "tags" in value:
        note["tags"] = _get_str_list(value, "tags")
    return note


def _parse_notes(params: JsonObject) -> list[NoteInput]:
    return [_parse_note(value) for value in _get_list(params, "notes", required=True)]


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


async def handle_version(_wrapper: AnkiWrapper, _params: JsonObject) -> int:
    return ANKICONNECT_API_VERSION


async def handle_sync(wrapper: AnkiWrapper, params: JsonObject) -> str:
    return await asyncio.to_thread(
        wrapper.sync_to_ankiweb,
        _get_optional_str(params, "username"),
        _get_optional_str(params, "password"),
        _get_optional_str(params, "endpoint"),
    )


async def handle_sync_status(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return await asyncio.to_thread(
        wrapper.sync_status,
        _get_optional_str(params, "username"),
        _get_optional_str(params, "password"),
        _get_optional_str(params, "endpoint"),
    )


async def handle_sync_media(wrapper: AnkiWrapper, params: JsonObject) -> str:
    return await asyncio.to_thread(
        wrapper.sync_media_only,
        _get_optional_str(params, "username"),
        _get_optional_str(params, "password"),
        _get_optional_str(params, "endpoint"),
    )


async def handle_deck_names(wrapper: AnkiWrapper, _params: JsonObject) -> list[str]:
    return wrapper.deck_names()


async def handle_deck_names_and_ids(wrapper: AnkiWrapper, _params: JsonObject) -> dict[str, int]:
    return wrapper.deck_names_and_ids()


async def handle_get_decks(wrapper: AnkiWrapper, params: JsonObject) -> dict[str, list[int]]:
    return wrapper.get_decks(_get_int_list(params, "cards"))


async def handle_create_deck(wrapper: AnkiWrapper, params: JsonObject) -> int:
    require_params(params, "deck")
    deck = _get_str(params, "deck")
    if not deck:
        raise ValidationError("Deck name cannot be empty")
    return wrapper.create_deck(deck)


async def handle_change_deck(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.change_deck(_get_int_list(params, "cards", required=True), _get_str(params, "deck"))


async def handle_delete_decks(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.delete_decks(
        _get_str_list(params, "decks", required=True),
        _get_bool(params, "cardsToo"),
    )


async def handle_get_deck_config(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return wrapper.get_deck_config(_get_str(params, "deck"))


async def handle_save_deck_config(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.save_deck_config(_get_object(params, "config", required=True))


async def handle_set_deck_config_id(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.set_deck_config_id(
        _get_str_list(params, "decks", required=True),
        _get_int(params, "configId"),
    )


async def handle_clone_deck_config_id(wrapper: AnkiWrapper, params: JsonObject) -> int:
    return wrapper.clone_deck_config_id(
        _get_str(params, "name"),
        _get_int(params, "cloneFrom"),
    )


async def handle_remove_deck_config_id(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.remove_deck_config_id(_get_int(params, "configId"))


async def handle_model_names(wrapper: AnkiWrapper, _params: JsonObject) -> list[str]:
    return wrapper.model_names()


async def handle_model_names_and_ids(wrapper: AnkiWrapper, _params: JsonObject) -> dict[str, int]:
    return wrapper.model_names_and_ids()


async def handle_model_field_names(wrapper: AnkiWrapper, params: JsonObject) -> list[str]:
    return wrapper.model_field_names(_get_str(params, "modelName"))


async def handle_model_fields_on_templates(
    wrapper: AnkiWrapper, params: JsonObject
) -> dict[str, list[list[str]]]:
    return wrapper.model_fields_on_templates(_get_str(params, "modelName"))


async def handle_create_model(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.create_model(
        _get_str(params, "modelName"),
        _get_str_list(params, "inOrderFields", required=True),
        _parse_card_templates(params),
        _get_str(params, "css", ""),
        _get_bool(params, "isCloze"),
    )


async def handle_model_templates(
    wrapper: AnkiWrapper, params: JsonObject
) -> dict[str, dict[str, str]]:
    return wrapper.model_templates(_get_str(params, "modelName"))


async def handle_model_styling(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return wrapper.model_styling(_get_str(params, "modelName"))


async def handle_update_model_templates(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.update_model_templates(_parse_template_update(params))


async def handle_update_model_styling(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.update_model_styling(_parse_styling_update(params))


async def handle_add_note(wrapper: AnkiWrapper, params: JsonObject) -> int | None:
    require_params(params, "note")
    return wrapper.add_note(_parse_note(params["note"]))


async def handle_add_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[int | None]:
    return wrapper.add_notes(_parse_notes(params))


async def handle_can_add_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[bool]:
    return wrapper.can_add_notes(_parse_notes(params))


async def handle_update_note_fields(wrapper: AnkiWrapper, params: JsonObject) -> None:
    note = _get_object(params, "note", required=True)
    wrapper.update_note_fields(
        _get_int(note, "id"),
        _string_map(note.get("fields"), "fields"),
    )


async def handle_add_tags(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.add_tags(_get_int_list(params, "notes", required=True), _get_str(params, "tags"))


async def handle_remove_tags(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.remove_tags(
        _get_int_list(params, "notes", required=True),
        _get_str(params, "tags"),
    )


async def handle_get_tags(wrapper: AnkiWrapper, _params: JsonObject) -> list[str]:
    return wrapper.get_tags()


async def handle_find_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[int]:
    return wrapper.find_notes(_get_str(params, "query", ""))


async def handle_notes_info(wrapper: AnkiWrapper, params: JsonObject) -> list[JsonObject]:
    return wrapper.notes_info(_get_int_list(params, "notes", required=True))


async def handle_delete_notes(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.delete_notes(_get_int_list(params, "notes", required=True))


async def handle_find_cards(wrapper: AnkiWrapper, params: JsonObject) -> list[int]:
    return wrapper.find_cards(_get_str(params, "query", ""))


async def handle_cards_to_notes(wrapper: AnkiWrapper, params: JsonObject) -> list[int]:
    return wrapper.cards_to_notes(_get_int_list(params, "cards", required=True))


async def handle_cards_info(wrapper: AnkiWrapper, params: JsonObject) -> list[JsonObject]:
    return wrapper.cards_info(_get_int_list(params, "cards", required=True))


async def handle_answer_cards(wrapper: AnkiWrapper, params: JsonObject) -> list[bool]:
    return wrapper.answer_cards(_parse_card_answers(params))


async def handle_suspend(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.suspend(_get_int_list(params, "cards", required=True))


async def handle_unsuspend(wrapper: AnkiWrapper, params: JsonObject) -> bool:
    return wrapper.unsuspend(_get_int_list(params, "cards", required=True))


async def handle_are_suspended(wrapper: AnkiWrapper, params: JsonObject) -> list[bool]:
    return wrapper.are_suspended(_get_int_list(params, "cards", required=True))


async def handle_are_due(wrapper: AnkiWrapper, params: JsonObject) -> list[bool]:
    return wrapper.are_due(_get_int_list(params, "cards", required=True))


async def handle_get_intervals(wrapper: AnkiWrapper, params: JsonObject) -> list[JsonValue]:
    return wrapper.get_intervals(
        _get_int_list(params, "cards", required=True),
        _get_bool(params, "complete"),
    )


async def handle_get_media_dir_path(wrapper: AnkiWrapper, _params: JsonObject) -> str:
    return wrapper.get_media_dir_path()


async def handle_store_media_file(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.store_media_file(_get_str(params, "filename"), _get_str(params, "data"))


async def handle_retrieve_media_file(wrapper: AnkiWrapper, params: JsonObject) -> str | None:
    return wrapper.retrieve_media_file(_get_str(params, "filename"))


async def handle_delete_media_file(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.delete_media_file(_get_str(params, "filename"))


async def handle_import_package(wrapper: AnkiWrapper, params: JsonObject) -> JsonObject:
    return wrapper.import_package(_get_str(params, "path"))


async def handle_export_package(wrapper: AnkiWrapper, params: JsonObject) -> None:
    wrapper.export_package(
        _get_str(params, "deck"),
        _get_str(params, "path"),
        _get_bool(params, "includeSched"),
    )


async def handle_multi(wrapper: AnkiWrapper, params: JsonObject) -> list[JsonValue]:
    results: list[JsonValue] = []
    for value in _get_list(params, "actions", required=True):
        if not isinstance(value, dict):
            raise ValidationError("actions must contain only objects")
        action = _get_str(value, "action")
        action_params = _get_object(value, "params")
        handler = ACTION_HANDLERS.get(action)
        if handler is None:
            results.append({"error": f"Unknown action: {action}"})
        else:
            results.append(cast(JsonValue, await handler(wrapper, action_params)))
    return results


type Handler = Callable[[AnkiWrapper, JsonObject], Awaitable[object]]

ACTION_HANDLERS: dict[str, Handler] = {
    "version": handle_version,
    "sync": handle_sync,
    "syncStatus": handle_sync_status,
    "syncMedia": handle_sync_media,
    "deckNames": handle_deck_names,
    "deckNamesAndIds": handle_deck_names_and_ids,
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
    "modelFieldNames": handle_model_field_names,
    "modelFieldsOnTemplates": handle_model_fields_on_templates,
    "createModel": handle_create_model,
    "modelTemplates": handle_model_templates,
    "modelStyling": handle_model_styling,
    "updateModelTemplates": handle_update_model_templates,
    "updateModelStyling": handle_update_model_styling,
    "addNote": handle_add_note,
    "addNotes": handle_add_notes,
    "canAddNotes": handle_can_add_notes,
    "updateNoteFields": handle_update_note_fields,
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
    "storeMediaFile": handle_store_media_file,
    "retrieveMediaFile": handle_retrieve_media_file,
    "deleteMediaFile": handle_delete_media_file,
    "importPackage": handle_import_package,
    "exportPackage": handle_export_package,
    "multi": handle_multi,
}


async def dispatch(action: str, params: JsonObject, wrapper: AnkiWrapper) -> JsonValue:
    handler = ACTION_HANDLERS.get(action)
    if handler is None:
        logger.warning("Unsupported action requested: %s", action)
        raise ValueError(f"Unsupported action: {action}")
    try:
        return cast(JsonValue, await handler(wrapper, params))
    except ValidationError as exc:
        logger.warning("Validation error in %s: %s", action, exc)
        raise ValueError(str(exc)) from exc

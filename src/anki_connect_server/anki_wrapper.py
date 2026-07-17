import base64
import logging
import re
from pathlib import Path
from typing import cast

import anki.collection
from anki.cards import CardId
from anki.collection import (
    DeckIdLimit,
    ExportAnkiPackageOptions,
    ImportAnkiPackageRequest,
)
from anki.consts import MODEL_CLOZE
from anki.decks import DeckConfigDict, DeckConfigId, DeckId
from anki.errors import NotFoundError
from anki.models import FieldDict, NotetypeDict, TemplateDict
from anki.notes import Note, NoteId
from anki.sync import SyncAuth
from anki.sync_pb2 import SyncCollectionResponse
from google.protobuf.json_format import MessageToDict

from anki_connect_server.config import Config
from anki_connect_server.types import (
    CardTemplateInput,
    JsonObject,
    JsonValue,
    ModelStylingUpdate,
    ModelTemplateUpdate,
    NoteInput,
)

Collection = anki.collection.Collection

logger = logging.getLogger(__name__)


class AnkiWrapper:
    def __init__(self, collection_path: str | Path, *, settings: Config | None = None) -> None:
        Collection.initialize_backend_logging()
        self.collection_path = Path(collection_path)
        self.settings = settings or Config(collection_path=self.collection_path)
        self.col = Collection(str(self.collection_path))
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self.col.close()
            self._closed = True

    def _reopen_collection(self) -> None:
        self.col = Collection(str(self.collection_path))
        self._closed = False

    def _credentials(
        self,
        username: str | None,
        password: str | None,
        endpoint: str | None,
        *,
        operation: str,
    ) -> tuple[str, str, str | None]:
        user = username or self.settings.ankiweb_user
        pass_ = password or self.settings.ankiweb_pass
        url = endpoint or self.settings.ankiweb_url
        if not user or not pass_:
            raise ValueError(
                f"ANKICONNECT_ANKIWEB_USER and ANKICONNECT_ANKIWEB_PASS required for {operation}"
            )
        return user, pass_, url

    def _full_sync(self, auth: SyncAuth, server_usn: int, *, upload: bool) -> None:
        self.col.close_for_full_sync()
        self._closed = True
        try:
            self.col.full_upload_or_download(auth=auth, server_usn=server_usn, upload=upload)
        finally:
            self.col.reopen(after_full_sync=True)
            self._closed = False

    def sync_to_ankiweb(
        self,
        username: str | None = None,
        password: str | None = None,
        endpoint: str | None = None,
    ) -> str:
        user, pass_, url = self._credentials(
            username,
            password,
            endpoint,
            operation="sync",
        )
        try:
            auth = self.col.sync_login(username=user, password=pass_, endpoint=url)
            result = self.col.sync_collection(auth, sync_media=False)
            if result.required in (
                SyncCollectionResponse.FULL_SYNC,
                SyncCollectionResponse.FULL_DOWNLOAD,
            ):
                self._full_sync(auth, result.server_media_usn, upload=False)
            elif result.required == SyncCollectionResponse.FULL_UPLOAD:
                if self.settings.full_upload:
                    self._full_sync(auth, result.server_media_usn, upload=True)
                else:
                    logger.warning(
                        "Full upload required but ANKICONNECT_FULL_UPLOAD=false; skipping"
                    )
                    self.close()
                    self._reopen_collection()
            else:
                self.close()
                self._reopen_collection()
        except Exception:
            logger.exception("AnkiWeb sync failed")
            if self._closed:
                self._reopen_collection()
            raise

        logger.info(
            "Sync completed: host=%s, required=%s",
            result.host_number,
            result.required,
        )
        return f"sync completed: host={result.host_number}, required={result.required}"

    def deck_names(self) -> list[str]:
        return [deck.name for deck in self.col.decks.all_names_and_ids()]

    def deck_names_and_ids(self) -> dict[str, int]:
        return {deck.name: int(deck.id) for deck in self.col.decks.all_names_and_ids()}

    def create_deck(self, deck: str) -> int:
        deck_id = self.col.decks.id(deck)
        if deck_id is None:
            raise ValueError(f"Unable to create deck: {deck}")
        return int(deck_id)

    def delete_decks(self, decks: list[str], cards_too: bool = False) -> None:
        for deck in decks:
            deck_id = self.col.decks.id_for_name(deck)
            if deck_id is None:
                continue
            if cards_too:
                card_ids = self.col.find_cards(f'deck:"{deck}"')
                note_ids = [
                    NoteId(note_id)
                    for note_id in self.cards_to_notes([int(card_id) for card_id in card_ids])
                ]
                if note_ids:
                    self.col.remove_notes(note_ids)
            self.col.decks.remove([deck_id])

    def get_decks(self, cards: list[int]) -> dict[str, list[int]]:
        result: dict[str, list[int]] = {}
        for card_id in cards:
            try:
                card = self.col.get_card(CardId(card_id))
            except NotFoundError:
                continue
            deck_name = self.col.decks.name(card.did)
            result.setdefault(deck_name, []).append(card_id)
        return result

    def change_deck(self, cards: list[int], deck: str) -> None:
        deck_id = self.col.decks.id(deck)
        if deck_id is None:
            raise ValueError(f"Unable to find or create deck: {deck}")
        self.col.set_deck([CardId(card_id) for card_id in cards], deck_id)

    def get_deck_config(self, deck: str) -> JsonObject:
        deck_id = self.col.decks.id_for_name(deck)
        if deck_id is None:
            return {}
        return cast(JsonObject, self.col.decks.config_dict_for_deck_id(deck_id))

    def save_deck_config(self, config: JsonObject) -> bool:
        self.col.decks.update_config(cast(DeckConfigDict, config))
        return True

    def set_deck_config_id(self, decks: list[str], config_id: int) -> bool:
        typed_config_id = DeckConfigId(config_id)
        if self.col.decks.get_config(typed_config_id) is None:
            raise ValueError(f"Unknown deck configuration: {config_id}")
        for deck_name in decks:
            deck_id = self.col.decks.id_for_name(deck_name)
            deck = self.col.decks.get(deck_id) if deck_id is not None else None
            if deck is not None:
                self.col.decks.set_config_id_for_deck_dict(deck, typed_config_id)
        return True

    def clone_deck_config_id(self, name: str, clone_from: int) -> int:
        source = self.col.decks.get_config(DeckConfigId(clone_from))
        if source is None:
            raise ValueError(f"Unknown deck configuration: {clone_from}")
        return int(self.col.decks.add_config_returning_id(name, source))

    def remove_deck_config_id(self, config_id: int) -> bool:
        self.col.decks.remove_config(DeckConfigId(config_id))
        return True

    def model_names(self) -> list[str]:
        return [model.name for model in self.col.models.all_names_and_ids()]

    def model_names_and_ids(self) -> dict[str, int]:
        return {model.name: int(model.id) for model in self.col.models.all_names_and_ids()}

    def _get_model_by_name(self, model_name: str) -> NotetypeDict | None:
        return self.col.models.by_name(model_name)

    @staticmethod
    def _model_fields(model: NotetypeDict) -> list[FieldDict]:
        return cast(list[FieldDict], model.get("flds", []))

    @staticmethod
    def _model_templates(model: NotetypeDict) -> list[TemplateDict]:
        return cast(list[TemplateDict], model.get("tmpls", []))

    def model_field_names(self, model_name: str) -> list[str]:
        model = self._get_model_by_name(model_name)
        if model is None:
            return []
        return [cast(str, field["name"]) for field in self._model_fields(model)]

    def model_fields_on_templates(self, model_name: str) -> dict[str, list[list[str]]]:
        model = self._get_model_by_name(model_name)
        if model is None:
            return {}
        result: dict[str, list[list[str]]] = {}
        for template in self._model_templates(model):
            name = cast(str, template.get("name", ""))
            question = cast(str, template.get("qfmt", ""))
            answer = cast(str, template.get("afmt", ""))
            result[name] = [
                self._extract_fields_from_template(question),
                self._extract_fields_from_template(answer),
            ]
        return result

    @staticmethod
    def _extract_fields_from_template(template: str) -> list[str]:
        fields = re.findall(r"\{\{([^}]+)}}", template)
        return [field for field in fields if not field.startswith("!")]

    def create_model(
        self,
        model_name: str,
        in_order_fields: list[str],
        card_templates: list[CardTemplateInput],
        css: str = "",
        is_cloze: bool = False,
    ) -> None:
        notetype = self.col.models.new(model_name)
        if is_cloze:
            notetype["type"] = MODEL_CLOZE
        for field_name in in_order_fields:
            self.col.models.add_field(notetype, self.col.models.new_field(field_name))
        for index, card_template in enumerate(card_templates, start=1):
            template = self.col.models.new_template(card_template.get("Name", f"Card {index}"))
            template["qfmt"] = card_template.get("Front", "")
            template["afmt"] = card_template.get("Back", "")
            self.col.models.add_template(notetype, template)
        if css:
            notetype["css"] = css
        self.col.models.add(notetype)

    def model_templates(self, model_name: str) -> dict[str, dict[str, str]]:
        model = self._get_model_by_name(model_name)
        if model is None:
            return {}
        result: dict[str, dict[str, str]] = {}
        for template in self._model_templates(model):
            name = cast(str, template.get("name", ""))
            result[name] = {
                "Front": cast(str, template.get("qfmt", "")),
                "Back": cast(str, template.get("afmt", "")),
            }
        return result

    def model_styling(self, model_name: str) -> JsonObject:
        model = self._get_model_by_name(model_name)
        if model is None:
            return {}
        return {"css": cast(str, model.get("css", ""))}

    def update_model_templates(self, model_update: ModelTemplateUpdate) -> None:
        notetype = self._get_model_by_name(model_update["name"])
        if notetype is None:
            raise ValueError(f"Unknown model: {model_update['name']}")
        for template in self._model_templates(notetype):
            name = cast(str, template.get("name", ""))
            updates = model_update["templates"].get(name)
            if updates is None:
                continue
            if "Front" in updates:
                template["qfmt"] = updates["Front"]
            if "Back" in updates:
                template["afmt"] = updates["Back"]
        self.col.models.update(notetype)

    def update_model_styling(self, model_update: ModelStylingUpdate) -> None:
        notetype = self._get_model_by_name(model_update["name"])
        if notetype is None:
            raise ValueError(f"Unknown model: {model_update['name']}")
        notetype["css"] = model_update["css"]
        self.col.models.update(notetype)

    def add_note(self, note: NoteInput) -> int | None:
        notetype = self._get_model_by_name(note["modelName"])
        if notetype is None:
            return None
        deck_id = self.col.decks.id(note["deckName"])
        if deck_id is None:
            return None
        new_note = Note(self.col, notetype)
        for field_name, value in note["fields"].items():
            new_note[field_name] = value
        new_note.tags = list(note.get("tags", []))
        self.col.add_note(new_note, deck_id)
        return int(new_note.id)

    def add_notes(self, notes: list[NoteInput]) -> list[int | None]:
        return [self.add_note(note) for note in notes]

    def can_add_notes(self, notes: list[NoteInput]) -> list[bool]:
        return [self._can_add_note(note) for note in notes]

    def _can_add_note(self, note: NoteInput) -> bool:
        model = self._get_model_by_name(note["modelName"])
        if model is None or not note["deckName"]:
            return False
        model_fields = self.model_field_names(note["modelName"])
        fields = note["fields"]
        return (
            bool(model_fields)
            and set(fields) == set(model_fields)
            and bool(fields[model_fields[0]])
        )

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> None:
        note = self.col.get_note(NoteId(note_id))
        for field_name, value in fields.items():
            note[field_name] = value
        self.col.update_note(note)

    def add_tags(self, notes: list[int], tags: str) -> None:
        self.col.tags.bulk_add([NoteId(note_id) for note_id in notes], tags)

    def remove_tags(self, notes: list[int], tags: str) -> None:
        self.col.tags.bulk_remove([NoteId(note_id) for note_id in notes], tags)

    def get_tags(self) -> list[str]:
        return self.col.tags.all()

    def find_notes(self, query: str) -> list[int]:
        return [int(note_id) for note_id in self.col.find_notes(query)]

    def notes_info(self, notes: list[int]) -> list[JsonObject]:
        result: list[JsonObject] = []
        for note_id in notes:
            try:
                note = self.col.get_note(NoteId(note_id))
            except NotFoundError:
                continue
            model = self.col.models.get(note.mid)
            model_name = cast(str, model.get("name", "")) if model is not None else ""
            fields: JsonObject = {
                name: {"value": value, "order": index}
                for index, (name, value) in enumerate(note.items())
            }
            result.append(
                {
                    "noteId": int(note.id),
                    "modelName": model_name,
                    "tags": list(note.tags),
                    "fields": fields,
                }
            )
        return result

    def delete_notes(self, notes: list[int]) -> None:
        self.col.remove_notes([NoteId(note_id) for note_id in notes])

    def find_cards(self, query: str) -> list[int]:
        return [int(card_id) for card_id in self.col.find_cards(query)]

    def cards_to_notes(self, cards: list[int]) -> list[int]:
        note_ids: list[int] = []
        for card_id in cards:
            try:
                note_id = int(self.col.get_card(CardId(card_id)).nid)
            except NotFoundError:
                continue
            if note_id not in note_ids:
                note_ids.append(note_id)
        return note_ids

    def cards_info(self, cards: list[int]) -> list[JsonObject]:
        result: list[JsonObject] = []
        for card_id in cards:
            try:
                card = self.col.get_card(CardId(card_id))
            except NotFoundError:
                continue
            note = card.note()
            model = self.col.models.get(note.mid)
            model_name = cast(str, model.get("name", "")) if model is not None else ""
            fields: JsonObject = {
                name: {"value": value, "order": index}
                for index, (name, value) in enumerate(note.items())
            }
            result.append(
                {
                    "cardId": int(card.id),
                    "note": int(note.id),
                    "deckName": self.col.decks.name(card.did),
                    "modelName": model_name,
                    "fields": fields,
                    "interval": card.ivl,
                    "ease": card.factor,
                    "question": card.question(reload=True),
                    "answer": card.answer(),
                }
            )
        return result

    def suspend(self, cards: list[int]) -> bool:
        changes = self.col.sched.suspend_cards([CardId(card_id) for card_id in cards])
        return changes.count > 0

    def unsuspend(self, cards: list[int]) -> bool:
        self.col.sched.unsuspend_cards([CardId(card_id) for card_id in cards])
        return True

    def are_suspended(self, cards: list[int]) -> list[bool]:
        return [self.col.get_card(CardId(card_id)).queue == -1 for card_id in cards]

    def are_due(self, cards: list[int]) -> list[bool]:
        result: list[bool] = []
        for card_id in cards:
            try:
                card = self.col.get_card(CardId(card_id))
            except NotFoundError:
                result.append(False)
                continue
            if card.queue in (1, 3):
                result.append(True)
            elif card.queue == 2:
                result.append(card.due <= self.col.sched.today)
            else:
                result.append(False)
        return result

    def get_intervals(self, cards: list[int], complete: bool = False) -> list[JsonValue]:
        result: list[JsonValue] = []
        for card_id in cards:
            try:
                card = self.col.get_card(CardId(card_id))
            except NotFoundError:
                result.append(None)
                continue
            if complete:
                result.append(
                    {
                        "interval": card.ivl,
                        "last_interval": card.lapses,
                        "is_learning": card.queue in (1, 3),
                        "is_mature": card.ivl >= 21,
                    }
                )
            else:
                result.append(card.ivl)
        return result

    def get_media_dir_path(self) -> str:
        return self.col.media.dir()

    def _media_path(self, filename: str) -> Path:
        if not filename or Path(filename).name != filename:
            raise ValueError("Media filename must not contain a directory")
        media_root = Path(self.col.media.dir()).resolve()
        candidate = (media_root / filename).resolve()
        if candidate.parent != media_root:
            raise ValueError("Media filename resolves outside the media directory")
        return candidate

    def store_media_file(self, filename: str, data: str) -> None:
        self._media_path(filename)
        file_data = base64.b64decode(data, validate=True)
        self.col.media.write_data(filename, file_data)

    def retrieve_media_file(self, filename: str) -> str | None:
        path = self._media_path(filename)
        try:
            return base64.b64encode(path.read_bytes()).decode()
        except FileNotFoundError:
            return None

    def delete_media_file(self, filename: str) -> None:
        path = self._media_path(filename)
        if path.exists():
            self.col.media.trash_files([filename])

    def import_package(self, path: str) -> JsonObject:
        request = ImportAnkiPackageRequest(package_path=path)
        response = self.col.import_anki_package(request)
        return cast(JsonObject, MessageToDict(response))

    def export_package(self, deck: str, path: str, include_sched: bool = False) -> None:
        deck_id = self.col.decks.id_for_name(deck)
        if deck_id is None:
            raise ValueError(f"Unknown deck: {deck}")
        options = ExportAnkiPackageOptions(
            with_scheduling=include_sched,
            with_deck_configs=True,
            with_media=True,
            legacy=False,
        )
        self.col.export_anki_package(
            out_path=path,
            options=options,
            limit=DeckIdLimit(DeckId(deck_id)),
        )

    def sync_status(
        self,
        username: str | None = None,
        password: str | None = None,
        endpoint: str | None = None,
    ) -> JsonObject:
        user, pass_, url = self._credentials(
            username,
            password,
            endpoint,
            operation="sync status",
        )
        auth = self.col.sync_login(username=user, password=pass_, endpoint=url)
        status = self.col.sync_status(auth)
        return {
            "required": int(status.required),
            "newEndpoint": status.new_endpoint or None,
        }

    def sync_media_only(
        self,
        username: str | None = None,
        password: str | None = None,
        endpoint: str | None = None,
    ) -> str:
        user, pass_, url = self._credentials(
            username,
            password,
            endpoint,
            operation="media sync",
        )
        auth = self.col.sync_login(username=user, password=pass_, endpoint=url)
        self.col.sync_media(auth)
        logger.info("Media sync completed")
        return "media sync completed"

    def get_sync_auth(
        self,
        username: str | None = None,
        password: str | None = None,
        endpoint: str | None = None,
    ) -> SyncAuth | None:
        try:
            user, pass_, url = self._credentials(
                username,
                password,
                endpoint,
                operation="sync authentication",
            )
        except ValueError:
            return None
        return self.col.sync_login(username=user, password=pass_, endpoint=url)

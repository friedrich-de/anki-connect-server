import base64
import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

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
from anki.sync_pb2 import MediaSyncStatusResponse, SyncCollectionResponse
from google.protobuf.json_format import MessageToDict

from anki_connect_server.config import Config, get_config
from anki_connect_server.sync import (
    CollectionSyncOutcome,
    CollectionSyncResult,
    DownloadReason,
    MediaSyncResult,
    SyncError,
    SyncResult,
)
from anki_connect_server.types import (
    CardAnswerInput,
    CardTemplateInput,
    JsonObject,
    JsonValue,
    ModelStylingUpdate,
    ModelTemplateUpdate,
    NoteInput,
)

Collection = anki.collection.Collection

logger = logging.getLogger(__name__)

type SyncProgressCallback = Callable[[str], None]


class AnkiWrapper:
    def __init__(self, collection_path: str | Path, *, settings: Config | None = None) -> None:
        Collection.initialize_backend_logging()
        self.collection_path = Path(collection_path)
        self.settings = settings or Config(collection_path=self.collection_path)
        self.col = Collection(str(self.collection_path))
        self._closed = False
        self._collection_generation = 0
        self._sync_lock = threading.Lock()

    @property
    def collection_generation(self) -> int:
        """Incremented whenever synchronization reopens the collection."""
        return self._collection_generation

    def close(self) -> None:
        if not self._closed:
            self.col.close()
            self._closed = True

    def _reopen_collection(self) -> None:
        self.col = Collection(str(self.collection_path))
        self._closed = False
        self._collection_generation += 1

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

    def _full_download(self, auth: SyncAuth, server_usn: int) -> None:
        self.col.close_for_full_sync()
        self._closed = True
        try:
            self.col.full_upload_or_download(auth=auth, server_usn=server_usn, upload=False)
        finally:
            self.col.reopen(after_full_sync=True)
            self._closed = False
            self._collection_generation += 1

    @staticmethod
    def _report(progress: SyncProgressCallback | None, message: str) -> None:
        if progress is not None:
            progress(message)

    def _wait_for_media(self, progress: SyncProgressCallback | None) -> MediaSyncResult:
        self._report(progress, "Synchronizing media")
        latest: tuple[str, str, str] | None = None
        while True:
            status = self.col.media_sync_status()
            counters = self._media_counters(status)
            if counters != latest and any(counters):
                checked, added, removed = counters
                self._report(
                    progress,
                    f"Media progress: checked {checked or '0'}, added {added or '0'}, "
                    f"removed {removed or '0'}",
                )
                latest = counters
            if not status.active:
                return MediaSyncResult(
                    checked=counters[0] or None,
                    added=counters[1] or None,
                    removed=counters[2] or None,
                )
            time.sleep(0.1)

    @staticmethod
    def _media_counters(status: MediaSyncStatusResponse) -> tuple[str, str, str]:
        if not status.HasField("progress"):
            return "", "", ""
        return status.progress.checked, status.progress.added, status.progress.removed

    @staticmethod
    def _phase_error(phase: str, error: Exception) -> SyncError:
        return SyncError(f"{phase} failed: {error}")

    def sync_to_ankiweb(
        self,
        username: str | None = None,
        password: str | None = None,
        endpoint: str | None = None,
        *,
        progress: SyncProgressCallback | None = None,
    ) -> SyncResult:
        if not self._sync_lock.acquire(blocking=False):
            raise SyncError("A synchronization is already in progress")
        try:
            user, pass_, url = self._credentials(
                username,
                password,
                endpoint,
                operation="sync",
            )
            self._report(progress, "Authenticating with AnkiWeb")
            try:
                auth = self.col.sync_login(username=user, password=pass_, endpoint=url)
            except Exception as error:
                raise self._phase_error("AnkiWeb authentication", error) from error

            self._report(progress, "Synchronizing collection")
            try:
                result = self.col.sync_collection(auth, sync_media=True)
            except Exception as error:
                self.close()
                self._reopen_collection()
                raise self._phase_error("Collection synchronization", error) from error

            if result.new_endpoint:
                auth.endpoint = result.new_endpoint

            needs_reopen = False
            if result.required in (
                SyncCollectionResponse.FULL_SYNC,
                SyncCollectionResponse.FULL_DOWNLOAD,
            ):
                reason = (
                    DownloadReason.CONFLICT
                    if result.required == SyncCollectionResponse.FULL_SYNC
                    else DownloadReason.REMOTE_ONLY
                )
                self._report(
                    progress,
                    "Downloading the AnkiWeb collection to resolve a conflict"
                    if reason is DownloadReason.CONFLICT
                    else "Downloading the AnkiWeb collection",
                )
                try:
                    self._full_download(auth, result.server_media_usn)
                except Exception as error:
                    raise self._phase_error("Full collection download", error) from error
                collection = CollectionSyncResult(
                    outcome=CollectionSyncOutcome.DOWNLOADED,
                    download_reason=reason,
                    local_data_replaced=True,
                )
            elif result.required == SyncCollectionResponse.FULL_UPLOAD:
                raise SyncError(
                    "AnkiWeb collection is empty and only a full upload is possible; "
                    "full uploads are disabled by policy and the local collection was preserved"
                )
            elif result.required == SyncCollectionResponse.NORMAL_SYNC:
                collection = CollectionSyncResult(
                    outcome=CollectionSyncOutcome.MERGED,
                    local_data_replaced=False,
                )
                needs_reopen = True
            elif result.required == SyncCollectionResponse.NO_CHANGES:
                collection = CollectionSyncResult(
                    outcome=CollectionSyncOutcome.NO_CHANGES,
                    local_data_replaced=False,
                )
                needs_reopen = True
            else:
                raise SyncError(f"Unsupported synchronization requirement: {result.required}")

            try:
                media = self._wait_for_media(progress)
            except Exception as error:
                raise SyncError(
                    "Media synchronization failed after collection synchronization completed; "
                    f"media remains incomplete: {error}"
                ) from error
            finally:
                if needs_reopen:
                    self.close()
                    self._reopen_collection()

            self._report(progress, "Synchronization completed")
            logger.info(
                "Sync completed: collection=%s, media=%s",
                collection.outcome,
                media.outcome,
            )
            return SyncResult(
                collection=collection,
                media=media,
                server_message=result.server_message or None,
            )
        except Exception:
            logger.exception("AnkiWeb sync failed")
            if self._closed:
                self._reopen_collection()
            raise
        finally:
            self._sync_lock.release()

    def abort_sync(self) -> None:
        """Best-effort cancellation of collection and media synchronization."""
        for abort in (self.col.abort_sync, self.col.abort_media_sync):
            try:
                abort()
            except Exception:
                logger.exception("Failed to abort an Anki synchronization operation")

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

    def answer_cards(self, answers: list[CardAnswerInput]) -> list[bool]:
        """Apply AnkiConnect-compatible ease ratings in input order."""
        results: list[bool] = []
        for answer in answers:
            try:
                card = self.col.get_card(CardId(answer["cardId"]))
            except NotFoundError:
                results.append(False)
                continue
            card.start_timer()
            ease = cast(Literal[1, 2, 3, 4], answer["ease"])
            self.col.sched.answerCard(card, ease)
            results.append(True)
        return results

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

    def media_path(self, filename: str) -> Path:
        """Return a safe path inside the collection media directory."""
        if not filename or Path(filename).name != filename:
            raise ValueError("Media filename must not contain a directory")
        media_root = Path(self.col.media.dir()).resolve()
        candidate = (media_root / filename).resolve()
        if candidate.parent != media_root:
            raise ValueError("Media filename resolves outside the media directory")
        return candidate

    def store_media_file(self, filename: str, data: str) -> None:
        self.media_path(filename)
        file_data = base64.b64decode(data, validate=True)
        self.col.media.write_data(filename, file_data)

    def retrieve_media_file(self, filename: str) -> str | None:
        path = self.media_path(filename)
        try:
            return base64.b64encode(path.read_bytes()).decode()
        except FileNotFoundError:
            return None

    def delete_media_file(self, filename: str) -> None:
        path = self.media_path(filename)
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
        if not self._sync_lock.acquire(blocking=False):
            raise SyncError("A synchronization is already in progress")
        try:
            user, pass_, url = self._credentials(
                username,
                password,
                endpoint,
                operation="media sync",
            )
            try:
                auth = self.col.sync_login(username=user, password=pass_, endpoint=url)
            except Exception as error:
                raise self._phase_error("AnkiWeb authentication", error) from error
            try:
                self.col.sync_media(auth)
                self._wait_for_media(None)
            except Exception as error:
                raise self._phase_error("Media synchronization", error) from error
            logger.info("Media sync completed")
            return "media sync completed"
        finally:
            self._sync_lock.release()


type WrapperFactory = Callable[[], AnkiWrapper]


def create_anki_wrapper(settings: Config | None = None) -> AnkiWrapper:
    """Create a collection wrapper from explicit or environment-backed settings."""
    resolved_settings = settings or get_config()
    return AnkiWrapper(resolved_settings.collection_path, settings=resolved_settings)

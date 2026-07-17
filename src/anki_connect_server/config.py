from functools import cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _missing_collection_path() -> Path:
    raise ValueError(
        "ANKICONNECT_COLLECTION_PATH is required "
        "(ANKI_COLLECTION_PATH is accepted for compatibility)"
    )


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="ANKICONNECT_",
        populate_by_name=True,
    )

    port: int = 8765
    bind: str = "127.0.0.1"

    collection_path: Path = Field(
        default_factory=_missing_collection_path,
        validation_alias=AliasChoices(
            "ANKICONNECT_COLLECTION_PATH",
            "ANKI_COLLECTION_PATH",
        ),
    )

    ankiweb_user: str | None = None
    ankiweb_pass: str | None = None
    ankiweb_url: str | None = None
    full_upload: bool = False

    @field_validator("collection_path")
    @classmethod
    def validate_collection_path(cls, value: Path) -> Path:
        if value.suffix.lower() != ".anki2":
            raise ValueError("collection path must use the .anki2 extension")
        return value


@cache
def get_config() -> Config:
    return Config()

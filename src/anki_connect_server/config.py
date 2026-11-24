from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_MAX_REQUEST_BYTES = 128 * 1024 * 1024


def _missing_collection_path() -> Path:
    raise ValueError("ANKICONNECT_COLLECTION_PATH is required")


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="ANKICONNECT_",
    )

    port: int = 8765
    bind: str = "127.0.0.1"

    collection_path: Path = Field(default_factory=_missing_collection_path)

    api_key: SecretStr | None = Field(default=None, repr=False)
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list[str])
    # Like AnkiConnect's default, browser extensions such as Yomitan may call the API
    # from their extension origin (which differs per install in Firefox).
    cors_extensions: bool = True
    max_request_bytes: int = Field(default=DEFAULT_MAX_REQUEST_BYTES, gt=0)
    busy_timeout: float = Field(default=30.0, gt=0)

    ankiweb_user: str | None = None
    ankiweb_pass: str | None = Field(default=None, repr=False)
    ankiweb_url: str | None = None

    auto_sync: bool = False
    auto_sync_delay: float = Field(default=30.0, ge=1)
    auto_sync_interval: float = Field(default=600.0, ge=0)

    mcp_port: int = 8766

    @field_validator("collection_path")
    @classmethod
    def validate_collection_path(cls, value: Path) -> Path:
        if value.suffix.lower() != ".anki2":
            raise ValueError("collection path must use the .anki2 extension")
        return value

    @field_validator("api_key", mode="before")
    @classmethod
    def empty_api_key_disables_authentication(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def api_key_value(self) -> str | None:
        return self.api_key.get_secret_value() if self.api_key is not None else None

    @property
    def has_ankiweb_credentials(self) -> bool:
        return bool(self.ankiweb_user and self.ankiweb_pass)


@cache
def get_config() -> Config:
    return Config()

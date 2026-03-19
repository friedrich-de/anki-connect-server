from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="ANKICONNECT_",
    )

    PORT: int = 8765
    BIND: str = "127.0.0.1"

    COLLECTION_PATH: str = ""

    ANKIWEB_USER: Optional[str] = None
    ANKIWEB_PASS: Optional[str] = None

    ANKIWEB_URL: Optional[str] = None

    def validate(self) -> None:
        if not self.COLLECTION_PATH:
            raise ValueError("ANKI_COLLECTION_PATH environment variable is required")


config = Config()
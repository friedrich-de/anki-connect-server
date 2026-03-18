import os
from typing import Optional


class Config:
    PORT: int = int(os.environ.get("ANKICONNECT_PORT", "8765"))
    BIND: str = os.environ.get("ANKICONNECT_BIND", "127.0.0.1")

    COLLECTION_PATH: str = os.environ.get("ANKI_COLLECTION_PATH", "")

    ANKIWEB_USER: Optional[str] = os.environ.get("ANKICONNECT_ANKIWEB_USER")
    ANKIWEB_PASS: Optional[str] = os.environ.get("ANKICONNECT_ANKIWEB_PASS")

    ANKIWEB_URL: Optional[str] = os.environ.get("ANKIWEB_URL")

    @classmethod
    def validate(cls) -> None:
        if not cls.COLLECTION_PATH:
            raise ValueError("ANKI_COLLECTION_PATH environment variable is required")


config = Config()
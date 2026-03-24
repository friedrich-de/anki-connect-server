from typing import Optional

from anki_connect_server.anki_wrapper import AnkiWrapper
from anki_connect_server.config import config


wrapper: Optional[AnkiWrapper] = None


def get_anki_wrapper() -> AnkiWrapper:
    return wrapper


def set_wrapper(w: AnkiWrapper):
    global wrapper
    wrapper = w


def close_wrapper():
    global wrapper
    if wrapper:
        wrapper.close()
        wrapper = None

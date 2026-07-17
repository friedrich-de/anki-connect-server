from anki_connect_server.anki_wrapper import AnkiWrapper

_wrapper: AnkiWrapper | None = None


def get_anki_wrapper() -> AnkiWrapper:
    if _wrapper is None:
        raise RuntimeError("Anki wrapper is not initialized")
    return _wrapper


def maybe_get_anki_wrapper() -> AnkiWrapper | None:
    return _wrapper


def set_wrapper(value: AnkiWrapper | None) -> None:
    global _wrapper
    _wrapper = value


def close_wrapper() -> None:
    global _wrapper
    if _wrapper is not None:
        _wrapper.close()
        _wrapper = None

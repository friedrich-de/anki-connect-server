from importlib.metadata import version

ANKICONNECT_API_VERSION = 6
__version__ = version("anki-connect-server")

__all__ = ["ANKICONNECT_API_VERSION", "__version__"]

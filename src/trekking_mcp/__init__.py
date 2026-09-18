from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("trekking-mcp")
except PackageNotFoundError:  # pragma: no cover - solo fuori da un'installazione
    __version__ = "0.0.0+sviluppo"

__all__ = ["__version__"]

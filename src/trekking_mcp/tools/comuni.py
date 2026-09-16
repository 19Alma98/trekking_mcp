from __future__ import annotations

import functools
import logging
import math
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from mcp.server.mcpserver.exceptions import ToolError

from trekking_mcp.errors import ErroreSentieri

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def gestisci_errori(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Traduce gli errori previsti in `ToolError`.

    Un `ToolError` arriva al client come messaggio leggibile e viene loggato
    senza traceback. Tutto il resto e' un bug: passa e viene loggato come crash.
    """

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await fn(*args, **kwargs)
        except ErroreSentieri as exc:
            log.info("errore previsto in %s: %s", fn.__name__, exc)
            raise ToolError(exc.messaggio_utente()) from exc

    return wrapper


def riquadro_intorno(lat: float, lon: float, raggio_km: float) -> tuple[float, float, float, float]:
    """Riquadro (sud, ovest, nord, est) attorno a un punto.

    Approssimazione piana: il grado di longitudine si accorcia con il coseno
    della latitudine. Sufficiente per una bbox di ricerca, non per misure.
    """
    delta_lat = raggio_km / 111.0
    delta_lon = raggio_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return (lat - delta_lat, lon - delta_lon, lat + delta_lat, lon + delta_lon)


def distanza_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza great-circle (haversine), in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))

from __future__ import annotations

import functools
import logging
import math
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

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

    wrapper.errori_tradotti = True  # type: ignore[attr-defined]
    return wrapper


# Ogni tool di questo server legge e basta, e ogni tool interroga fonti esterne
# che possono cambiare sotto i piedi. Chi un giorno scrivesse qualcosa deve
# passare annotazioni proprie, non ereditare queste.
SOLA_LETTURA = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def strumento(
    mcp: MCPServer,
    *,
    name: str,
    title: str,
    description: str,
    annotations: ToolAnnotations = SOLA_LETTURA,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Registra un tool con la traduzione degli errori gia' dentro.

    `mcp.tool` + `gestisci_errori` erano due decoratori da ricordare a ogni
    tool. Ricordarne due su dieci funziona; su undici, prima o poi no, e il
    tool dimenticato fa arrivare al client un traceback invece di una frase.

    Qui la composizione e' una sola, quindi non c'e' la versione sbagliata da
    scrivere. `test_registrazione.py` verifica che nessun modulo chiami
    `mcp.tool` per conto suo.
    """

    def decoratore(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        registrato = mcp.tool(name=name, title=title, description=description, annotations=annotations)
        return registrato(gestisci_errori(fn))

    return decoratore


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

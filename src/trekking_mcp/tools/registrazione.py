"""Come un tool entra nel server: registrazione e contratto d'errore.

Un solo modo di registrare un tool, cosi' che la traduzione degli errori non si
possa dimenticare (§3.23). La geometria, che prima stava qui, e' in `geo.py`:
questo modulo parla di MCP e di niente altro.
"""

from __future__ import annotations

import functools
import logging
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


# Ogni tool di questo server legge e basta interrogando fonti esterne
SOLA_LETTURA = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def extended_tool(
    mcp: MCPServer,
    *,
    name: str,
    title: str,
    description: str,
    annotations: ToolAnnotations = SOLA_LETTURA,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Registra un tool con la traduzione degli errori gia' dentro."""

    def decoratore(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        registrato = mcp.tool(name=name, title=title, description=description, annotations=annotations)
        return registrato(gestisci_errori(fn))

    return decoratore

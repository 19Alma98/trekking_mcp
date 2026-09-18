from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import cast

from mcp.server.mcpserver import MCPServer
from mcp.types import (
    Completion,
    CompletionArgument,
    CompletionContext,
    PromptReference,
    ResourceTemplateReference,
)

from trekking_mcp.sources import caaml, eaws

URI_BOLLETTINO = "bollettino://{provider}/{zona_id}"
MAX_VALORI = 100

# Prefisso degli ID di zona per provider: AINEVA copre l'Italia, SLF la Svizzera.
PREFISSI_PROVIDER = {"aineva": "IT-", "slf": "CH-"}


def _filtra(candidati: list[str], parziale: str) -> Completion:
    inizio = parziale.casefold()
    trovati = sorted(c for c in candidati if c.casefold().startswith(inizio))
    return Completion(
        values=trovati[:MAX_VALORI],
        total=len(trovati),
        has_more=len(trovati) > MAX_VALORI,
    )


def zone_note(provider: str | None = None) -> list[str]:
    """ID di zona dall'indice EAWS gia' in memoria."""
    prefisso = PREFISSI_PROVIDER.get(provider or "")
    return [r.id_zona for r in eaws.INDICE.regioni if prefisso is None or r.id_zona.startswith(prefisso)]


_Handler = Callable[
    [PromptReference | ResourceTemplateReference, CompletionArgument, CompletionContext | None],
    Awaitable[Completion | None],
]


def registra(mcp: MCPServer) -> None:
    completion = cast(Callable[[], Callable[[_Handler], _Handler]], mcp.completion)

    @completion()
    async def completa(
        ref: PromptReference | ResourceTemplateReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        risolti = (context.arguments if context else None) or {}

        if isinstance(ref, ResourceTemplateReference) and ref.uri == URI_BOLLETTINO:
            if argument.name == "provider":
                return _filtra(list(caaml.PROVIDER), argument.value)
            if argument.name == "zona_id":
                return _filtra(zone_note(risolti.get("provider")), argument.value)
            return None

        if isinstance(ref, PromptReference) and ref.name == "spiega_bollettino" and argument.name == "zona_id":
            return _filtra(zone_note(), argument.value)

        return None

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

from trekking_mcp.constants import MAX_VALORI_COMPLETAMENTO, URI_BOLLETTINO
from trekking_mcp.risorse import Risorse
from trekking_mcp.sources import caaml


def _filtra(candidati: list[str], parziale: str) -> Completion:
    inizio = parziale.casefold()
    trovati = sorted(c for c in candidati if c.casefold().startswith(inizio))
    return Completion(
        values=trovati[:MAX_VALORI_COMPLETAMENTO],
        total=len(trovati),
        has_more=len(trovati) > MAX_VALORI_COMPLETAMENTO,
    )


def zone_note(risorse: Risorse, provider: str | None = None) -> list[str]:
    """ID di zona dall'indice EAWS gia' in memoria."""
    dati = caaml.PROVIDER.get(provider or "")
    prefisso = dati["prefisso_zone"] if dati else None
    return [r.id_zona for r in risorse.eaws.regioni if prefisso is None or r.id_zona.startswith(prefisso)]


_Handler = Callable[
    [PromptReference | ResourceTemplateReference, CompletionArgument, CompletionContext | None],
    Awaitable[Completion | None],
]


def registra(mcp: MCPServer, risorse: Risorse) -> None:
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
                return _filtra(zone_note(risorse, risolti.get("provider")), argument.value)
            return None

        if isinstance(ref, PromptReference) and ref.name == "spiega_bollettino" and argument.name == "zona_id":
            return _filtra(zone_note(risorse), argument.value)

        return None

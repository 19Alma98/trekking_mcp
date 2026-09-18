"""Freschezza dichiarata al client (SEP-2549, revisione 2026-07-28).

Il server sa gia' quanto vale ogni dato: `Config` ha un TTL per fonte, e
`CacheTTL` lo usa per la cache HTTP interna. Quella conoscenza pero' si fermava
al processo. Un client che rilegge `bollettino://aineva/IT-21-AO-01` tre volte
in cinque minuti faceva tre richieste, e il server rispondeva tre volte dalla
propria cache: lavoro inutile su entrambi i lati, che nessuno dei due poteva
evitare perche' la freschezza non era scritta da nessuna parte.

`ttlMs` e `cacheScope` la scrivono. Due meccanismi, perche' l'SDK ne offre due:

- **Gli elenchi** (`tools/list`, `prompts/list`, ...) prendono un hint per
  metodo, passato a `MCPServer(cache_hints=...)`. Qui sono statici: tutto viene
  registrato in `crea_server()` e non cambia piu' finche' il processo vive.
- **Le resource** hanno freschezze diverse fra loro, e l'hint per metodo e' uno
  solo. Un middleware le distingue per schema dell'URI: e' il posto giusto,
  perche' e' l'unico che vede insieme l'URI richiesto e il risultato.

`tools/call` non e' cacheabile e non compare qui: `CallToolResult` non ha i due
campi, ed e' corretto — il risultato di un tool dipende dagli argomenti, e
decidere per quanto vale non spetta al protocollo.
"""

from __future__ import annotations

from typing import Any

from mcp.server.caching import CacheableMethod, CacheHint
from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext

from trekking_mcp.config import Config
from trekking_mcp.constants import MS, TTL_ELENCHI_MS, TTL_SCALE_MS

CACHE_HINTS: dict[CacheableMethod, CacheHint] = {
    "tools/list": CacheHint(ttl_ms=TTL_ELENCHI_MS, scope="public"),
    "prompts/list": CacheHint(ttl_ms=TTL_ELENCHI_MS, scope="public"),
    "resources/list": CacheHint(ttl_ms=TTL_ELENCHI_MS, scope="public"),
    "resources/templates/list": CacheHint(ttl_ms=TTL_ELENCHI_MS, scope="public"),
    "server/discover": CacheHint(ttl_ms=TTL_ELENCHI_MS, scope="public"),
}


def freschezza_resource(uri: str, config: Config) -> CacheHint:
    """Quanto vale una resource, per schema dell'URI.

    `bollettino://` non ha un numero suo: prende `ttl_bollettino_s`, lo stesso
    valore che governa la cache HTTP interna. Un bollettino vale trenta minuti
    o non li vale; non puo' valerne trenta per il server e un'ora per il client.
    """
    if uri.startswith("metriche://"):
        # Contatori in memoria: cambiano a ogni chiamata a una fonte. Chi li
        # legge li vuole adesso. `private` perche' descrivono questo processo,
        # non un dato del dominio condivisibile fra contesti diversi.
        return CacheHint(ttl_ms=0, scope="private")
    if uri.startswith("bollettino://"):
        return CacheHint(ttl_ms=config.ttl_bollettino_s * MS, scope="public")
    if uri.startswith("scala://"):
        return CacheHint(ttl_ms=TTL_SCALE_MS, scope="public")
    return CacheHint(ttl_ms=0, scope="private")


class FreschezzaPerResource(ServerMiddleware[Any]):
    """Scrive `ttlMs`/`cacheScope` su ogni `resources/read`, secondo l'URI.

    Il middleware e' l'unico punto che vede insieme l'URI richiesto
    (`ctx.params`) e il risultato che sta tornando indietro. Le funzioni
    decorate con `@mcp.resource` restituiscono una stringa: non hanno modo di
    parlare dei campi del risultato.

    A questo punto della catena il risultato e' gia' un dict serializzato,
    quindi le chiavi sono quelle del protocollo, in camelCase. Non e' un
    dettaglio da indovinare: `test_freschezza.py` le rilegge attraverso un
    Client vero, cosi' se l'SDK cambiasse forma il test lo direbbe.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        risultato = await call_next(ctx)
        if ctx.method != "resources/read" or not isinstance(risultato, dict):
            return risultato

        uri = str((ctx.params or {}).get("uri", ""))
        hint = freschezza_resource(uri, self._config)
        return {**risultato, "ttlMs": hint.ttl_ms, "cacheScope": hint.scope}

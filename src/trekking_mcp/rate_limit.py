from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST, CallToolResult, TextContent

from trekking_mcp.config import Config
from trekking_mcp.constants import HTTP_RATE_LIMIT_MAX_KEYS_DEFAULT
from trekking_mcp.metriche import Metriche

log = logging.getLogger(__name__)

METODI_LIMITATI = frozenset({"tools/call", "resources/read"})


@dataclass
class TokenBucket:
    """Token bucket: capacita' = burst, ricarica a `rpm` token al minuto."""

    capacita: float
    rpm: float
    tokens: float = field(init=False)
    aggiornato_a: float = field(init=False)
    _orologio: Callable[[], float] = field(default=time.monotonic, repr=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacita
        self.aggiornato_a = self._orologio()

    def _ricarica(self, adesso: float) -> None:
        trascorso = max(0.0, adesso - self.aggiornato_a)
        self.tokens = min(self.capacita, self.tokens + trascorso * (self.rpm / 60.0))
        self.aggiornato_a = adesso

    def prova(self, costo: float = 1.0) -> float | None:
        """Consuma `costo` token. `None` se ok, altrimenti secondi di attesa."""
        adesso = self._orologio()
        self._ricarica(adesso)
        if self.tokens >= costo:
            self.tokens -= costo
            return None
        mancanti = costo - self.tokens
        return mancanti / (self.rpm / 60.0) if self.rpm > 0 else float("inf")


@dataclass
class RegistroBucket:
    """Un bucket per chiave (`anon:{ip}`), creati lazy, con tetto LRU."""

    capacita: float
    rpm: float
    max_keys: int = HTTP_RATE_LIMIT_MAX_KEYS_DEFAULT
    _bucket: OrderedDict[str, TokenBucket] = field(default_factory=OrderedDict)
    _orologio: Callable[[], float] = field(default=time.monotonic, repr=False)

    def __len__(self) -> int:
        return len(self._bucket)

    def prova(self, chiave: str) -> float | None:
        if chiave in self._bucket:
            self._bucket.move_to_end(chiave)
        else:
            while len(self._bucket) >= self.max_keys:
                self._bucket.popitem(last=False)
            self._bucket[chiave] = TokenBucket(
                capacita=self.capacita,
                rpm=self.rpm,
                _orologio=self._orologio,
            )
        return self._bucket[chiave].prova()


def _header_xff(headers: object | None) -> str | None:
    if headers is None:
        return None
    get = getattr(headers, "get", None)
    if not callable(get):
        if isinstance(headers, Mapping):
            grezzo = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
        else:
            return None
    else:
        grezzo = get("x-forwarded-for") or get("X-Forwarded-For")
    if grezzo is None:
        return None
    testo = grezzo if isinstance(grezzo, str) else str(grezzo)
    primo = testo.split(",")[0].strip()
    return primo or None


def ip_da_request(request: object | None, *, trust_proxy: bool = False) -> str | None:
    """Estrae l'IP del client da una Starlette `Request`, se c'e'.

    Con `trust_proxy=True` usa il primo hop di `X-Forwarded-For` (client
    originale). Abilitare solo dietro un reverse proxy che riscrive l'header.
    """
    if request is None:
        return None
    if trust_proxy:
        xff = _header_xff(getattr(request, "headers", None))
        if xff is not None:
            return xff
    client = getattr(request, "client", None)
    if client is None:
        return None
    host = getattr(client, "host", None)
    return str(host) if host else None


def metodo_da_limitare(method: str, params: dict[str, Any] | None) -> bool:
    if method == "tools/call":
        return True
    if method == "resources/read":
        uri = str((params or {}).get("uri", ""))
        return uri.startswith("bollettino://")
    return False


def _risultato_tool_limitato(attesa_s: float) -> dict[str, Any]:
    secondi = max(1, int(attesa_s + 0.999))
    messaggio = (
        f"Troppe richieste da questo indirizzo. Riprova tra circa {secondi} secondi (limite per IP sul transport HTTP)."
    )
    esito = CallToolResult(content=[TextContent(type="text", text=messaggio)], is_error=True)
    return esito.model_dump(by_alias=True, mode="json", exclude_none=True)


class RateLimitInbound(ServerMiddleware[Any]):
    """Tetto per IP su `tools/call` e `resources/read` di bollettini."""

    def __init__(
        self,
        config: Config,
        metriche: Metriche,
        *,
        orologio: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._metriche = metriche
        self._orologio = orologio or time.monotonic
        self._registro = RegistroBucket(
            capacita=float(max(1, config.http_rate_limit_burst)),
            rpm=float(max(0, config.http_rate_limit_rpm)),
            max_keys=config.http_rate_limit_max_keys,
            _orologio=self._orologio,
        )

    @property
    def attivo(self) -> bool:
        return self._config.http_rate_limit_rpm > 0

    async def __call__(self, ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if not self.attivo or not metodo_da_limitare(ctx.method, dict(ctx.params) if ctx.params else None):
            return await call_next(ctx)

        ip = ip_da_request(ctx.request, trust_proxy=self._config.http_trust_proxy)
        if ip is None:
            return await call_next(ctx)

        chiave = f"anon:{ip}"
        attesa = self._registro.prova(chiave)
        if attesa is None:
            return await call_next(ctx)

        self._metriche.rate_limit_inbound()
        log.info("rate-limit inbound chiave=%s method=%s attesa=%.1fs", chiave, ctx.method, attesa)

        if ctx.method == "tools/call":
            return _risultato_tool_limitato(attesa)

        secondi = max(1, int(attesa + 0.999))
        raise MCPError(
            code=INVALID_REQUEST,
            message=(
                f"Troppe richieste da questo indirizzo. Riprova tra circa {secondi} secondi "
                f"(limite per IP sul transport HTTP)."
            ),
        )

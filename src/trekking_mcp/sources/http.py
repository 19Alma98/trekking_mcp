from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from typing import Any

import httpx2

from trekking_mcp.config import CONFIG
from trekking_mcp.errors import FonteNonDisponibile

log = logging.getLogger(__name__)


class CacheTTL:
    """LRU con scadenza. Volutamente minimale: nessuna dipendenza esterna."""

    def __init__(self, max_entry: int = 512) -> None:
        self._dati: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_entry
        self._lock = asyncio.Lock()

    @staticmethod
    def chiave(*parti: Any) -> str:
        grezzo = json.dumps(parti, sort_keys=True, default=str)
        return hashlib.sha256(grezzo.encode()).hexdigest()[:32]

    async def get(self, chiave: str) -> Any | None:
        async with self._lock:
            voce = self._dati.get(chiave)
            if voce is None:
                return None
            scadenza, valore = voce
            if time.monotonic() > scadenza:
                del self._dati[chiave]
                return None
            self._dati.move_to_end(chiave)
            return valore

    async def set(self, chiave: str, valore: Any, ttl_s: int) -> None:
        async with self._lock:
            self._dati[chiave] = (time.monotonic() + ttl_s, valore)
            self._dati.move_to_end(chiave)
            while len(self._dati) > self._max:
                self._dati.popitem(last=False)

    async def svuota(self) -> None:
        async with self._lock:
            self._dati.clear()


class ClientHttp:
    """Wrapper su httpx2 con retry esponenziale e cache opzionale."""

    def __init__(self, cache: CacheTTL | None = None) -> None:
        self._client: httpx2.AsyncClient | None = None
        self.cache = cache or CacheTTL(CONFIG.cache_max_entry)

    async def avvia(self) -> None:
        if self._client is None:
            self._client = httpx2.AsyncClient(
                timeout=CONFIG.timeout_s,
                headers={"User-Agent": CONFIG.user_agent, "Accept-Encoding": "gzip"},
                follow_redirects=True,
            )

    async def chiudi(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def json(
        self,
        metodo: str,
        url: str,
        *,
        fonte: str,
        ttl_s: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """Esegue una richiesta e restituisce JSON, con cache e retry.

        Solleva `FonteNonDisponibile` (mai un'eccezione httpx2 grezza) cosi' il
        layer dei tool ha un solo tipo di errore da tradurre per il client.
        """
        if self._client is None:
            await self.avvia()
        assert self._client is not None

        usa_cache = ttl_s is not None and metodo.upper() in {"GET", "POST"}
        chiave = CacheTTL.chiave(metodo, url, kwargs.get("params"), kwargs.get("data"), kwargs.get("json"))

        if usa_cache and (cachato := await self.cache.get(chiave)) is not None:
            log.debug("cache hit %s %s", fonte, url)
            return cachato

        ultimo_errore: Exception | None = None
        for tentativo in range(CONFIG.max_retry):
            try:
                risposta = await self._client.request(metodo, url, **kwargs)
                if risposta.status_code in (429, 502, 503, 504):
                    raise httpx2.HTTPStatusError(
                        f"HTTP {risposta.status_code}", request=risposta.request, response=risposta
                    )
                if 400 <= risposta.status_code < 500:
                    raise FonteNonDisponibile(fonte=fonte, dettaglio=f"HTTP {risposta.status_code} (errore definitivo)")
                risposta.raise_for_status()
                dati = risposta.json()
                if usa_cache and ttl_s is not None:
                    await self.cache.set(chiave, dati, ttl_s)
                return dati
            except (httpx2.HTTPError, ValueError) as exc:
                ultimo_errore = exc
                if tentativo < CONFIG.max_retry - 1:
                    attesa = 2**tentativo
                    log.warning("%s: tentativo %d fallito (%s), riprovo tra %ds", fonte, tentativo + 1, exc, attesa)
                    await asyncio.sleep(attesa)

        raise FonteNonDisponibile(fonte=fonte, dettaglio=str(ultimo_errore)) from ultimo_errore


CLIENT = ClientHttp()

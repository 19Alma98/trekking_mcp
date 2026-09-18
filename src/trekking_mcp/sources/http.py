from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from collections import OrderedDict
from typing import Any

import httpx2

from trekking_mcp.config import Config
from trekking_mcp.constants import RETRY_AFTER_MAX_S
from trekking_mcp.errors import FonteNonDisponibile
from trekking_mcp.metriche import Metriche

log = logging.getLogger(__name__)

_RIFAI = object()


def secondi_retry_after(risposta: httpx2.Response) -> float | None:
    """Parse di `Retry-After` in secondi. Solo valori numerici (non HTTP-date)."""
    grezzo = risposta.headers.get("Retry-After")
    if grezzo is None:
        return None
    try:
        return max(0.0, float(grezzo.strip()))
    except ValueError:
        return None


def ritardo_retry(tentativo: int, retry_after: float | None = None) -> float:
    """Backoff con jitter; se c'è Retry-After, lo rispetta (più jitter piccolo)."""
    if retry_after is not None:
        return retry_after + random.uniform(0, 1)
    base = float(2**tentativo)
    return base + random.uniform(0, base)


class CacheTTL:
    """LRU con scadenza, con un tetto sia alle voci sia ai byte.

    Volutamente minimale: nessuna dipendenza esterna, e un'interfaccia piccola
    perche' chi volesse Redis sostituisce la classe, non i chiamanti.
    """

    def __init__(self, max_entry: int = 512, max_byte: int = 64 * 1024 * 1024) -> None:
        self._dati: OrderedDict[str, tuple[float, Any, int]] = OrderedDict()
        self._max = max_entry
        self._max_byte = max_byte
        self._byte = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def chiave(*parti: Any) -> str:
        grezzo = json.dumps(parti, sort_keys=True, default=str)
        return hashlib.sha256(grezzo.encode()).hexdigest()[:32]

    @property
    def byte(self) -> int:
        """Peso stimato di quanto c'e' in cache, per le metriche e per i test."""
        return self._byte

    async def get(self, chiave: str) -> Any | None:
        async with self._lock:
            voce = self._dati.get(chiave)
            if voce is None:
                return None
            scadenza, valore, _ = voce
            if time.monotonic() > scadenza:
                self._scarta(chiave)
                return None
            self._dati.move_to_end(chiave)
            return valore

    async def set(self, chiave: str, valore: Any, ttl_s: int, *, peso: int = 0) -> None:
        async with self._lock:
            if chiave in self._dati:
                self._scarta(chiave)
            if peso > self._max_byte:
                log.debug("risposta da %d byte oltre il tetto di cache: non memorizzata", peso)
                return
            self._dati[chiave] = (time.monotonic() + ttl_s, valore, peso)
            self._byte += peso
            while self._dati and (len(self._dati) > self._max or self._byte > self._max_byte):
                self._scarta(next(iter(self._dati)))

    def _scarta(self, chiave: str) -> None:
        """Rimuove una voce tenendo aggiornato il totale. Chiamare sotto lock."""
        _, _, peso = self._dati.pop(chiave)
        self._byte -= peso

    async def svuota(self) -> None:
        async with self._lock:
            self._dati.clear()
            self._byte = 0


class ClientHttp:
    """Wrapper su httpx2 con retry esponenziale, cache e coalescing."""

    def __init__(self, config: Config, metriche: Metriche, cache: CacheTTL | None = None) -> None:
        self._client: httpx2.AsyncClient | None = None
        self.config = config
        self.metriche = metriche
        self.cache = cache or CacheTTL(config.cache_max_entry, config.cache_max_byte)
        self._in_volo: dict[str, asyncio.Future[Any]] = {}

    async def avvia(self) -> None:
        if self._client is None:
            self._client = httpx2.AsyncClient(
                timeout=self.config.timeout_s,
                headers={"User-Agent": self.config.user_agent, "Accept-Encoding": "gzip"},
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
        max_retry: int | None = None,
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

        if usa_cache:
            if (cachato := await self.cache.get(chiave)) is not None:
                self.metriche.cache_hit(fonte)
                log.debug("cache hit %s %s", fonte, url)
                return cachato

            if (in_volo := self._in_volo.get(chiave)) is not None:
                log.debug("coalescing %s %s", fonte, url)
                risultato = await self._attendi(in_volo)
                if risultato is not _RIFAI:
                    self.metriche.coalescing(fonte)
                    return risultato

            self.metriche.cache_miss(fonte)
            return await self._guida(
                metodo, url, fonte=fonte, ttl_s=ttl_s, chiave=chiave, max_retry=max_retry, **kwargs
            )

        return await self._richiedi(metodo, url, fonte=fonte, ttl_s=None, chiave=chiave, max_retry=max_retry, **kwargs)

    async def _attendi(self, in_volo: asyncio.Future[Any]) -> Any:
        """Attende la richiesta identica gia' in corso."""
        await asyncio.wait([in_volo])
        if in_volo.cancelled():
            return _RIFAI
        return in_volo.result()

    async def _guida(
        self,
        metodo: str,
        url: str,
        *,
        fonte: str,
        ttl_s: int | None,
        chiave: str,
        max_retry: int | None,
        **kwargs: Any,
    ) -> Any:
        """Fa la richiesta come capofila, pubblicando l'esito a chi si accoda."""
        attesa: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._in_volo[chiave] = attesa
        try:
            dati = await self._richiedi(
                metodo, url, fonte=fonte, ttl_s=ttl_s, chiave=chiave, max_retry=max_retry, **kwargs
            )
        except asyncio.CancelledError:
            attesa.cancel()
            raise
        except BaseException as exc:
            attesa.set_exception(exc)
            attesa.exception()
            raise
        else:
            attesa.set_result(dati)
            return dati
        finally:
            self._in_volo.pop(chiave, None)

    async def _richiedi(
        self,
        metodo: str,
        url: str,
        *,
        fonte: str,
        ttl_s: int | None,
        chiave: str,
        max_retry: int | None,
        **kwargs: Any,
    ) -> Any:
        """Una richiesta con i suoi retry. Non consulta la cache: la popola."""
        assert self._client is not None

        ultimo_errore: Exception | None = None
        tentativi = self.config.max_retry if max_retry is None else max_retry
        for tentativo in range(tentativi):
            avvio = time.perf_counter()
            try:
                risposta = await self._client.request(metodo, url, **kwargs)
                self.metriche.chiamata(fonte, (time.perf_counter() - avvio) * 1000)
                self.metriche.stato_http(fonte, risposta.status_code)
                if risposta.status_code in (429, 502, 503, 504):
                    raise httpx2.HTTPStatusError(
                        f"HTTP {risposta.status_code}", request=risposta.request, response=risposta
                    )
                if 400 <= risposta.status_code < 500:
                    self.metriche.errore(fonte)
                    raise FonteNonDisponibile(fonte=fonte, dettaglio=f"HTTP {risposta.status_code} (errore definitivo)")
                risposta.raise_for_status()
                dati = risposta.json()
                if ttl_s is not None:
                    await self.cache.set(chiave, dati, ttl_s, peso=len(risposta.content))
                return dati
            except (httpx2.HTTPError, ValueError) as exc:
                ultimo_errore = exc
                retry_after = None
                if isinstance(exc, httpx2.HTTPStatusError) and exc.response is not None:
                    retry_after = secondi_retry_after(exc.response)

                if retry_after is not None and retry_after > RETRY_AFTER_MAX_S:
                    self.metriche.errore(fonte)
                    raise FonteNonDisponibile(
                        fonte=fonte,
                        dettaglio=f"la fonte chiede di attendere {retry_after:.0f}s, oltre il tetto di "
                        f"{RETRY_AFTER_MAX_S:.0f}s: non resto in attesa",
                    ) from exc

                if tentativo < tentativi - 1:
                    attesa = ritardo_retry(tentativo, retry_after)
                    self.metriche.retry(fonte)
                    log.warning(
                        "%s: tentativo %d fallito (%s), riprovo tra %.1fs",
                        fonte,
                        tentativo + 1,
                        exc,
                        attesa,
                    )
                    await asyncio.sleep(attesa)

        self.metriche.errore(fonte)
        raise FonteNonDisponibile(fonte=fonte, dettaglio=str(ultimo_errore)) from ultimo_errore

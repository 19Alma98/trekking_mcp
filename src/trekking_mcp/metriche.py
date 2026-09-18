from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from trekking_mcp.constants import CAMPIONI_LATENZA


def _percentile(valori: list[float], q: float) -> float:
    """Percentile per rango, senza interpolazione."""
    if not valori:
        return 0.0
    ordinati = sorted(valori)
    indice = min(len(ordinati) - 1, max(0, math.ceil(q * len(ordinati)) - 1))
    return ordinati[indice]


class Latenze(BaseModel):
    p50_ms: int
    p95_ms: int
    max_ms: int


class SintesiFonte(BaseModel):
    """Quanto e' costata una fonte, dall'avvio del processo."""

    chiamate: int = Field(description="Richieste effettivamente uscite in rete")
    errori: int = Field(description="Richieste finite in FonteNonDisponibile dopo i retry")
    retry: int = Field(description="Tentativi ripetuti dopo un errore ritentabile")
    rate_limit: int = Field(description="Risposte 429")
    server_error: int = Field(description="Risposte 5xx")
    cache_hit: int
    cache_miss: int
    cache_hit_rate: float | None = Field(description="None se la fonte non usa la cache")
    coalescing: int = Field(
        default=0,
        description=(
            "Richieste identiche accodate a una gia' in corso invece di uscire in rete. "
            "Contatore separato dai cache hit: non hanno trovato nulla in cache, hanno "
            "aspettato chi ce lo stava mettendo."
        ),
    )
    latenza: Latenze


class SintesiMetriche(BaseModel):
    fonti: dict[str, SintesiFonte]
    nota: str = Field(
        default=(
            "Contatori in memoria del singolo processo, azzerati a ogni riavvio. Con piu' repliche ognuna ha i propri."
        )
    )


@dataclass
class _StatFonte:
    chiamate: int = 0
    errori: int = 0
    retry: int = 0
    rate_limit: int = 0
    server_error: int = 0
    cache_hit: int = 0
    cache_miss: int = 0
    coalescing: int = 0
    latenze_ms: deque[float] = field(default_factory=lambda: deque(maxlen=CAMPIONI_LATENZA))

    def sintesi(self) -> SintesiFonte:
        campioni = list(self.latenze_ms)
        letture = self.cache_hit + self.cache_miss
        return SintesiFonte(
            chiamate=self.chiamate,
            errori=self.errori,
            retry=self.retry,
            rate_limit=self.rate_limit,
            server_error=self.server_error,
            cache_hit=self.cache_hit,
            cache_miss=self.cache_miss,
            cache_hit_rate=round(self.cache_hit / letture, 3) if letture else None,
            coalescing=self.coalescing,
            latenza=Latenze(
                p50_ms=round(_percentile(campioni, 0.50)),
                p95_ms=round(_percentile(campioni, 0.95)),
                max_ms=round(max(campioni, default=0.0)),
            ),
        )


class Metriche:
    """Registro dei contatori, una riga per fonte."""

    def __init__(self) -> None:
        self._fonti: dict[str, _StatFonte] = {}

    def _stat(self, fonte: str) -> _StatFonte:
        if fonte not in self._fonti:
            self._fonti[fonte] = _StatFonte()
        return self._fonti[fonte]

    def cache_hit(self, fonte: str) -> None:
        self._stat(fonte).cache_hit += 1

    def cache_miss(self, fonte: str) -> None:
        self._stat(fonte).cache_miss += 1

    def coalescing(self, fonte: str) -> None:
        self._stat(fonte).coalescing += 1

    def chiamata(self, fonte: str, durata_ms: float) -> None:
        stat = self._stat(fonte)
        stat.chiamate += 1
        stat.latenze_ms.append(durata_ms)

    def retry(self, fonte: str) -> None:
        self._stat(fonte).retry += 1

    def errore(self, fonte: str) -> None:
        self._stat(fonte).errori += 1

    def stato_http(self, fonte: str, codice: int) -> None:
        stat = self._stat(fonte)
        if codice == 429:
            stat.rate_limit += 1
        elif codice >= 500:
            stat.server_error += 1

    def istantanea(self) -> SintesiMetriche:
        return SintesiMetriche(fonti={nome: stat.sintesi() for nome, stat in sorted(self._fonti.items())})

    def riga_di_log(self) -> str:
        """Una riga leggibile per il log di spegnimento."""
        pezzi = []
        for nome, stat in sorted(self._fonti.items()):
            s = stat.sintesi()
            pezzi.append(
                f"{nome}: {s.chiamate} chiamate, {s.errori} errori, "
                f"p50 {s.latenza.p50_ms}ms, p95 {s.latenza.p95_ms}ms, "
                f"cache {s.cache_hit}/{s.cache_hit + s.cache_miss}"
            )
        return " | ".join(pezzi) if pezzi else "nessuna chiamata a fonti esterne"

    def azzera(self) -> None:
        self._fonti.clear()

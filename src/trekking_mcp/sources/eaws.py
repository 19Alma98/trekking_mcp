"""Micro-regioni EAWS: dal punto sulla mappa all'ID della zona valanghe.

Fonte: progetto EAWS Regions (regions.avalanches.org).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from trekking_mcp.config import Config
from trekking_mcp.errors import FonteNonDisponibile, NonTrovato
from trekking_mcp.geo import Anello, Riquadro, anelli_di_geometria, contiene, nel_riquadro, riquadro_di
from trekking_mcp.payloads import EawsFeatureCollection
from trekking_mcp.sources.http import ClientHttp

log = logging.getLogger(__name__)

ATTRIBUZIONE = "Perimetri delle zone valanghe: progetto EAWS Regions (regions.avalanches.org)"


@dataclass(frozen=True)
class MicroRegione:
    """Una zona del bollettino, con il suo perimetro gia' normalizzato."""

    id_zona: str
    nome: str | None
    riquadro: Riquadro
    poligoni: list[list[Anello]]

    def contiene(self, lat: float, lon: float) -> bool:
        if not nel_riquadro(lat, lon, self.riquadro):
            return False
        return contiene(lat, lon, self.poligoni)


class IndiceRegioni:
    """Indice in memoria delle micro-regioni, caricato pigramente."""

    def __init__(self, config: Config, http: ClientHttp) -> None:
        self._config = config
        self._http = http
        self._regioni: list[MicroRegione] = []
        self._territori_caricati: set[str] = set()
        self._lock = asyncio.Lock()

    @property
    def caricato(self) -> bool:
        return bool(self._regioni)

    @property
    def regioni(self) -> Sequence[MicroRegione]:
        """Le micro-regioni in indice, in sola lettura."""
        return self._regioni

    def _percorso_cache(self, territorio: str) -> Path:
        cartella = Path(self._config.cache_dir).expanduser()
        cartella.mkdir(parents=True, exist_ok=True)
        return cartella / f"eaws_{territorio}.geojson"

    async def _scarica(self, territorio: str) -> EawsFeatureCollection:
        """Legge dalla cache su disco, o scarica se assente o scaduta."""
        percorso = self._percorso_cache(territorio)

        if percorso.exists():
            eta = time.time() - percorso.stat().st_mtime
            if eta < self._config.ttl_regioni_s:
                log.debug("regioni %s dalla cache su disco", territorio)
                return cast(EawsFeatureCollection, json.loads(percorso.read_text(encoding="utf-8")))

        url = f"{self._config.eaws_regions_url}/micro-regions/{territorio}_micro-regions.geojson.json"
        log.info("scarico i perimetri %s", territorio)
        dati = cast(EawsFeatureCollection, await self._http.json("GET", url, fonte="eaws-regions", ttl_s=None))

        temporaneo = percorso.with_suffix(".tmp")
        temporaneo.write_text(json.dumps(dati), encoding="utf-8")
        temporaneo.replace(percorso)
        return dati

    def _indicizza(self, geojson: EawsFeatureCollection) -> int:
        aggiunte = 0
        for feature in geojson.get("features") or []:
            proprieta = feature.get("properties") or {}
            id_zona = proprieta.get("id") or proprieta.get("regionID")
            if not id_zona:
                continue

            poligoni = anelli_di_geometria(feature.get("geometry") or {})
            if not poligoni:
                continue

            anelli_esterni = [poligono[0] for poligono in poligoni if poligono]
            self._regioni.append(
                MicroRegione(
                    id_zona=str(id_zona),
                    nome=proprieta.get("name") or proprieta.get("name_it"),
                    riquadro=riquadro_di(anelli_esterni),
                    poligoni=poligoni,
                )
            )
            aggiunte += 1
        return aggiunte

    async def carica(self, territori: Sequence[str] | None = None) -> None:
        """Carica i territori richiesti, saltando quelli gia' in indice.

        L'elenco di default e' `Config.eaws_territori`: e' li' perche' quali
        territori indicizzare decide anche quali zone sa risolvere
        `zona_valanghe_da_coordinate` e quali `zona_id` si autocompletano, quindi
        e' configurazione, non una costante di questo modulo.
        """
        async with self._lock:
            for territorio in territori if territori is not None else self._config.eaws_territori:
                if territorio in self._territori_caricati:
                    continue
                try:
                    geojson = await self._scarica(territorio)
                except (FonteNonDisponibile, json.JSONDecodeError) as exc:
                    log.warning("perimetri %s non disponibili: %s", territorio, exc)
                    continue

                aggiunte = self._indicizza(geojson)
                self._territori_caricati.add(territorio)
                log.info("indicizzate %d micro-regioni per %s", aggiunte, territorio)

    async def cerca(self, lat: float, lon: float) -> list[MicroRegione]:
        """Micro-regioni che contengono il punto."""
        if not self.caricato:
            await self.carica()
        return [r for r in self._regioni if r.contiene(lat, lon)]

    def svuota(self) -> None:
        self._regioni.clear()
        self._territori_caricati.clear()


async def zona_da_coordinate(indice: IndiceRegioni, lat: float, lon: float) -> MicroRegione:
    """Micro-regione del punto, o `NonTrovato` con le zone piu' vicine."""
    trovate = await indice.cerca(lat, lon)
    if trovate:
        return trovate[0]

    raise NonTrovato(
        "zona valanghe per le coordinate",
        f"{lat:.4f},{lon:.4f}",
        alternative=_vicine(indice, lat, lon),
    )


def _vicine(indice: IndiceRegioni, lat: float, lon: float, quante: int = 5) -> list[str]:
    """Zone il cui riquadro e' piu' vicino al punto.

    Serve solo a dare un suggerimento utile nel messaggio d'errore: se un
    utente sbaglia di poco le coordinate, vede subito quali zone stanno
    attorno invece di un rifiuto secco.
    """

    def distanza(regione: MicroRegione) -> float:
        ovest, sud, est, nord = regione.riquadro
        dx = max(ovest - lon, 0.0, lon - est)
        dy = max(sud - lat, 0.0, lat - nord)
        return dx * dx + dy * dy

    return [r.id_zona for r in sorted(indice.regioni, key=distanza)[:quante]]

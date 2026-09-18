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

import anyio.to_thread

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

    def _leggi_da_disco(self, territorio: str) -> EawsFeatureCollection | None:
        """Sincrona di proposito: gira in un thread. Vedi `_scarica`."""
        percorso = self._percorso_cache(territorio)
        if not percorso.exists():
            return None
        if time.time() - percorso.stat().st_mtime >= self._config.ttl_regioni_s:
            return None
        log.debug("regioni %s dalla cache su disco", territorio)
        return cast(EawsFeatureCollection, json.loads(percorso.read_text(encoding="utf-8")))

    def _scrivi_su_disco(self, territorio: str, dati: EawsFeatureCollection) -> None:
        """Scrittura atomica: piu' repliche sullo stesso disco al peggio riscaricano."""
        percorso = self._percorso_cache(territorio)
        temporaneo = percorso.with_suffix(".tmp")
        temporaneo.write_text(json.dumps(dati), encoding="utf-8")
        temporaneo.replace(percorso)

    async def _scarica(self, territorio: str) -> EawsFeatureCollection:
        """Legge dalla cache su disco, o scarica se assente o scaduta.

        Lettura, scrittura e `json.loads` passano da `anyio.to_thread`: sono file
        da qualche MB, e farli sull'event loop blocca *tutto* il server — la prima
        ricerca di una zona valanghe fermava anche le richieste che non
        c'entravano nulla. Un `await` che non cede il controllo e' peggio di un
        `await` lento, perche' non si vede.
        """
        if (da_disco := await anyio.to_thread.run_sync(self._leggi_da_disco, territorio)) is not None:
            return da_disco

        url = f"{self._config.eaws_regions_url}/micro-regions/{territorio}_micro-regions.geojson.json"
        log.info("scarico i perimetri %s", territorio)
        dati = cast(EawsFeatureCollection, await self._http.json("GET", url, fonte="eaws-regions", ttl_s=None))

        await anyio.to_thread.run_sync(self._scrivi_su_disco, territorio, dati)
        return dati

    @staticmethod
    def _micro_regioni(geojson: EawsFeatureCollection) -> list[MicroRegione]:
        """Normalizza i perimetri in oggetti pronti all'uso.

        Pura e statica perche' gira in un thread (vedi `carica`): un poligono
        EAWS ha migliaia di vertici e ognuno diventa una tupla di float, il che
        per nove territori e' un lavoro che l'event loop non deve fare.
        """
        regioni: list[MicroRegione] = []
        for feature in geojson.get("features") or []:
            proprieta = feature.get("properties") or {}
            id_zona = proprieta.get("id") or proprieta.get("regionID")
            if not id_zona:
                continue

            poligoni = anelli_di_geometria(feature.get("geometry") or {})
            if not poligoni:
                continue

            anelli_esterni = [poligono[0] for poligono in poligoni if poligono]
            regioni.append(
                MicroRegione(
                    id_zona=str(id_zona),
                    nome=proprieta.get("name") or proprieta.get("name_it"),
                    riquadro=riquadro_di(anelli_esterni),
                    poligoni=poligoni,
                )
            )
        return regioni

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

                nuove = await anyio.to_thread.run_sync(self._micro_regioni, geojson)
                # L'append e' l'unico pezzo che tocca lo stato condiviso, e sta
                # sull'event loop senza await in mezzo: nessuno puo' vedere
                # l'indice a meta'.
                self._regioni.extend(nuove)
                self._territori_caricati.add(territorio)
                log.info("indicizzate %d micro-regioni per %s", len(nuove), territorio)

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

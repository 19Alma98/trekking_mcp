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

from trekking_mcp.config import CONFIG
from trekking_mcp.errors import FonteNonDisponibile, NonTrovato
from trekking_mcp.geo import Anello, Riquadro, anelli_di_geometria, contiene, nel_riquadro, riquadro_di
from trekking_mcp.payloads import EawsFeatureCollection
from trekking_mcp.sources.http import CLIENT

log = logging.getLogger(__name__)

ATTRIBUZIONE = "Perimetri delle zone valanghe: progetto EAWS Regions (regions.avalanches.org)"

# Codici dei file per territorio. IT-21 = Piemonte, IT-23 = Valle d'Aosta,
# IT-25 = Lombardia, IT-32-BZ = Bolzano, IT-32-TN = Trento, IT-34 = Veneto,
# IT-36 = Friuli, IT-57 = Marche. CH = Svizzera.
TERRITORI_ITALIA = [
    "IT-21",
    "IT-23",
    "IT-25",
    "IT-32-BZ",
    "IT-32-TN",
    "IT-34",
    "IT-36",
    "IT-57",
]


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

    def __init__(self) -> None:
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
        cartella = Path(CONFIG.cache_dir).expanduser()
        cartella.mkdir(parents=True, exist_ok=True)
        return cartella / f"eaws_{territorio}.geojson"

    async def _scarica(self, territorio: str) -> EawsFeatureCollection:
        """Legge dalla cache su disco, o scarica se assente o scaduta."""
        percorso = self._percorso_cache(territorio)

        if percorso.exists():
            eta = time.time() - percorso.stat().st_mtime
            if eta < CONFIG.ttl_regioni_s:
                log.debug("regioni %s dalla cache su disco", territorio)
                return cast(EawsFeatureCollection, json.loads(percorso.read_text(encoding="utf-8")))

        url = f"{CONFIG.eaws_regions_url}/micro-regions/{territorio}_micro-regions.geojson.json"
        log.info("scarico i perimetri %s", territorio)
        dati = cast(EawsFeatureCollection, await CLIENT.json("GET", url, fonte="eaws-regions", ttl_s=None))

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

    async def carica(self, territori: list[str] | None = None) -> None:
        """Carica i territori richiesti, saltando quelli gia' in indice.

        Un territorio che non si scarica non blocca gli altri: meglio un indice
        parziale che nessun indice. Il buco viene loggato.

        Il lock serializza i caricamenti concorrenti, e non e' un lusso: il
        controllo su `_territori_caricati` sta prima di un await, ma l'insieme
        viene aggiornato solo dopo. Due tool chiamati insieme -- il caso
        normale con un agente che fa fan-out -- passerebbero entrambi il
        controllo, scaricherebbero lo stesso territorio due volte e lascerebbero
        in indice micro-regioni duplicate, per sempre: `zona_da_coordinate` se
        ne accorge poco, ma i completamenti e i suggerimenti di `_vicine`
        finiscono per proporre lo stesso ID piu' volte.
        """
        async with self._lock:
            for territorio in territori or TERRITORI_ITALIA:
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
        """Micro-regioni che contengono il punto.

        Normalmente e' una sola. Puo' essere vuota (fuori dall'area coperta) o
        contenere piu' elementi sui confini, dove i perimetri si sovrappongono
        di qualche metro: in quel caso si restituiscono tutte e si lascia
        decidere a chi chiama.
        """
        # Controllo fuori dal lock per non pagarlo sul caso comune (indice
        # gia' pronto); `carica` lo riprende e ricontrolla, quindi il secondo
        # chiamante concorrente non riscarica niente.
        if not self.caricato:
            await self.carica()
        return [r for r in self._regioni if r.contiene(lat, lon)]

    def svuota(self) -> None:
        self._regioni.clear()
        self._territori_caricati.clear()


INDICE = IndiceRegioni()


async def zona_da_coordinate(lat: float, lon: float) -> MicroRegione:
    """Micro-regione del punto, o `NonTrovato` con le zone piu' vicine."""
    trovate = await INDICE.cerca(lat, lon)
    if trovate:
        return trovate[0]

    raise NonTrovato(
        "zona valanghe per le coordinate",
        f"{lat:.4f},{lon:.4f}",
        alternative=_vicine(lat, lon),
    )


def _vicine(lat: float, lon: float, quante: int = 5) -> list[str]:
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

    return [r.id_zona for r in sorted(INDICE.regioni, key=distanza)[:quante]]

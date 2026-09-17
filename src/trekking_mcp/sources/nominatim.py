"""Ricerca per toponimo (geocoding) via Nominatim."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import cast

from trekking_mcp.config import CONFIG
from trekking_mcp.models import Coord, Localita
from trekking_mcp.payloads import NominatimExtratags, NominatimResult
from trekking_mcp.sources.http import CLIENT
from trekking_mcp.tools.comuni import distanza_km, riquadro_intorno

log = logging.getLogger(__name__)

ATTRIBUZIONE = "Geocoding: Nominatim / (c) contributori OpenStreetMap, ODbL"

# Riquadro approssimato dell'arco alpino e appenninico italiano, usato per
# spingere i risultati verso la montagna: "Balme" senza vincolo geografico
# restituisce risultati in mezzo mondo.
RIQUADRO_ITALIA = (6.6, 35.4, 18.6, 47.1)  # ovest, sud, est, nord

TIPI_UTILI = {
    "peak",
    "saddle",
    "alpine_hut",
    "wilderness_hut",
    "village",
    "hamlet",
    "town",
    "locality",
    "isolated_dwelling",
    "viewpoint",
    "valley",
}


class Limitatore:
    """Garantisce un intervallo minimo fra richieste consecutive."""

    def __init__(self, intervallo_s: float) -> None:
        self._intervallo = intervallo_s
        self._ultima = 0.0
        self._lock = asyncio.Lock()

    async def attendi(self) -> None:
        async with self._lock:
            trascorso = time.monotonic() - self._ultima
            if trascorso < self._intervallo:
                await asyncio.sleep(self._intervallo - trascorso)
            self._ultima = time.monotonic()


LIMITATORE = Limitatore(CONFIG.nominatim_intervallo_s)


def _quota(extratags: NominatimExtratags | None) -> int | None:
    if not extratags:
        return None
    for chiave in ("ele", "ele:m"):
        if valore := extratags.get(chiave):
            try:
                return int(float(str(valore).replace("m", "").strip()))
            except ValueError:
                continue
    return None


def _viewbox(lat: float, lon: float, raggio_km: float) -> str:
    """Nominatim: left,top,right,bottom = ovest,nord,est,sud."""
    sud, ovest, nord, est = riquadro_intorno(lat, lon, raggio_km)
    return f"{ovest},{nord},{est},{sud}"


async def cerca(
    nome: str,
    *,
    limite: int = 5,
    solo_montagna: bool = True,
    lat: float | None = None,
    lon: float | None = None,
    raggio_km: float = 50,
) -> list[Localita]:
    """Cerca un toponimo e restituisce i candidati piu' plausibili."""
    contestuale = lat is not None and lon is not None
    if contestuale:
        viewbox = _viewbox(cast(float, lat), cast(float, lon), raggio_km)
        bounded = 1
    else:
        ovest, sud, est, nord = RIQUADRO_ITALIA
        viewbox = f"{ovest},{nord},{est},{sud}"
        bounded = 0

    async def _richiedi(*, solo_montagna_eff: bool, bounded_eff: int) -> list[Localita]:
        await LIMITATORE.attendi()
        grezzo = await CLIENT.json(
            "GET",
            CONFIG.nominatim_url,
            fonte="nominatim",
            ttl_s=CONFIG.ttl_overpass_s,
            params={
                "q": nome,
                "format": "jsonv2",
                "limit": max(limite * 3, 10),
                "extratags": 1,
                "countrycodes": "it,ch,fr,at,si",
                "viewbox": viewbox,
                "bounded": bounded_eff,
                "accept-language": "it",
            },
        )
        risultati: list[Localita] = []
        voci = cast(list[NominatimResult], grezzo) if isinstance(grezzo, list) else []
        for voce in voci:
            tipo = voce.get("type")
            if solo_montagna_eff and tipo not in TIPI_UTILI:
                continue
            try:
                coord = Coord(lat=float(voce["lat"]), lon=float(voce["lon"]))
            except (KeyError, ValueError):
                continue
            osm_tipo, osm_id = voce.get("osm_type"), voce.get("osm_id")
            risultati.append(
                Localita(
                    nome=voce.get("display_name") or nome,
                    tipo=tipo,
                    coord=coord,
                    quota_m=_quota(voce.get("extratags")),
                    osm_url=(f"https://www.openstreetmap.org/{osm_tipo}/{osm_id}" if osm_tipo and osm_id else None),
                )
            )
        if contestuale:
            assert lat is not None and lon is not None
            risultati.sort(key=lambda loc: distanza_km(lat, lon, loc.coord.lat, loc.coord.lon))
        return risultati[:limite]

    risultati = await _richiedi(solo_montagna_eff=solo_montagna, bounded_eff=bounded)
    if not risultati and solo_montagna:
        risultati = await _richiedi(solo_montagna_eff=False, bounded_eff=bounded)
    if not risultati and contestuale and bounded == 1:
        risultati = await _richiedi(solo_montagna_eff=False, bounded_eff=0)
    return risultati

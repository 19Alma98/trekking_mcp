"""Ricerca per toponimo (geocoding) via Nominatim."""

from __future__ import annotations

import asyncio
import logging
import time

from trekking_mcp.config import CONFIG
from trekking_mcp.models import Coord, Localita
from trekking_mcp.sources.http import CLIENT

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


def _quota(extratags: dict | None) -> int | None:
    if not extratags:
        return None
    for chiave in ("ele", "ele:m"):
        if valore := extratags.get(chiave):
            try:
                return int(float(str(valore).replace("m", "").strip()))
            except ValueError:
                continue
    return None


async def cerca(nome: str, *, limite: int = 5, solo_montagna: bool = True) -> list[Localita]:
    """Cerca un toponimo e restituisce i candidati piu' plausibili."""
    await LIMITATORE.attendi()

    ovest, sud, est, nord = RIQUADRO_ITALIA
    dati = await CLIENT.json(
        "GET",
        CONFIG.nominatim_url,
        fonte="nominatim",
        ttl_s=CONFIG.ttl_overpass_s,
        params={
            "q": nome,
            "format": "jsonv2",
            "limit": max(limite * 3, 10),  # si filtra dopo, quindi si chiede largo
            "extratags": 1,
            "countrycodes": "it,ch,fr,at,si",
            "viewbox": f"{ovest},{nord},{est},{sud}",
            "bounded": 0,
            "accept-language": "it",
        },
    )

    risultati: list[Localita] = []
    for voce in dati if isinstance(dati, list) else []:
        tipo = voce.get("type")
        if solo_montagna and tipo not in TIPI_UTILI:
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
                osm_url=f"https://www.openstreetmap.org/{osm_tipo}/{osm_id}" if osm_tipo and osm_id else None,
            )
        )

    if not risultati and solo_montagna:
        return await cerca(nome, limite=limite, solo_montagna=False)

    return risultati[:limite]

from __future__ import annotations

import difflib
import logging
from typing import TYPE_CHECKING

from trekking_mcp.config import Config
from trekking_mcp.errors import FonteNonDisponibile
from trekking_mcp.geo import distanza_km, riquadro_intorno
from trekking_mcp.models import Coord, Localita
from trekking_mcp.payloads import OverpassElement
from trekking_mcp.sources import overpass

if TYPE_CHECKING:
    from trekking_mcp.risorse import Risorse

log = logging.getLogger(__name__)

SOGLIA_SIMILARITA = 0.55
MAX_CANDIDATI_SIMILI = 3
_MAX_ELEMENTI_OUT = 500

# I tipi di luogo che contano per la disambiguazione di un toponimo, con il tag
# OSM che li identifica. Era tre elenchi in tre posti diversi: la query, il
# riconoscimento del tipo e il filtro di `nominatim`.
TIPI_LUOGO: dict[str, frozenset[str]] = {
    "natural": frozenset({"peak", "saddle"}),
    "tourism": frozenset({"alpine_hut", "wilderness_hut"}),
    "place": frozenset({"village", "hamlet", "town", "locality", "isolated_dwelling"}),
}

# Prefissi generici dei toponimi di montagna: "Monte Rosa" e "Rosa" sono lo
# stesso posto, e chi scrive in chat ne omette meta'. Condiviso con
# `tools.sentieri.testo_da_toponimo`.
PREFISSI_TOPONIMO = frozenset(
    {
        "monte",
        "mont",
        "monti",
        "cima",
        "pizzo",
        "col",
        "colle",
        "passo",
        "rifugio",
        "bivacco",
    }
)


def query_luoghi_bbox(config: Config, sud: float, ovest: float, nord: float, est: float) -> str:
    """Tutti i luoghi nominabili in un riquadro, per cercarne uno somigliante.

    L'intestazione e il formato del riquadro arrivano da `overpass`: erano
    riscritti qui, e una seconda copia del preambolo significa un timeout che
    puo' divergere da quello vero.
    """
    riquadro = overpass.bbox(sud, ovest, nord, est)
    selettori = "".join(
        f'{elemento}["{chiave}"~"^({"|".join(sorted(valori))})$"]({riquadro});'
        for chiave, valori in TIPI_LUOGO.items()
        for elemento in ("node", "way")
    )
    return overpass.intestazione(config) + "(" + selettori + ");" + f"out tags center {_MAX_ELEMENTI_OUT};"


def _tipo_da_tags(tags: dict[str, str]) -> str | None:
    for chiave, valori in TIPI_LUOGO.items():
        valore = tags.get(chiave)
        if valore in valori:
            return valore
    return None


def _quota_tags(tags: dict[str, str]) -> int | None:
    raw = tags.get("ele") or tags.get("ele:m")
    if not raw:
        return None
    try:
        return int(float(str(raw).replace("m", "").strip()))
    except ValueError:
        return None


def localita_da_elemento(el: OverpassElement) -> Localita | None:
    tags = el.get("tags") or {}
    nome = tags.get("name")
    if not nome:
        return None
    tipo = _tipo_da_tags(tags)
    if tipo is None:
        return None
    if "lat" in el and "lon" in el:
        lat, lon = float(el["lat"]), float(el["lon"])
    elif "center" in el:
        lat, lon = float(el["center"]["lat"]), float(el["center"]["lon"])
    else:
        return None
    osm_type = el.get("type")
    osm_id = el.get("id")
    return Localita(
        nome=nome,
        tipo=tipo,
        coord=Coord(lat=lat, lon=lon),
        quota_m=_quota_tags(tags),
        osm_url=(f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_type and osm_id else None),
    )


def normalizza_nome_luogo(nome: str) -> str:
    parti = nome.strip().casefold().split()
    while len(parti) >= 2 and parti[0] in PREFISSI_TOPONIMO:
        parti = parti[1:]
    return " ".join(parti)


def similarita_nome(query: str, candidato: str) -> float:
    return difflib.SequenceMatcher(
        None,
        normalizza_nome_luogo(query),
        normalizza_nome_luogo(candidato),
    ).ratio()


def filtra_simili(
    query: str,
    candidati: list[Localita],
    *,
    lat: float,
    lon: float,
) -> list[Localita]:
    scored: list[tuple[float, float, Localita]] = []
    for loc in candidati:
        ratio = similarita_nome(query, loc.nome)
        if ratio < SOGLIA_SIMILARITA:
            continue
        d = distanza_km(lat, lon, loc.coord.lat, loc.coord.lon)
        scored.append((ratio, d, loc))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [loc for _, _, loc in scored[:MAX_CANDIDATI_SIMILI]]


async def cerca_simili_nel_raggio(
    risorse: Risorse,
    nome: str,
    *,
    lat: float,
    lon: float,
    raggio_km: float,
) -> list[Localita]:
    sud, ovest, nord, est = riquadro_intorno(lat, lon, raggio_km)
    try:
        dati = await overpass.esegui(risorse, query_luoghi_bbox(risorse.config, sud, ovest, nord, est))
    except FonteNonDisponibile as exc:
        log.warning("overpass luoghi simili non disponibile: %s", exc)
        return []
    grezzi: list[Localita] = []
    for el in dati.get("elements", []):
        loc = localita_da_elemento(el)
        if loc is None:
            continue
        if distanza_km(lat, lon, loc.coord.lat, loc.coord.lon) > raggio_km:
            continue
        grezzi.append(loc)
    return filtra_simili(nome, grezzi, lat=lat, lon=lon)

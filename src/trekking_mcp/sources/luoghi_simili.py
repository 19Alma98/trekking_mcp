from __future__ import annotations

import difflib
import logging

from trekking_mcp.config import CONFIG
from trekking_mcp.errors import FonteNonDisponibile
from trekking_mcp.models import Coord, Localita
from trekking_mcp.payloads import OverpassElement
from trekking_mcp.sources import overpass
from trekking_mcp.tools.comuni import distanza_km, riquadro_intorno

log = logging.getLogger(__name__)

SOGLIA_SIMILARITA = 0.55
MAX_CANDIDATI_SIMILI = 3

_INTESTAZIONE = "[out:json][timeout:{timeout}];"
_MAX_ELEMENTI_OUT = 500

_PREFISSI = frozenset(
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


def query_luoghi_bbox(sud: float, ovest: float, nord: float, est: float) -> str:
    bbox = f"{sud},{ovest},{nord},{est}"
    return (
        _INTESTAZIONE.format(timeout=int(CONFIG.timeout_s) - 5)
        + "("
        + f'node["natural"~"^(peak|saddle)$"]({bbox});'
        + f'way["natural"~"^(peak|saddle)$"]({bbox});'
        + f'node["tourism"~"^(alpine_hut|wilderness_hut)$"]({bbox});'
        + f'way["tourism"~"^(alpine_hut|wilderness_hut)$"]({bbox});'
        + f'node["place"~"^(village|hamlet|town|locality|isolated_dwelling)$"]({bbox});'
        + f'way["place"~"^(village|hamlet|town|locality|isolated_dwelling)$"]({bbox});'
        + ");"
        + f"out tags center {_MAX_ELEMENTI_OUT};"
    )


def _tipo_da_tags(tags: dict[str, str]) -> str | None:
    if tags.get("natural") in {"peak", "saddle"}:
        return tags["natural"]
    if tags.get("tourism") in {"alpine_hut", "wilderness_hut"}:
        return tags["tourism"]
    if tags.get("place") in {"village", "hamlet", "town", "locality", "isolated_dwelling"}:
        return tags["place"]
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
    while len(parti) >= 2 and parti[0] in _PREFISSI:
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
    nome: str,
    *,
    lat: float,
    lon: float,
    raggio_km: float,
) -> list[Localita]:
    sud, ovest, nord, est = riquadro_intorno(lat, lon, raggio_km)
    try:
        dati = await overpass.esegui(query_luoghi_bbox(sud, ovest, nord, est))
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

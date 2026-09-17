"""Candidati toponomastici locali (Overpass) e similarita' di nome."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from trekking_mcp.tools.comuni import distanza_km

if TYPE_CHECKING:
    from trekking_mcp.models import Localita

SOGLIA_SIMILARITA = 0.55
MAX_CANDIDATI_SIMILI = 3

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

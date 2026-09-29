from __future__ import annotations

from trekking_mcp.constants import PREFISSI_TOPONIMO


def testo_da_toponimo(nome: str) -> str:
    """La parola da passare a Overpass come filtro testuale.

    Overpass cerca su `name|from|to|description` con una regex.
    """
    parti = nome.strip().split()
    if not parti:
        return nome.strip()
    while len(parti) >= 2 and parti[0].casefold() in PREFISSI_TOPONIMO:
        parti = parti[1:]
    return parti[-1]


def varianti_query_geocode(nome: str) -> list[str]:
    """Varianti di query Nominatim per toponimi composti, uniche e non vuote."""
    grezzo = " ".join(nome.strip().split())
    if not grezzo:
        return []
    parti = grezzo.split()
    out: list[str] = []
    min_taglia = 2 if len(parti) >= 2 else 1
    for taglia in range(len(parti), min_taglia - 1, -1):
        candidato = " ".join(parti[:taglia])
        if candidato not in out:
            out.append(candidato)
    fonte = out[-1] if len(parti) >= 2 else grezzo
    estratto = testo_da_toponimo(fonte)
    if estratto and estratto not in out:
        out.append(estratto)
    return out

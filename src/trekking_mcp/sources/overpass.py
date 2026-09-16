"""Adapter per Overpass API (OpenStreetMap).

I sentieri numerati italiani sono mappati come relation `route=hiking`, con il
numero nel tag `ref` e l'ente nel tag `operator` (es. "CAI Torino"). Il numero
NON sta nel tag `name`: e' una convenzione esplicita del wiki OSM italiano, ed
e' il motivo per cui qui si cerca su `ref` e non su `name`.

Dati (c) contributori OpenStreetMap, licenza ODbL. L'attribuzione e' obbligatoria
e viene propagata nei campi `fonti` degli output.
"""

from __future__ import annotations

from typing import cast

from trekking_mcp.config import CONFIG
from trekking_mcp.models import Coord, Ricovero, Sentiero
from trekking_mcp.payloads import OverpassElement, OverpassResponse
from trekking_mcp.sources.http import CLIENT

ATTRIBUZIONE = "Dati sentieri e ricoveri: (c) contributori OpenStreetMap, ODbL"
_INTESTAZIONE = "[out:json][timeout:{timeout}];"


def _bbox(sud: float, ovest: float, nord: float, est: float) -> str:
    return f"{sud},{ovest},{nord},{est}"


def query_sentieri(
    *,
    sud: float,
    ovest: float,
    nord: float,
    est: float,
    ref: str | None = None,
    operatore: str | None = None,
) -> str:
    """Costruisce la query QL per le relation escursionistiche in un riquadro."""
    filtri = ['["route"="hiking"]', '["type"="route"]']
    if ref:
        filtri.append(f'["ref"="{_escape(ref)}"]')
    if operatore:
        filtri.append(f'["operator"~"{_escape(operatore)}",i]')

    catena = "".join(filtri)
    return (
        _INTESTAZIONE.format(timeout=int(CONFIG.timeout_s) - 5)
        + f"relation{catena}({_bbox(sud, ovest, nord, est)});"
        + "out tags center;"
    )


def query_ricoveri(*, lat: float, lon: float, raggio_m: int) -> str:
    """Rifugi gestiti, bivacchi e ripari entro un raggio."""
    return (
        _INTESTAZIONE.format(timeout=int(CONFIG.timeout_s) - 5)
        + "("
        + f'node["tourism"~"^(alpine_hut|wilderness_hut)$"](around:{raggio_m},{lat},{lon});'
        + f'way["tourism"~"^(alpine_hut|wilderness_hut)$"](around:{raggio_m},{lat},{lon});'
        + f'node["amenity"="shelter"]["shelter_type"="basic_hut"](around:{raggio_m},{lat},{lon});'
        + ");"
        + "out tags center;"
    )


def query_relation(osm_relation_id: int) -> str:
    return (
        _INTESTAZIONE.format(timeout=int(CONFIG.timeout_s) - 5) + f"relation({osm_relation_id});" + "out tags center;"
    )


def query_geometria(osm_relation_id: int) -> str:
    """Relation con la geometria completa dei membri.

    `out geom` restituisce ogni vertice di ogni way: per un sentiero alpino
    sono facilmente migliaia di punti e centinaia di KB. Va usata solo quando
    serve davvero il profilo, mai nelle ricerche.
    """
    return _INTESTAZIONE.format(timeout=int(CONFIG.timeout_s) - 5) + f"relation({osm_relation_id});" + "out tags geom;"


def polilinea(elemento: OverpassElement) -> list[Coord]:
    """Concatena i membri way di una relation in una polilinea unica.

    Le way di una relation escursionistica **non sono garantite in ordine ne'
    orientate coerentemente**: e' normale trovare un tratto percorso al
    contrario. Qui si ricuce confrontando gli estremi e si inverte il tratto
    quando serve. Senza questo passaggio il profilo altimetrico risulta un
    dente di sega privo di senso.
    """
    tratti: list[list[Coord]] = []
    for membro in elemento.get("members") or []:
        if membro.get("type") != "way" or not membro.get("geometry"):
            continue
        punti = [Coord(lat=p["lat"], lon=p["lon"]) for p in membro["geometry"] if "lat" in p]
        if len(punti) >= 2:
            tratti.append(punti)

    if not tratti:
        return []

    percorso = tratti.pop(0)
    while tratti:
        coda = percorso[-1]
        indice, inverti, migliore = 0, False, float("inf")
        for i, tratto in enumerate(tratti):
            for candidato, va_invertito in ((tratto[0], False), (tratto[-1], True)):
                d = (candidato.lat - coda.lat) ** 2 + (candidato.lon - coda.lon) ** 2
                if d < migliore:
                    indice, inverti, migliore = i, va_invertito, d

        tratto = tratti.pop(indice)
        if inverti:
            tratto.reverse()
        percorso.extend(tratto[1:] if tratto[0] == coda else tratto)

    return percorso


def _escape(valore: str) -> str:
    """Neutralizza i caratteri che romperebbero la sintassi QL.

    Overpass non ha query parametrizzate, quindi l'escaping e' a carico nostro:
    e' l'equivalente locale della prevenzione da injection.
    """
    return valore.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


async def esegui(ql: str, *, ttl_s: int | None = None) -> OverpassResponse:
    return cast(
        OverpassResponse,
        await CLIENT.json(
            "POST",
            CONFIG.overpass_url,
            fonte="overpass",
            ttl_s=ttl_s if ttl_s is not None else CONFIG.ttl_overpass_s,
            data={"data": ql},
        ),
    )


async def cerca_sentieri(
    *,
    sud: float,
    ovest: float,
    nord: float,
    est: float,
    ref: str | None = None,
    operatore: str | None = None,
) -> list[Sentiero]:
    dati = await esegui(query_sentieri(sud=sud, ovest=ovest, nord=nord, est=est, ref=ref, operatore=operatore))
    return [Sentiero.da_relation(el) for el in dati.get("elements", []) if el.get("type") == "relation"]


async def cerca_ricoveri(*, lat: float, lon: float, raggio_m: int) -> list[Ricovero]:
    dati = await esegui(query_ricoveri(lat=lat, lon=lon, raggio_m=raggio_m))
    return [Ricovero.da_element(el) for el in dati.get("elements", []) if el.get("tags")]


async def leggi_sentiero(osm_relation_id: int) -> Sentiero | None:
    dati = await esegui(query_relation(osm_relation_id))
    elementi = [el for el in dati.get("elements", []) if el.get("type") == "relation"]
    return Sentiero.da_relation(elementi[0]) if elementi else None


async def leggi_geometria(osm_relation_id: int) -> tuple[Sentiero, list[Coord]] | None:
    """Sentiero piu' la sua polilinea completa.

    Non usa la cache condivisa con TTL breve: la risposta e' grande e la
    geometria dei sentieri e' la cosa piu' stabile che questo server tratti.
    """
    dati = await esegui(query_geometria(osm_relation_id))
    relazioni = [el for el in dati.get("elements", []) if el.get("type") == "relation"]
    if not relazioni:
        return None
    return Sentiero.da_relation(relazioni[0]), polilinea(relazioni[0])

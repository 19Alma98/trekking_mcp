"""Adapter per Overpass API (OpenStreetMap).

I sentieri numerati italiani sono mappati come relation `route=hiking`, con il
numero nel tag `ref` e l'ente nel tag `operator` (es. "CAI Torino"). Il numero
NON sta nel tag `name`: e' una convenzione esplicita del wiki OSM italiano, ed
e' il motivo per cui qui si cerca su `ref` e non su `name`.

Dati (c) contributori OpenStreetMap, licenza ODbL. L'attribuzione e' obbligatoria
e viene propagata nei campi `fonti` degli output.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from trekking_mcp.config import Config
from trekking_mcp.constants import OVERPASS_MARGINE_TIMEOUT_S, OVERPASS_TESTO_MAX_LEN
from trekking_mcp.models import SAC_TO_CAI, Coord, DifficoltaCAI, Ricovero, SacScale, Sentiero, TipoRicovero
from trekking_mcp.payloads import OverpassElement, OverpassResponse

if TYPE_CHECKING:
    from trekking_mcp.risorse import Risorse


def escape(valore: str) -> str:
    """Neutralizza i caratteri che romperebbero la sintassi QL.

    Overpass non ha query parametrizzate, quindi l'escaping e' a carico nostro:
    e' l'equivalente locale della prevenzione da injection.
    """
    return valore.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def intestazione(config: Config) -> str:
    """Il preambolo di ogni query QL: formato di uscita e timeout.

    Una funzione e non una costante perche' il timeout viene dal `Config`, e
    perche' era duplicata in `luoghi_simili` — due copie della stessa stringa che
    potevano divergere sul valore che conta.
    """
    return f"[out:json][timeout:{int(config.timeout_s) - OVERPASS_MARGINE_TIMEOUT_S}];"


def bbox(sud: float, ovest: float, nord: float, est: float) -> str:
    """Riquadro nell'ordine che vuole Overpass: sud,ovest,nord,est."""
    return f"{sud},{ovest},{nord},{est}"


def sentiero_da_relation(rel: OverpassElement) -> Sentiero:
    """Una relation `route=hiking` nel modello `Sentiero`."""
    tags: dict[str, str] = rel.get("tags", {})

    sac = None
    if raw := tags.get("sac_scale"):
        try:
            sac = SacScale(raw)
        except ValueError:
            # `sac_scale` fuori standard: si scarta il valore, non la relation.
            sac = None

    centro = None
    if c := rel.get("center"):
        centro = Coord(lat=c["lat"], lon=c["lon"])

    lunghezza = None
    if raw := tags.get("distance"):
        try:
            lunghezza = float(raw.replace("km", "").strip())
        except ValueError:
            lunghezza = None

    return Sentiero(
        osm_relation_id=rel["id"],
        ref=tags.get("ref"),
        nome=tags.get("name"),
        da=tags.get("from"),
        a=tags.get("to"),
        operatore=tags.get("operator"),
        rete=tags.get("network"),
        sac_scale=sac,
        difficolta_cai=SAC_TO_CAI.get(sac, DifficoltaCAI.SCONOSCIUTA) if sac else DifficoltaCAI.SCONOSCIUTA,
        visibilita=tags.get("trail_visibility"),
        lunghezza_km=lunghezza,
        centro=centro,
        osm_url=f"https://www.openstreetmap.org/relation/{rel['id']}",
    )


def ricovero_da_element(el: OverpassElement) -> Ricovero:
    """Un nodo o una way di rifugio, bivacco o riparo nel modello `Ricovero`."""
    tags: dict[str, str] = el.get("tags", {})

    if tags.get("tourism") == "alpine_hut":
        tipo = TipoRicovero.RIFUGIO
    elif tags.get("tourism") == "wilderness_hut":
        tipo = TipoRicovero.BIVACCO
    else:
        tipo = TipoRicovero.RIPARO

    if "lat" in el and "lon" in el:
        lat, lon = el["lat"], el["lon"]
    elif "center" in el:
        lat, lon = el["center"]["lat"], el["center"]["lon"]
    else:
        raise ValueError(f"elemento Overpass {el.get('id')} senza coordinate")

    def _int(chiave: str) -> int | None:
        try:
            return int(float(tags[chiave]))
        except (KeyError, ValueError):
            return None

    return Ricovero(
        osm_id=el["id"],
        nome=tags.get("name"),
        tipo=tipo,
        quota_m=_int("ele"),
        coord=Coord(lat=lat, lon=lon),
        posti_letto=_int("beds") or _int("capacity"),
        telefono=tags.get("phone") or tags.get("contact:phone"),
        sito_web=tags.get("website") or tags.get("contact:website"),
        osm_url=f"https://www.openstreetmap.org/{el.get('type', 'node')}/{el['id']}",
    )


def pattern_operatore(operatore: str) -> str:
    """Normalizza alias comuni prima della regex case-insensitive Overpass."""
    if operatore.strip().casefold() == "cai":
        return r"C\.?A\.?I\.?"
    return operatore


def _escape_regex(valore: str) -> str:
    """Escape PCRE/regex per valore utente, poi escape sintassi QL."""
    return escape(re.escape(valore[:OVERPASS_TESTO_MAX_LEN]))


def query_sentieri(
    config: Config,
    *,
    sud: float,
    ovest: float,
    nord: float,
    est: float,
    ref: str | None = None,
    operatore: str | None = None,
    testo: str | None = None,
) -> str:
    """Costruisce la query QL per le relation escursionistiche in un riquadro."""
    filtri = ['["route"="hiking"]', '["type"="route"]']
    if ref:
        filtri.append(f'["ref"="{escape(ref)}"]')
    if operatore:
        filtri.append(f'["operator"~"{escape(pattern_operatore(operatore))}",i]')
    if testo and testo.strip():
        filtri.append(f'[~"^(name|from|to|description)$"~"{_escape_regex(testo.strip())}",i]')

    catena = "".join(filtri)
    return intestazione(config) + f"relation{catena}({bbox(sud, ovest, nord, est)});" + "out tags center;"


def query_ricoveri(config: Config, *, lat: float, lon: float, raggio_m: int) -> str:
    """Rifugi gestiti, bivacchi e ripari entro un raggio."""
    return (
        intestazione(config)
        + "("
        + f'node["tourism"~"^(alpine_hut|wilderness_hut)$"](around:{raggio_m},{lat},{lon});'
        + f'way["tourism"~"^(alpine_hut|wilderness_hut)$"](around:{raggio_m},{lat},{lon});'
        + f'node["amenity"="shelter"]["shelter_type"="basic_hut"](around:{raggio_m},{lat},{lon});'
        + ");"
        + "out tags center;"
    )


def query_relation(config: Config, osm_relation_id: int) -> str:
    return intestazione(config) + f"relation({osm_relation_id});" + "out tags center;"


def ha_membri_way(elemento: OverpassElement) -> bool:
    return any(m.get("type") == "way" for m in (elemento.get("members") or []))


def query_geometria(config: Config, osm_relation_id: int) -> str:
    """Relation con la geometria completa dei membri.

    `out geom` restituisce ogni vertice di ogni way: per un sentiero alpino
    sono facilmente migliaia di punti e centinaia di KB. Va usata solo quando
    serve davvero il profilo, mai nelle ricerche.
    """
    return intestazione(config) + f"relation({osm_relation_id});" + "out tags geom;"


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


async def esegui(risorse: Risorse, ql: str, *, ttl_s: int | None = None) -> OverpassResponse:
    async with risorse.overpass:
        return cast(
            OverpassResponse,
            await risorse.http.json(
                "POST",
                risorse.config.overpass_url,
                fonte="overpass",
                ttl_s=ttl_s if ttl_s is not None else risorse.config.ttl_overpass_s,
                max_retry=2,
                data={"data": ql},
            ),
        )


async def cerca_sentieri(
    risorse: Risorse,
    *,
    sud: float,
    ovest: float,
    nord: float,
    est: float,
    ref: str | None = None,
    operatore: str | None = None,
    testo: str | None = None,
) -> list[Sentiero]:
    dati = await esegui(
        risorse,
        query_sentieri(
            risorse.config, sud=sud, ovest=ovest, nord=nord, est=est, ref=ref, operatore=operatore, testo=testo
        ),
    )
    return [sentiero_da_relation(el) for el in dati.get("elements", []) if el.get("type") == "relation"]


async def cerca_ricoveri(risorse: Risorse, *, lat: float, lon: float, raggio_m: int) -> list[Ricovero]:
    dati = await esegui(risorse, query_ricoveri(risorse.config, lat=lat, lon=lon, raggio_m=raggio_m))
    return [ricovero_da_element(el) for el in dati.get("elements", []) if el.get("tags")]


async def leggi_sentiero(risorse: Risorse, osm_relation_id: int) -> Sentiero | None:
    dati = await esegui(risorse, query_relation(risorse.config, osm_relation_id))
    elementi = [el for el in dati.get("elements", []) if el.get("type") == "relation"]
    return sentiero_da_relation(elementi[0]) if elementi else None


async def leggi_geometria(risorse: Risorse, osm_relation_id: int) -> tuple[Sentiero, list[Coord]] | None:
    """Sentiero piu' la sua polilinea completa, in una sola query."""
    dati = await esegui(risorse, query_geometria(risorse.config, osm_relation_id))
    relazioni = [el for el in dati.get("elements", []) if el.get("type") == "relation"]
    if not relazioni:
        return None

    relazione = relazioni[0]
    if not ha_membri_way(relazione):
        return sentiero_da_relation(relazione), []
    return sentiero_da_relation(relazione), polilinea(relazione)

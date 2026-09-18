"""Geometria: distanze, riquadri, point-in-polygon.

Niente shapely e niente GEOS: point-in-polygon e haversine sono cinquanta righe
di matematica scolastica, e una dipendenza binaria costa a chiunque provi a
installare il progetto (§3.11).

Questo modulo non importa nulla del resto del pacchetto tranne i tipi dei
payload. E' il fondo della pila: `tools` e `sources` dipendono da lui, lui da
nessuno. Prima `distanza_km` e `riquadro_intorno` stavano in `tools/comuni.py`,
e tre adapter in `sources/` importavano *verso l'alto* dal layer dei tool —
esattamente il contrario della dipendenza a senso unico dichiarata in §2.
"""

from __future__ import annotations

import math
from typing import cast

from trekking_mcp.constants import KM_PER_GRADO, RAGGIO_TERRA_KM
from trekking_mcp.payloads import GeoJsonGeometry, GeoJsonMultiPolygonCoords, GeoJsonPolygonCoords

# (ovest, sud, est, nord), come da convenzione GeoJSON `bbox`.
Riquadro = tuple[float, float, float, float]
Anello = list[tuple[float, float]]


def riquadro_intorno(lat: float, lon: float, raggio_km: float) -> tuple[float, float, float, float]:
    """Riquadro (sud, ovest, nord, est) attorno a un punto.

    Approssimazione piana: il grado di longitudine si accorcia con il coseno
    della latitudine. Sufficiente per una bbox di ricerca, non per misure.

    Nota l'ordine, diverso da `Riquadro`: e' quello che vuole Overpass
    (`bbox:sud,ovest,nord,est`), ed e' li' che questo risultato finisce.
    """
    delta_lat = raggio_km / KM_PER_GRADO
    delta_lon = raggio_km / (KM_PER_GRADO * max(math.cos(math.radians(lat)), 0.01))
    return (lat - delta_lat, lon - delta_lon, lat + delta_lat, lon + delta_lon)


def distanza_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza great-circle (haversine), in km."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 2 * RAGGIO_TERRA_KM * math.asin(math.sqrt(a))


def riquadro_di(anelli: list[Anello]) -> Riquadro:
    """Bounding box di uno o piu' anelli."""
    lon = [p[0] for anello in anelli for p in anello]
    lat = [p[1] for anello in anelli for p in anello]
    return (min(lon), min(lat), max(lon), max(lat))


def nel_riquadro(lat: float, lon: float, riquadro: Riquadro) -> bool:
    ovest, sud, est, nord = riquadro
    return ovest <= lon <= est and sud <= lat <= nord


def _nell_anello(lat: float, lon: float, anello: Anello) -> bool:
    """Ray casting: conta gli attraversamenti di una semiretta orizzontale.

    Un punto esattamente sul bordo puo' risultare dentro o fuori a seconda
    dell'orientamento: per le zone valanghe e' irrilevante, perche' le
    micro-regioni confinanti hanno comunque bollettini simili.
    """
    dentro = False
    n = len(anello)
    j = n - 1
    for i in range(n):
        xi, yi = anello[i]
        xj, yj = anello[j]
        # Il segmento attraversa la latitudine del punto?
        if (yi > lat) != (yj > lat):
            # Longitudine dell'intersezione fra segmento e semiretta.
            x_taglio = xi + (lat - yi) * (xj - xi) / (yj - yi)
            if lon < x_taglio:
                dentro = not dentro
        j = i
    return dentro


def _nel_poligono(lat: float, lon: float, poligono: list[Anello]) -> bool:
    """Un poligono GeoJSON: primo anello esterno, successivi buchi."""
    if not poligono or not _nell_anello(lat, lon, poligono[0]):
        return False
    return not any(_nell_anello(lat, lon, buco) for buco in poligono[1:])


def anelli_di_geometria(geometria: GeoJsonGeometry) -> list[list[Anello]]:
    """Normalizza Polygon e MultiPolygon in una lista di poligoni.

    Restituisce sempre la stessa forma, cosi' il chiamante non deve
    distinguere i due tipi.
    """
    tipo = geometria.get("type")
    coordinate = geometria.get("coordinates") or []

    if tipo == "Polygon":
        poligono = cast(GeoJsonPolygonCoords, coordinate)
        return [[[(float(p[0]), float(p[1])) for p in anello] for anello in poligono]]
    if tipo == "MultiPolygon":
        multipoligono = cast(GeoJsonMultiPolygonCoords, coordinate)
        return [[[(float(p[0]), float(p[1])) for p in anello] for anello in poligono] for poligono in multipoligono]
    return []


def contiene(lat: float, lon: float, poligoni: list[list[Anello]]) -> bool:
    return any(_nel_poligono(lat, lon, poligono) for poligono in poligoni)

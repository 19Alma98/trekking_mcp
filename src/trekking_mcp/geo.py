from __future__ import annotations

from typing import Any

# (ovest, sud, est, nord), come da convenzione GeoJSON `bbox`.
Riquadro = tuple[float, float, float, float]
Anello = list[tuple[float, float]]


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


def anelli_di_geometria(geometria: dict[str, Any]) -> list[list[Anello]]:
    """Normalizza Polygon e MultiPolygon in una lista di poligoni.

    Restituisce sempre la stessa forma, cosi' il chiamante non deve
    distinguere i due tipi.
    """
    tipo = geometria.get("type")
    coordinate = geometria.get("coordinates") or []

    if tipo == "Polygon":
        return [[[(float(p[0]), float(p[1])) for p in anello] for anello in coordinate]]
    if tipo == "MultiPolygon":
        return [[[(float(p[0]), float(p[1])) for p in anello] for anello in poligono] for poligono in coordinate]
    return []


def contiene(lat: float, lon: float, poligoni: list[list[Anello]]) -> bool:
    return any(_nel_poligono(lat, lon, poligono) for poligono in poligoni)

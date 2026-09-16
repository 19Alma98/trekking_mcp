from __future__ import annotations

from typing import TypedDict


class OverpassCenter(TypedDict):
    lat: float
    lon: float


class OverpassGeometryPoint(TypedDict):
    lat: float
    lon: float


class OverpassMember(TypedDict, total=False):
    type: str
    geometry: list[OverpassGeometryPoint]


class OverpassElement(TypedDict, total=False):
    type: str
    id: int
    tags: dict[str, str]
    center: OverpassCenter
    lat: float
    lon: float
    members: list[OverpassMember]


class OverpassResponse(TypedDict, total=False):
    elements: list[OverpassElement]


# Chiave API reale "ele:m": forma funzionale obbligatoria.
NominatimExtratags = TypedDict(
    "NominatimExtratags",
    {"ele": str, "ele:m": str},
    total=False,
)


class NominatimResult(TypedDict, total=False):
    lat: str
    lon: str
    type: str
    display_name: str
    osm_type: str
    osm_id: int
    extratags: NominatimExtratags


GeoJsonPosition = list[float]
GeoJsonRing = list[GeoJsonPosition]
GeoJsonPolygonCoords = list[GeoJsonRing]
GeoJsonMultiPolygonCoords = list[GeoJsonPolygonCoords]


class GeoJsonGeometry(TypedDict, total=False):
    type: str
    coordinates: GeoJsonPolygonCoords | GeoJsonMultiPolygonCoords


class EawsFeatureProperties(TypedDict, total=False):
    id: str
    regionID: str
    name: str
    name_it: str


class EawsFeature(TypedDict, total=False):
    properties: EawsFeatureProperties
    geometry: GeoJsonGeometry


class EawsFeatureCollection(TypedDict, total=False):
    type: str
    features: list[EawsFeature]


CaamlElevationBound = str | int | float


class CaamlElevation(TypedDict, total=False):
    lowerBound: CaamlElevationBound
    upperBound: CaamlElevationBound


class CaamlDangerRating(TypedDict, total=False):
    mainValue: str
    elevation: CaamlElevation


class CaamlAvalancheProblem(TypedDict, total=False):
    problemType: str
    type: str
    aspects: list[str]
    elevation: CaamlElevation


class CaamlRegion(TypedDict, total=False):
    regionID: str
    name: str


class CaamlValidTime(TypedDict, total=False):
    startTime: str
    endTime: str


class CaamlTextBlock(TypedDict, total=False):
    highlights: str
    comment: str
    avalancheActivityComment: str


class CaamlBulletin(TypedDict, total=False):
    bulletinID: str
    id: str
    regions: list[CaamlRegion]
    validTime: CaamlValidTime
    dangerRatings: list[CaamlDangerRating]
    avalancheProblems: list[CaamlAvalancheProblem]
    highlights: str | CaamlTextBlock
    avalancheActivity: str | CaamlTextBlock
    snowpackStructure: str | CaamlTextBlock


class CaamlFeature(TypedDict, total=False):
    properties: CaamlBulletin


class CaamlResponse(TypedDict, total=False):
    bulletins: list[CaamlBulletin]
    features: list[CaamlFeature]

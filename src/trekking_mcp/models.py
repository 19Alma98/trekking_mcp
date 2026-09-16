from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field

from trekking_mcp.payloads import OverpassElement


class SacScale(StrEnum):
    """Valori del tag OSM `sac_scale`."""

    T1 = "hiking"
    T2 = "mountain_hiking"
    T3 = "demanding_mountain_hiking"
    T4 = "alpine_hiking"
    T5 = "demanding_alpine_hiking"
    T6 = "difficult_alpine_hiking"


class DifficoltaCAI(StrEnum):
    """Scala escursionistica CAI."""

    T = "T"  # Turistico
    E = "E"  # Escursionistico
    EE = "EE"  # Escursionisti Esperti
    EEA = "EEA"  # Escursionisti Esperti con Attrezzatura
    SCONOSCIUTA = "sconosciuta"


# Corrispondenza indicativa SAC -> CAI
SAC_TO_CAI: dict[SacScale, DifficoltaCAI] = {
    SacScale.T1: DifficoltaCAI.T,
    SacScale.T2: DifficoltaCAI.E,
    SacScale.T3: DifficoltaCAI.EE,
    SacScale.T4: DifficoltaCAI.EE,
    SacScale.T5: DifficoltaCAI.EEA,
    SacScale.T6: DifficoltaCAI.EEA,
}


class Coord(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Sentiero(BaseModel):
    """Un percorso escursionistico, da una relation OSM `route=hiking`."""

    osm_relation_id: int
    ref: str | None = Field(default=None, description="Numero del sentiero, es. '103'")
    nome: str | None = None
    da: str | None = Field(default=None, description="Punto di partenza (tag `from`)")
    a: str | None = Field(default=None, description="Punto di arrivo (tag `to`)")
    operatore: str | None = Field(default=None, description="Es. 'CAI Torino'")
    rete: str | None = Field(default=None, description="Tag `network`: lwn/rwn/nwn/iwn")
    sac_scale: SacScale | None = None
    difficolta_cai: DifficoltaCAI = DifficoltaCAI.SCONOSCIUTA
    visibilita: str | None = Field(default=None, description="Tag `trail_visibility`")
    lunghezza_km: float | None = None
    centro: Coord | None = Field(default=None, description="Centroide approssimato")
    profilo: ProfiloAltimetrico | None = Field(
        default=None, description="Popolato solo su richiesta esplicita: richiede una query piu' pesante"
    )
    osm_url: str

    @classmethod
    def da_relation(cls, rel: OverpassElement) -> Sentiero:
        tags: dict[str, str] = rel.get("tags", {})
        sac = None
        if raw := tags.get("sac_scale"):
            try:
                sac = SacScale(raw)
            except ValueError:
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

        return cls(
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


class PuntoQuotato(BaseModel):
    coord: Coord
    quota_m: float


class ProfiloAltimetrico(BaseModel):
    """Profilo di un percorso: quote campionate e dislivelli cumulati."""

    punti: list[PuntoQuotato] = Field(default_factory=list)
    lunghezza_km: float
    dislivello_positivo_m: int
    dislivello_negativo_m: int
    quota_minima_m: int | None = None
    quota_massima_m: int | None = None


class ZonaValanghe(BaseModel):
    """Micro-regione EAWS identificata a partire da un punto."""

    id_zona: str
    nome: str | None = None
    coord_richiesta: Coord
    fonte: str = "EAWS Regions"


class Localita(BaseModel):
    """Risultato di una ricerca per toponimo."""

    nome: str
    tipo: str | None = Field(default=None, description="Es. peak, village, alpine_hut")
    coord: Coord
    quota_m: int | None = None
    osm_url: str | None = None


class TipoRicovero(StrEnum):
    RIFUGIO = "rifugio_gestito"  # tourism=alpine_hut
    BIVACCO = "bivacco"  # tourism=wilderness_hut
    RIPARO = "riparo"  # amenity=shelter


class Ricovero(BaseModel):
    """Rifugio, bivacco o riparo."""

    osm_id: int
    nome: str | None = None
    tipo: TipoRicovero
    quota_m: int | None = None
    coord: Coord
    posti_letto: int | None = None
    telefono: str | None = None
    sito_web: str | None = None
    osm_url: str

    @classmethod
    def da_element(cls, el: OverpassElement) -> Ricovero:
        tags: dict[str, str] = el.get("tags", {})
        if tags.get("tourism") == "alpine_hut":
            tipo = TipoRicovero.RIFUGIO
        elif tags.get("tourism") == "wilderness_hut":
            tipo = TipoRicovero.BIVACCO
        else:
            tipo = TipoRicovero.RIPARO

        lat = el.get("lat") or el["center"]["lat"]
        lon = el.get("lon") or el["center"]["lon"]

        def _int(chiave: str) -> int | None:
            try:
                return int(float(tags[chiave]))
            except (KeyError, ValueError):
                return None

        return cls(
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


class GradoPericolo(IntEnum):
    """Scala europea unificata del pericolo valanghe (EAWS), 5 gradi."""

    DEBOLE = 1
    MODERATO = 2
    MARCATO = 3
    FORTE = 4
    MOLTO_FORTE = 5

    @property
    def etichetta(self) -> str:
        return {1: "Debole", 2: "Moderato", 3: "Marcato", 4: "Forte", 5: "Molto forte"}[self.value]


class ValutazionePericolo(BaseModel):
    grado: GradoPericolo
    etichetta: str
    quota_limite_m: int | None = Field(
        default=None, description="Quota di separazione, se il grado varia con l'altitudine"
    )
    sopra_quota: bool | None = Field(default=None, description="True se questo grado vale sopra `quota_limite_m`")


class ProblemaValanghivo(BaseModel):
    """Uno dei problemi tipici EAWS (neve ventata, strati deboli persistenti, ...)."""

    tipo: str
    esposizioni: list[str] = Field(default_factory=list, description="Settori: N, NE, E, ...")
    quota_min_m: int | None = None
    quota_max_m: int | None = None


class Bollettino(BaseModel):
    """Bollettino valanghe normalizzato da CAAML v6 (profilo EAWS)."""

    id_bollettino: str
    zona_id: str
    zona_nome: str | None = None
    valido_da: datetime
    valido_fino: datetime
    valutazioni: list[ValutazionePericolo]
    problemi: list[ProblemaValanghivo] = Field(default_factory=list)
    sintesi: str | None = Field(
        default=None, description="Testo libero del previsore (`highlights`/`avalancheActivity`)"
    )
    innevamento: str | None = None
    fonte: str = Field(description="Provider: aineva | slf | albina")
    fonte_url: str
    avvertenza: str = Field(
        default=(
            "Il bollettino valanghe e' un documento ufficiale di sicurezza. Questo strumento "
            "ne espone i dati ma NON sostituisce la lettura del bollettino originale, la "
            "valutazione sul posto ne' una formazione adeguata."
        )
    )

    @property
    def grado_massimo(self) -> GradoPericolo:
        return max((v.grado for v in self.valutazioni), default=GradoPericolo.DEBOLE)


class MeteoQuota(BaseModel):
    """Previsione puntuale corretta per l'elevazione."""

    coord: Coord
    quota_m: int
    istante: datetime
    temperatura_c: float | None = None
    vento_kmh: float | None = None
    raffica_kmh: float | None = None
    direzione_vento_gradi: int | None = None
    precipitazioni_mm: float | None = None
    neve_cm: float | None = None
    copertura_nuvolosa_pct: int | None = None
    zero_termico_m: int | None = None


class SegnaleAttenzione(BaseModel):
    categoria: str = Field(description="valanghe | meteo | difficolta | logistica")
    messaggio: str
    severita: str = Field(description="info | attenzione | critico")


class ValutazioneGita(BaseModel):
    """Output composito: mette insieme sentiero, ricoveri, bollettino e meteo.

    Deliberatamente NON emette un verdetto vai/non-vai. Restituisce i fatti
    normalizzati e i segnali di attenzione; la decisione resta all'utente.
    """

    sentiero: Sentiero
    data: str
    zona_valanghe: ZonaValanghe | None = None
    ricoveri_vicini: list[Ricovero] = Field(default_factory=list)
    bollettino: Bollettino | None = None
    meteo: list[MeteoQuota] = Field(default_factory=list)
    segnali: list[SegnaleAttenzione] = Field(default_factory=list)
    fonti: list[str] = Field(default_factory=list)
    avvertenza: str = Field(
        default=(
            "Sintesi automatica da dati aperti, priva di validazione umana. Non e' una "
            "consulenza e non sostituisce il bollettino ufficiale ne' il giudizio di chi "
            "conosce il terreno."
        )
    )

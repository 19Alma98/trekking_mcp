from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from trekking_mcp.errors import NonTrovato
from trekking_mcp.models import DifficoltaCAI, Ricovero, Sentiero, SentieriVersoLocalita
from trekking_mcp.sources import nominatim, overpass
from trekking_mcp.tools.comuni import distanza_km, gestisci_errori, riquadro_intorno

_PREFISSI_TOPONIMO = frozenset(
    {"monte", "mont", "monti", "cima", "pizzo", "col", "colle", "passo", "rifugio", "bivacco"}
)


def testo_da_toponimo(nome: str) -> str:
    parti = nome.strip().split()
    if not parti:
        return nome.strip()
    if len(parti) >= 2 and parti[0].casefold() in _PREFISSI_TOPONIMO:
        return parti[-1]
    return parti[-1]


async def esegui_sentieri_verso_localita(
    *,
    nome: str,
    vicino_a_lat: float | None = None,
    vicino_a_lon: float | None = None,
    raggio_km: float = 5,
    limite: int = 15,
    includi_ricoveri: bool = True,
) -> SentieriVersoLocalita:
    candidati = await nominatim.cerca(
        nome, limite=1, lat=vicino_a_lat, lon=vicino_a_lon
    )
    if not candidati:
        raise NonTrovato("localita'", nome)
    localita = candidati[0]
    testo = testo_da_toponimo(nome)
    sud, ovest, nord, est = riquadro_intorno(localita.coord.lat, localita.coord.lon, raggio_km)
    grezzi = await overpass.cerca_sentieri(
        sud=sud, ovest=ovest, nord=nord, est=est, testo=testo
    )
    sentieri = ordina_sentieri_per_distanza(
        grezzi, lat=localita.coord.lat, lon=localita.coord.lon, limite=limite
    )
    ricoveri: list[Ricovero] = []
    if includi_ricoveri:
        ricoveri = await overpass.cerca_ricoveri(
            lat=localita.coord.lat,
            lon=localita.coord.lon,
            raggio_m=int(raggio_km * 1000),
        )
    return SentieriVersoLocalita(localita=localita, sentieri=sentieri, ricoveri=ricoveri)


def ordina_sentieri_per_distanza(
    risultati: list[Sentiero], *, lat: float, lon: float, limite: int
) -> list[Sentiero]:
    """Assegna distanza_km e tiene i sentieri piu' vicini al punto query."""
    arricchiti: list[Sentiero] = []
    for s in risultati:
        if s.centro is None:
            arricchiti.append(s.model_copy(update={"distanza_km": None}))
            continue
        d = round(distanza_km(lat, lon, s.centro.lat, s.centro.lon), 1)
        arricchiti.append(s.model_copy(update={"distanza_km": d}))

    def chiave(s: Sentiero) -> tuple:
        senza_centro = s.distanza_km is None
        return (senza_centro, s.distanza_km if s.distanza_km is not None else 0.0, s.ref is None, s.ref or "")

    arricchiti.sort(key=chiave)
    return arricchiti[:limite]


def registra(mcp: MCPServer) -> None:
    @mcp.tool(
        name="cerca_sentieri",
        title="Cerca sentieri escursionistici",
        description=(
            "Cerca sentieri escursionistici numerati in una zona, per riquadro geografico "
            "o attorno a un punto. Default raggio 5 km (alzabile fino a 50). "
            "Usa `testo` per filtrare name/from/to/description (es. 'Mucrone'). "
            "Il numero del sentiero va in `ref` (es. '103'). "
            "Fonte: relation OSM route=hiking."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def cerca_sentieri(
        ctx: Context,
        lat: Annotated[float, Field(description="Latitudine del centro ricerca", ge=-90, le=90)],
        lon: Annotated[float, Field(description="Longitudine del centro ricerca", ge=-180, le=180)],
        raggio_km: Annotated[
            float, Field(description="Raggio di ricerca in km (default 5, max 50)", gt=0, le=50)
        ] = 5,
        ref: Annotated[str | None, Field(description="Numero esatto del sentiero, es. '103'")] = None,
        operatore: Annotated[
            str | None, Field(description="Filtro sull'ente, es. 'CAI' (matcha anche C.A.I.)")
        ] = None,
        testo: Annotated[
            str | None,
            Field(description="Filtro testuale su name/from/to/description, es. 'Mucrone'"),
        ] = None,
        difficolta_max: Annotated[
            DifficoltaCAI | None, Field(description="Scarta i sentieri piu' difficili di questo grado")
        ] = None,
        limite: Annotated[int, Field(description="Numero massimo di risultati", ge=1, le=100)] = 25,
    ) -> list[Sentiero]:
        sud, ovest, nord, est = riquadro_intorno(lat, lon, raggio_km)
        await ctx.log("info", f"Overpass: riquadro {raggio_km}km attorno a {lat:.4f},{lon:.4f}")

        risultati = await overpass.cerca_sentieri(
            sud=sud, ovest=ovest, nord=nord, est=est, ref=ref, operatore=operatore, testo=testo
        )

        if difficolta_max is not None:
            ordine = [DifficoltaCAI.T, DifficoltaCAI.E, DifficoltaCAI.EE, DifficoltaCAI.EEA]
            if difficolta_max in ordine:
                soglia = ordine.index(difficolta_max)
                risultati = [
                    s
                    for s in risultati
                    if s.difficolta_cai == DifficoltaCAI.SCONOSCIUTA
                    or (s.difficolta_cai in ordine and ordine.index(s.difficolta_cai) <= soglia)
                ]

        return ordina_sentieri_per_distanza(risultati, lat=lat, lon=lon, limite=limite)

    @mcp.tool(
        name="dettaglio_sentiero",
        title="Dettaglio di un sentiero",
        description=(
            "Restituisce i dati di un sentiero dato l'ID della relation OSM. "
            "Necessario solo se non hai gia' i campi da cerca_sentieri: non richiama "
            "dati diversi dalla search sui tag."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def dettaglio_sentiero(
        osm_relation_id: Annotated[int, Field(description="ID della relation OSM", gt=0)],
    ) -> Sentiero | None:
        return await overpass.leggi_sentiero(osm_relation_id)

    @mcp.tool(
        name="cerca_ricoveri",
        title="Cerca rifugi e bivacchi",
        description=(
            "Cerca rifugi gestiti, bivacchi e ripari entro un raggio da un punto. "
            "I dati su posti letto e contatti dipendono dalla mappatura OSM e possono mancare."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def cerca_ricoveri(
        lat: Annotated[float, Field(ge=-90, le=90)],
        lon: Annotated[float, Field(ge=-180, le=180)],
        raggio_km: Annotated[float, Field(description="Raggio in km", gt=0, le=30)] = 5,
    ) -> list[Ricovero]:
        return await overpass.cerca_ricoveri(lat=lat, lon=lon, raggio_m=int(raggio_km * 1000))

    @mcp.tool(
        name="sentieri_verso_localita",
        title="Sentieri verso un luogo per nome",
        description=(
            "Punto di ingresso quando l'utente chiede come arrivare a un luogo per nome: "
            "geocoding + ricerca sentieri (e rifugi) in una sola chiamata. "
            "Preferisci questo a una catena di cerca_localita + cerca_sentieri."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def sentieri_verso_localita(
        nome: Annotated[str, Field(description="Toponimo, es. 'Mucrone' o 'Monte Mucrone'", min_length=2)],
        vicino_a_lat: Annotated[
            float | None, Field(description="Lat di contesto (es. partenza)", ge=-90, le=90)
        ] = None,
        vicino_a_lon: Annotated[
            float | None, Field(description="Lon di contesto (es. partenza)", ge=-180, le=180)
        ] = None,
        raggio_km: Annotated[float, Field(description="Raggio ricerca sentieri/ricoveri", gt=0, le=50)] = 5,
        limite: Annotated[int, Field(ge=1, le=100)] = 15,
        includi_ricoveri: Annotated[bool, Field(description="Includi rifugi/bivacchi vicini")] = True,
    ) -> SentieriVersoLocalita:
        return await esegui_sentieri_verso_localita(
            nome=nome,
            vicino_a_lat=vicino_a_lat,
            vicino_a_lon=vicino_a_lon,
            raggio_km=raggio_km,
            limite=limite,
            includi_ricoveri=includi_ricoveri,
        )

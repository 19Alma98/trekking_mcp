from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from trekking_mcp.models import DifficoltaCAI, Ricovero, Sentiero
from trekking_mcp.sources import overpass
from trekking_mcp.tools.comuni import gestisci_errori, riquadro_intorno


def registra(mcp: MCPServer) -> None:
    @mcp.tool(
        name="cerca_sentieri",
        title="Cerca sentieri escursionistici",
        description=(
            "Cerca sentieri escursionistici numerati in una zona, per riquadro geografico "
            "o attorno a un punto. Il numero del sentiero va nel parametro `ref` (es. '103'). "
            "Fonte: relation OSM route=hiking."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def cerca_sentieri(
        ctx: Context,
        lat: Annotated[float, Field(description="Latitudine del centro ricerca", ge=-90, le=90)],
        lon: Annotated[float, Field(description="Longitudine del centro ricerca", ge=-180, le=180)],
        raggio_km: Annotated[float, Field(description="Raggio di ricerca in km", gt=0, le=50)] = 10,
        ref: Annotated[str | None, Field(description="Numero esatto del sentiero, es. '103'")] = None,
        operatore: Annotated[str | None, Field(description="Filtro sull'ente, es. 'CAI'")] = None,
        difficolta_max: Annotated[
            DifficoltaCAI | None, Field(description="Scarta i sentieri piu' difficili di questo grado")
        ] = None,
        limite: Annotated[int, Field(description="Numero massimo di risultati", ge=1, le=100)] = 25,
    ) -> list[Sentiero]:
        sud, ovest, nord, est = riquadro_intorno(lat, lon, raggio_km)
        await ctx.log("info", f"Overpass: riquadro {raggio_km}km attorno a {lat:.4f},{lon:.4f}")

        risultati = await overpass.cerca_sentieri(
            sud=sud, ovest=ovest, nord=nord, est=est, ref=ref, operatore=operatore
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

        risultati.sort(key=lambda s: (s.ref is None, s.ref or "", s.nome or ""))
        return risultati[:limite]

    @mcp.tool(
        name="dettaglio_sentiero",
        title="Dettaglio di un sentiero",
        description="Restituisce i dati completi di un sentiero dato l'ID della sua relation OSM.",
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

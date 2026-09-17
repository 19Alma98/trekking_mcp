from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from trekking_mcp.errors import NonTrovato
from trekking_mcp.models import Coord, Localita, ProfiloAltimetrico, ZonaValanghe
from trekking_mcp.sources import eaws, elevation, nominatim, overpass
from trekking_mcp.tools.comuni import gestisci_errori


def registra(mcp: MCPServer) -> None:
    @mcp.tool(
        name="zona_valanghe_da_coordinate",
        title="Trova la zona del bollettino valanghe",
        description=(
            "Dato un punto, individua la micro-regione EAWS a cui appartiene, cioe' la zona "
            "per cui viene emesso il bollettino valanghe. Usa questo tool prima di "
            "`bollettino_valanghe` invece di indovinare l'identificativo della zona."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def zona_valanghe_da_coordinate(
        ctx: Context,
        lat: Annotated[float, Field(ge=-90, le=90)],
        lon: Annotated[float, Field(ge=-180, le=180)],
    ) -> ZonaValanghe:
        await ctx.log("info", "cerco la micro-regione EAWS del punto")
        regione = await eaws.zona_da_coordinate(lat, lon)
        return ZonaValanghe(
            id_zona=regione.id_zona,
            nome=regione.nome,
            coord_richiesta=Coord(lat=lat, lon=lon),
        )

    @mcp.tool(
        name="cerca_localita",
        title="Cerca un luogo per nome",
        description=(
            "Converte un toponimo in coordinate: nomi di rifugi, cime, valichi, paesi e "
            "frazioni. Punto di partenza naturale quando l'utente nomina un posto invece "
            "di fornire coordinate. Con lat/lon opzionali filtra per raggio (default 30 km) "
            "e, se serve, chiede disambiguazione tra nomi simili; senza contesto usa "
            "Nominatim come prima."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def cerca_localita(
        ctx: Context,
        nome: Annotated[str, Field(description="Nome del luogo, es. 'Rifugio Gastaldi'", min_length=2)],
        limite: Annotated[int, Field(ge=1, le=10)] = 5,
        lat: Annotated[
            float | None,
            Field(description="Latitudine di contesto per disambiguare (viewbox)", ge=-90, le=90),
        ] = None,
        lon: Annotated[
            float | None,
            Field(description="Longitudine di contesto per disambiguare (viewbox)", ge=-180, le=180),
        ] = None,
        raggio_km: Annotated[
            float,
            Field(
                description="Raggio max (km) se lat/lon sono impostati; default 30. Ignorato senza contesto.",
                gt=0,
                le=200,
            ),
        ] = 30,
    ) -> list[Localita]:
        if lat is not None and lon is not None:
            from trekking_mcp.tools.geocode_risolvi import risolvi_localita

            return await risolvi_localita(ctx, nome, lat=lat, lon=lon, raggio_km=raggio_km, limite=limite)
        risultati = await nominatim.cerca(nome, limite=limite, lat=lat, lon=lon)
        if not risultati:
            raise NonTrovato("localita'", nome)
        return risultati

    @mcp.tool(
        name="profilo_altimetrico",
        title="Profilo altimetrico di un sentiero",
        description=(
            "Calcola lunghezza reale e dislivello positivo e negativo di un sentiero, "
            "campionando la quota lungo il tracciato. Usalo solo dopo una ricerca o un "
            "dettaglio sentiero quando serve il dislivello; non in esplorazione. "
            "Piu' lento perche' scarica la geometria completa."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def profilo_altimetrico(
        ctx: Context,
        osm_relation_id: Annotated[int, Field(description="Relation OSM del sentiero", gt=0)],
        passo_m: Annotated[float, Field(description="Distanza fra i punti campionati, in metri", ge=25, le=500)] = 100,
    ) -> ProfiloAltimetrico:
        await ctx.report_progress(0, 2, "Scarico la geometria del sentiero")
        esito = await overpass.leggi_geometria(osm_relation_id)
        if esito is None:
            raise NonTrovato("sentiero", str(osm_relation_id))

        _, punti = esito
        if len(punti) < 2:
            raise NonTrovato(
                "geometria del sentiero",
                str(osm_relation_id),
                alternative=["la relation esiste ma non ha way con geometria utilizzabile"],
            )

        await ctx.report_progress(1, 2, f"Campiono le quote su {len(punti)} punti")
        profilo = await elevation.profilo(punti, passo_m=passo_m)
        await ctx.report_progress(2, 2, "Fatto")
        return profilo

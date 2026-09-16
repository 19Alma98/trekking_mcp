from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from trekking_mcp.models import Bollettino, MeteoQuota
from trekking_mcp.sources import caaml, meteo
from trekking_mcp.tools.comuni import gestisci_errori


def registra(mcp: MCPServer) -> None:
    @mcp.tool(
        name="bollettino_valanghe",
        title="Bollettino valanghe",
        description=(
            "Restituisce il bollettino valanghe corrente per una zona (formato CAAML v6, "
            "profilo EAWS). Le zone AINEVA hanno identificativi tipo 'IT-21-...'. "
            "IMPORTANTE: i dati vanno sempre presentati con il rimando al bollettino "
            "ufficiale; non sono una valutazione del rischio."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def bollettino_valanghe(
        zona_id: Annotated[str, Field(description="Identificativo della zona, es. 'IT-21-AO-01'")],
        provider: Annotated[Literal["aineva", "slf"], Field(description="aineva = Italia, slf = Svizzera")] = "aineva",
        lingua: Annotated[Literal["it", "en", "de", "fr"], Field(description="Lingua dei testi")] = "it",
    ) -> Bollettino:
        return await caaml.leggi_bollettino(zona_id=zona_id, provider=provider, lingua=lingua)

    @mcp.tool(
        name="meteo_quota",
        title="Meteo di quota",
        description=(
            "Previsione oraria per un punto, corretta per l'elevazione indicata. "
            "Include zero termico, raffiche e neve fresca."
        ),
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )
    @gestisci_errori
    async def meteo_quota(
        lat: Annotated[float, Field(ge=-90, le=90)],
        lon: Annotated[float, Field(ge=-180, le=180)],
        quota_m: Annotated[int, Field(description="Quota in metri", ge=0, le=5000)],
        data: Annotated[str | None, Field(description="Data ISO YYYY-MM-DD; default: oggi")] = None,
        ore_max: Annotated[int, Field(ge=1, le=48)] = 12,
    ) -> list[MeteoQuota]:
        return await meteo.previsione(lat=lat, lon=lon, quota_m=quota_m, data=data, ore_max=ore_max)

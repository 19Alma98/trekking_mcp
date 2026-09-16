from __future__ import annotations

from importlib import resources as pkg_resources

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError

from trekking_mcp.sources import caaml


def _leggi_dato(nome: str) -> str:
    try:
        return (pkg_resources.files("trekking_mcp.data") / nome).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as exc:
        raise ResourceError(f"Documento di riferimento '{nome}' non incluso nel pacchetto") from exc


def registra(mcp: MCPServer) -> None:
    @mcp.resource(
        "scala://pericolo-valanghe",
        name="Scala europea del pericolo valanghe",
        description="I 5 gradi EAWS, con probabilita' di distacco e raccomandazioni.",
        mime_type="text/markdown",
    )
    def scala_valanghe() -> str:
        return _leggi_dato("scala_pericolo.md")

    @mcp.resource(
        "scala://difficolta-escursionistica",
        name="Scala di difficolta' CAI e corrispondenza SAC",
        description="T/E/EE/EEA e la mappatura indicativa verso il tag OSM sac_scale.",
        mime_type="text/markdown",
    )
    def scala_difficolta() -> str:
        return _leggi_dato("scala_difficolta.md")

    @mcp.resource(
        "bollettino://{provider}/{zona_id}",
        name="Bollettino valanghe corrente",
        description="Bollettino della zona indicata, come JSON normalizzato. Es. bollettino://aineva/IT-21-AO-01",
        mime_type="application/json",
    )
    async def bollettino_corrente(provider: str, zona_id: str) -> str:
        """Resource template: il bollettino esposto come documento indirizzabile.

        Stessi dati del tool omonimo, ma con un URI stabile che il client puo'
        allegare al contesto e ri-leggere senza una chiamata a tool.
        """
        try:
            b = await caaml.leggi_bollettino(zona_id=zona_id, provider=provider)
        except Exception as exc:
            raise ResourceError(str(exc)) from exc
        return b.model_dump_json(indent=2)

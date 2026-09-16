from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from trekking_mcp import prompts, resources
from trekking_mcp.sources.http import CLIENT
from trekking_mcp.tools import condizioni, gita, luoghi, sentieri

log = logging.getLogger(__name__)

ISTRUZIONI = """Server per l'escursionismo sulle Alpi e sugli Appennini italiani.

Fonti: sentieri e ricoveri da OpenStreetMap (relation route=hiking, numerazione
CAI mappata dalla community), bollettini valanghe in CAAML v6 da AINEVA e SLF,
meteo e modello di elevazione da Open-Meteo, perimetri delle zone valanghe
dal progetto EAWS Regions, geocoding da Nominatim.

Regole d'uso:
- I dati valanghivi provengono da documenti ufficiali di sicurezza. Riportali,
  non interpretarli, e rimanda sempre alla fonte.
- Non emettere verdetti sulla fattibilita' di un'uscita. Fornisci i fatti.
- Per una zona valanghe usa `zona_valanghe_da_coordinate` invece di indovinare
  l'identificativo; per un toponimo usa `cerca_localita`.
- Flusso tipico da localita' A a cima/luogo B: preferisci `sentieri_verso_localita`
  (con coordinate di A in vicino_a_*), poi eventualmente `valuta_gita` o
  `profilo_altimetrico` sul ref scelto. Evita catene lunghe di cerca + dettaglio
  + profili in esplorazione.
- La copertura OSM non e' uniforme: l'assenza di un sentiero non significa che
  non esista, e una difficolta' mancante non significa che sia facile.
"""


@asynccontextmanager
async def lifespan(_: MCPServer) -> AsyncIterator[None]:
    """Un solo pool HTTP per tutta la vita del processo."""
    await CLIENT.avvia()
    log.info("trekking-mcp avviato")
    try:
        yield
    finally:
        await CLIENT.chiudi()
        log.info("trekking-mcp chiuso")


def crea_server() -> MCPServer:
    mcp = MCPServer(
        name="trekking-mcp",
        title="Sentieri e condizioni di montagna",
        version="0.1.0",
        instructions=ISTRUZIONI,
        lifespan=lifespan,
    )

    sentieri.registra(mcp)
    luoghi.registra(mcp)
    condizioni.registra(mcp)
    gita.registra(mcp)
    resources.registra(mcp)
    prompts.registra(mcp)

    return mcp

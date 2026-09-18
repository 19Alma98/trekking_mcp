from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer
from mcp_types import Icon

from trekking_mcp import __version__, completamenti, prompts, resources
from trekking_mcp.cache import CACHE_HINTS, FreschezzaPerResource
from trekking_mcp.config import Config
from trekking_mcp.risorse import Risorse
from trekking_mcp.tools import condizioni, gita, luoghi, sentieri

log = logging.getLogger(__name__)

SITO = "https://github.com/19Alma98/trekking_mcp"

# L'icona e' un SVG inline come data URI: niente file binari nel repo, niente
# hosting da tenere in piedi, e funziona anche a un client offline. `theme`
# resta assente di proposito — `currentColor` si adatta da solo a chiaro e
# scuro, quindi non servono due varianti.
ICONA = Icon(
    src=(
        "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22currentColor%22%20stroke-width%3D%222%22%20stroke-linecap%3D%22round%22%20stroke-linejoin%3D%22round%22%3E%3Cpath%20d%3D%22M3%2020h18L14%206l-3.5%207L8%2010z%22%2F%3E%3Cpath%20d%3D%22m12.2%2010.6%201.8-1.2%201.6%201%22%2F%3E%3C%2Fsvg%3E"
    ),
    mime_type="image/svg+xml",
    sizes=["any"],
)

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


def crea_server(config: Config | None = None, *, risorse: Risorse | None = None) -> MCPServer[Risorse]:
    """Costruisce il server con le sue dipendenze.

    Le `Risorse` si creano qui e si passano a ogni `registra()`: e' l'unico
    punto in cui il grafo delle dipendenze e' visibile.
    """
    if risorse is None:
        risorse = Risorse.crea(config)

    @asynccontextmanager
    async def lifespan(_: MCPServer[Risorse]) -> AsyncIterator[Risorse]:
        """Apre e chiude il pool HTTP; un solo pool per server."""
        await risorse.avvia()
        log.info("trekking-mcp avviato")
        try:
            yield risorse
        finally:
            await risorse.chiudi()
            log.info("fonti esterne: %s", risorse.metriche.riga_di_log())
            log.info("trekking-mcp chiuso")

    mcp: MCPServer[Risorse] = MCPServer(
        name="trekking-mcp",
        title="Sentieri e condizioni di montagna",
        version=__version__,
        instructions=ISTRUZIONI,
        website_url=SITO,
        icons=[ICONA],
        lifespan=lifespan,
        # Gli elenchi sono statici per tutta la vita del processo; le resource
        # hanno freschezze diverse fra loro e le distingue il middleware.
        # Vedi cache.py.
        cache_hints=CACHE_HINTS,
        middleware=[FreschezzaPerResource(risorse.config)],
    )

    sentieri.registra(mcp, risorse)
    luoghi.registra(mcp, risorse)
    condizioni.registra(mcp, risorse)
    gita.registra(mcp, risorse)
    resources.registra(mcp, risorse)
    prompts.registra(mcp)
    completamenti.registra(mcp, risorse)

    return mcp

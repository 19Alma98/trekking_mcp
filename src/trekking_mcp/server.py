from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from trekking_mcp import __version__, completamenti, prompts, resources
from trekking_mcp.config import Config
from trekking_mcp.risorse import Risorse
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


def crea_server(config: Config | None = None, *, risorse: Risorse | None = None) -> MCPServer[Risorse]:
    """Costruisce il server con le sue dipendenze.

    Le `Risorse` si creano qui e si passano a ogni `registra()`: e' l'unico
    punto in cui il grafo delle dipendenze e' visibile.

    `risorse` le accetta gia' pronte ed e' la giuntura per i test: si prepara
    un indice EAWS finto, o un contatore di metriche con dentro qualcosa, e si
    consegna al server. Prima la stessa cosa si otteneva riscrivendo
    `eaws.INDICE` con `monkeypatch`, cioe' modificando un modulo per il resto
    della sessione di test. Se e' passato, `config` viene ignorato.
    """
    if risorse is None:
        risorse = Risorse.crea(config)

    @asynccontextmanager
    async def lifespan(_: MCPServer[Risorse]) -> AsyncIterator[Risorse]:
        """Apre e chiude il pool HTTP; un solo pool per server.

        Le risorse sono gia' costruite: qui si gestisce solo il loro ciclo di
        vita. Vengono anche restituite, cosi' sono raggiungibili come
        `ctx.request_context.lifespan_context` — la porta idiomatica dell'SDK
        per i tool e le resource template. Le resource statiche e l'handler dei
        completamenti non ricevono un Context, quindi usano la closure: stesso
        oggetto, due porte. Vedi `risorse.py`.
        """
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
        lifespan=lifespan,
    )

    sentieri.registra(mcp, risorse)
    luoghi.registra(mcp, risorse)
    condizioni.registra(mcp, risorse)
    gita.registra(mcp, risorse)
    resources.registra(mcp, risorse)
    prompts.registra(mcp)
    completamenti.registra(mcp, risorse)

    return mcp

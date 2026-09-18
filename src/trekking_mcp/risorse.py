"""Le dipendenze condivise del server, in un oggetto solo."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from trekking_mcp.config import Config
from trekking_mcp.metriche import Metriche
from trekking_mcp.sources.eaws import IndiceRegioni
from trekking_mcp.sources.http import ClientHttp
from trekking_mcp.sources.nominatim import Limitatore


@dataclass(frozen=True, slots=True)
class Risorse:
    """Tutto cio' che vive quanto il processo e non quanto una richiesta."""

    config: Config
    metriche: Metriche
    http: ClientHttp
    eaws: IndiceRegioni
    nominatim: Limitatore
    overpass: asyncio.Semaphore
    """Semaforo globale verso Overpass: limita il fan-out di un agente."""

    @classmethod
    def crea(cls, config: Config | None = None) -> Risorse:
        """Monta il grafo delle dipendenze. L'unico posto in cui e' descritto."""
        cfg = config if config is not None else Config()
        metriche = Metriche()
        http = ClientHttp(cfg, metriche)
        return cls(
            config=cfg,
            metriche=metriche,
            http=http,
            eaws=IndiceRegioni(cfg, http),
            nominatim=Limitatore(cfg.nominatim_intervallo_s),
            overpass=asyncio.Semaphore(max(1, cfg.overpass_concurrency)),
        )

    async def avvia(self) -> None:
        await self.http.avvia()

    async def chiudi(self) -> None:
        await self.http.chiudi()

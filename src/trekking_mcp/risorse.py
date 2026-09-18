"""Le dipendenze condivise del server, in un oggetto solo.

Prima erano sei singleton di modulo (`CONFIG`, `CLIENT`, `METRICHE`, `INDICE`,
il semaforo Overpass, il limitatore Nominatim), costruiti all'import. Il
sintomo si vedeva nei test: per cambiare un timeout si sostituiva un attributo
di modulo con `monkeypatch.setattr("...http.CONFIG", ...)`. Quando il modo
normale di configurare qualcosa e' riscrivere una variabile altrui, la
dipendenza non e' dichiarata da nessuna parte.

`Risorse` le dichiara. Si costruisce una volta in `crea_server()`, si passa a
ogni `registra()` e da li' scende nelle funzioni delle fonti. Un test ne crea
una sua, con il `Config` che vuole, e non tocca niente di globale.

## Perche' una closure e non solo il lifespan

L'SDK inietta il `Context` — e con esso `lifespan_context` — nei tool e nelle
resource template. **Non** lo inietta nelle resource statiche (l'SDK rifiuta
esplicitamente la registrazione) ne' nell'handler dei completamenti, che ha
una firma fissa. Visto che `metriche://fonti` e' statica e i completamenti
leggono l'indice EAWS, il `Context` da solo non basta.

Quindi le `Risorse` si legano alla registrazione, per closure: un unico
meccanismo valido per tutti e cinque i primitivi. Il lifespan resta il
padrone del *ciclo di vita* (apre e chiude il pool HTTP) e le espone anche
come `lifespan_context`, che e' la porta idiomatica dell'SDK: stesso oggetto,
due porte.
"""

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

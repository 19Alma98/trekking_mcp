from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from trekking_mcp import __version__

SITO = "https://github.com/19Alma98/trekking_mcp"

# La usage policy di Overpass chiede di identificarsi *con la versione*: un UA
# che dice "0.1" per sempre non permette a chi gestisce l'istanza di capire
# quale build sta generando traffico. Quindi la versione si legge dal pacchetto,
# non si riscrive a mano qui.
UA_DEFAULT = f"trekking-mcp/{__version__} (+{SITO})"

# Codici dei file EAWS Regions da indicizzare. IT-21 = Piemonte, IT-23 = Valle
# d'Aosta, IT-25 = Lombardia, IT-32-BZ = Bolzano, IT-32-TN = Trento,
# IT-34 = Veneto, IT-36 = Friuli, IT-57 = Marche, CH = Svizzera.
#
# La Svizzera e' nell'elenco perche' `bollettino_valanghe` accetta il provider
# `slf`: senza i suoi perimetri, `zona_valanghe_da_coordinate` non risolve un
# punto svizzero e l'autocompletamento di `zona_id` con provider `slf` resta
# vuoto per sempre. Un codice che non esiste non e' fatale: `carica()` logga un
# warning e va avanti (vedi `IndiceRegioni.carica`). Si sovrascrive l'elenco con
# EAWS_TERRITORI.
TERRITORI_DEFAULT = (
    "IT-21",
    "IT-23",
    "IT-25",
    "IT-32-BZ",
    "IT-32-TN",
    "IT-34",
    "IT-36",
    "IT-57",
    "CH",
)


def _elenco_env(nome: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Variabile d'ambiente con valori separati da virgola."""
    grezzo = os.getenv(nome)
    if grezzo is None:
        return default
    return tuple(pezzo.strip() for pezzo in grezzo.split(",") if pezzo.strip())


@dataclass(frozen=True)
class Config:
    """Configurazione del server, letta dall'ambiente al momento dell'istanza."""

    overpass_url: str = field(
        default_factory=lambda: os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
    )
    aineva_url: str = field(default_factory=lambda: os.getenv("AINEVA_CAAML_URL", "https://bollettini.aineva.it"))
    slf_url: str = field(default_factory=lambda: os.getenv("SLF_CAAML_URL", "https://aws.slf.ch/api/bulletin/caaml"))
    meteo_url: str = field(default_factory=lambda: os.getenv("METEO_URL", "https://api.open-meteo.com/v1/forecast"))
    elevazione_url: str = field(
        default_factory=lambda: os.getenv("ELEVAZIONE_URL", "https://api.open-meteo.com/v1/elevation")
    )
    eaws_regions_url: str = field(
        default_factory=lambda: os.getenv("EAWS_REGIONS_URL", "https://regions.avalanches.org")
    )
    nominatim_url: str = field(
        default_factory=lambda: os.getenv("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
    )

    user_agent: str = field(default_factory=lambda: os.getenv("TREKKING_MCP_UA", UA_DEFAULT))

    timeout_s: float = field(default_factory=lambda: float(os.getenv("HTTP_TIMEOUT", "30")))
    max_retry: int = field(default_factory=lambda: int(os.getenv("HTTP_MAX_RETRY", "3")))

    ttl_overpass_s: int = field(default_factory=lambda: int(os.getenv("TTL_OVERPASS", str(24 * 3600))))
    ttl_bollettino_s: int = field(default_factory=lambda: int(os.getenv("TTL_BOLLETTINO", str(30 * 60))))
    ttl_meteo_s: int = field(default_factory=lambda: int(os.getenv("TTL_METEO", str(15 * 60))))
    ttl_regioni_s: int = field(default_factory=lambda: int(os.getenv("TTL_REGIONI", str(30 * 24 * 3600))))
    ttl_elevazione_s: int = field(default_factory=lambda: int(os.getenv("TTL_ELEVAZIONE", str(7 * 24 * 3600))))

    cache_dir: str = field(default_factory=lambda: os.getenv("CACHE_DIR", str(Path.home() / ".cache" / "trekking-mcp")))

    nominatim_intervallo_s: float = field(default_factory=lambda: float(os.getenv("NOMINATIM_INTERVALLO", "1.0")))
    overpass_concurrency: int = field(default_factory=lambda: int(os.getenv("OVERPASS_CONCURRENCY", "1")))

    cache_max_entry: int = field(default_factory=lambda: int(os.getenv("CACHE_MAX_ENTRY", "512")))

    cache_max_byte: int = field(default_factory=lambda: int(os.getenv("CACHE_MAX_BYTE", str(64 * 1024 * 1024))))
    """Tetto in byte della cache HTTP in memoria.

    Solo il numero di voci non basta: una ricerca sentieri sta in qualche KB, una
    risposta `out geom` nell'ordine dei MB. 512 voci potevano quindi valere
    qualche megabyte o qualche gigabyte."""

    eaws_territori: tuple[str, ...] = field(default_factory=lambda: _elenco_env("EAWS_TERRITORI", TERRITORI_DEFAULT))

    state_keys: tuple[str, ...] = field(default_factory=lambda: _elenco_env("TREKKING_MCP_STATE_KEYS", ()))
    """Chiavi per sigillare il `requestState` (SEP dell'MCP 2026-07-28).

    Senza, l'SDK genera una chiave effimera per processo: le interazioni a piu'
    round-trip (elicitation) valgono solo dentro quel processo e muoiono a ogni
    riavvio. Un deploy HTTP con piu' repliche deve condividerle, altrimenti la
    replica B rifiuta lo stato emesso dalla replica A. `keys[0]` sigilla, tutte
    verificano: per ruotare si mette la nuova in testa e si tiene la vecchia in
    coda per un TTL. Almeno 32 byte di segreto per chiave, altrimenti l'SDK
    rifiuta l'avvio. Vedi DEVELOPMENT.md §3.26."""

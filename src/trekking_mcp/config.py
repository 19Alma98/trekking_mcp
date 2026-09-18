from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

UA_DEFAULT = "trekking-mcp/0.1 (+https://github.com/19Alma98/trekking_mcp)"


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

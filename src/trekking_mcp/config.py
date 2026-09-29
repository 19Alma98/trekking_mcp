from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from trekking_mcp.constants import (
    HTTP_RATE_LIMIT_BURST_DEFAULT,
    HTTP_RATE_LIMIT_MAX_KEYS_DEFAULT,
    HTTP_RATE_LIMIT_RPM_DEFAULT,
    OVERPASS_MARGINE_TIMEOUT_S,
    OVERPASS_URL_DEFAULT,
    TERRITORI_DEFAULT,
    UA_DEFAULT,
)


def _elenco_env(nome: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Variabile d'ambiente con valori separati da virgola."""
    grezzo = os.getenv(nome)
    if grezzo is None:
        return default
    return tuple(pezzo.strip() for pezzo in grezzo.split(",") if pezzo.strip())


def _bool_env(nome: str, default: bool = False) -> bool:
    grezzo = os.getenv(nome)
    if grezzo is None:
        return default
    return grezzo.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    """Configurazione del server, letta dall'ambiente al momento dell'istanza."""

    overpass_url: str = field(default_factory=lambda: os.getenv("OVERPASS_URL", OVERPASS_URL_DEFAULT))
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
    ttl_nominatim_s: int = field(default_factory=lambda: int(os.getenv("TTL_NOMINATIM", str(3600))))
    ttl_bollettino_s: int = field(default_factory=lambda: int(os.getenv("TTL_BOLLETTINO", str(30 * 60))))
    ttl_meteo_s: int = field(default_factory=lambda: int(os.getenv("TTL_METEO", str(15 * 60))))
    ttl_regioni_s: int = field(default_factory=lambda: int(os.getenv("TTL_REGIONI", str(30 * 24 * 3600))))
    ttl_elevazione_s: int = field(default_factory=lambda: int(os.getenv("TTL_ELEVAZIONE", str(7 * 24 * 3600))))

    cache_dir: str = field(default_factory=lambda: os.getenv("CACHE_DIR", str(Path.home() / ".cache" / "trekking-mcp")))

    nominatim_intervallo_s: float = field(default_factory=lambda: float(os.getenv("NOMINATIM_INTERVALLO", "1.0")))
    overpass_concurrency: int = field(default_factory=lambda: int(os.getenv("OVERPASS_CONCURRENCY", "1")))

    cache_max_entry: int = field(default_factory=lambda: int(os.getenv("CACHE_MAX_ENTRY", "512")))

    cache_max_byte: int = field(default_factory=lambda: int(os.getenv("CACHE_MAX_BYTE", str(64 * 1024 * 1024))))

    eaws_territori: tuple[str, ...] = field(default_factory=lambda: _elenco_env("EAWS_TERRITORI", TERRITORI_DEFAULT))

    state_keys: tuple[str, ...] = field(default_factory=lambda: _elenco_env("TREKKING_MCP_STATE_KEYS", ()))

    http_rate_limit_rpm: int = field(
        default_factory=lambda: int(os.getenv("HTTP_RATE_LIMIT_RPM", str(HTTP_RATE_LIMIT_RPM_DEFAULT)))
    )
    http_rate_limit_burst: int = field(
        default_factory=lambda: int(os.getenv("HTTP_RATE_LIMIT_BURST", str(HTTP_RATE_LIMIT_BURST_DEFAULT)))
    )
    http_rate_limit_max_keys: int = field(
        default_factory=lambda: int(os.getenv("HTTP_RATE_LIMIT_MAX_KEYS", str(HTTP_RATE_LIMIT_MAX_KEYS_DEFAULT)))
    )
    http_trust_proxy: bool = field(default_factory=lambda: _bool_env("HTTP_TRUST_PROXY", False))

    def __post_init__(self) -> None:
        """Clamp dei valori che altrimenti producono query o retry senza senso."""
        object.__setattr__(self, "max_retry", max(1, self.max_retry))
        object.__setattr__(self, "timeout_s", max(float(OVERPASS_MARGINE_TIMEOUT_S + 1), self.timeout_s))
        object.__setattr__(self, "ttl_overpass_s", max(0, self.ttl_overpass_s))
        object.__setattr__(self, "ttl_nominatim_s", max(0, self.ttl_nominatim_s))
        object.__setattr__(self, "ttl_bollettino_s", max(0, self.ttl_bollettino_s))
        object.__setattr__(self, "ttl_meteo_s", max(0, self.ttl_meteo_s))
        object.__setattr__(self, "ttl_regioni_s", max(0, self.ttl_regioni_s))
        object.__setattr__(self, "ttl_elevazione_s", max(0, self.ttl_elevazione_s))
        object.__setattr__(self, "cache_max_entry", max(1, self.cache_max_entry))
        object.__setattr__(self, "cache_max_byte", max(1, self.cache_max_byte))
        object.__setattr__(self, "overpass_concurrency", max(1, self.overpass_concurrency))
        object.__setattr__(self, "nominatim_intervallo_s", max(0.0, self.nominatim_intervallo_s))
        object.__setattr__(self, "http_rate_limit_rpm", max(0, self.http_rate_limit_rpm))
        object.__setattr__(self, "http_rate_limit_max_keys", max(1, self.http_rate_limit_max_keys))
        burst = max(0, self.http_rate_limit_burst)
        if self.http_rate_limit_rpm > 0:
            burst = max(1, burst)
        object.__setattr__(self, "http_rate_limit_burst", burst)

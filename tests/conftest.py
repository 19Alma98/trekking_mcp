"""Configurazione pytest condivisa."""

from dataclasses import replace

import pytest

from trekking_mcp.config import Config
from trekking_mcp.risorse import Risorse


@pytest.fixture(autouse=True)
def _ambiente_pulito(monkeypatch):
    """Evita che le variabili d'ambiente della macchina alterino i test."""
    for chiave in ("OVERPASS_URL", "AINEVA_CAAML_URL", "SLF_CAAML_URL", "METEO_URL"):
        monkeypatch.delenv(chiave, raising=False)


@pytest.fixture
def config() -> Config:
    return Config()


@pytest.fixture
def risorse(config: Config) -> Risorse:
    """Risorse nuove per ogni test.

    Prima la configurazione si cambiava riscrivendo un attributo di modulo
    (`monkeypatch.setattr("...http.CONFIG", ...)`), e cache e metriche erano
    condivise fra tutti i test: da cui le fixture che le svuotavano a mano.
    Qui ogni test ha le sue, e per cambiare un valore si costruisce un
    `Config` diverso — vedi `risorse_con`.
    """
    return Risorse.crea(config)


@pytest.fixture
def risorse_con():
    """Risorse con qualche campo di Config diverso: `risorse_con(max_retry=2)`."""

    def costruisci(**campi: object) -> Risorse:
        return Risorse.crea(replace(Config(), **campi))  # type: ignore[arg-type]

    return costruisci

from __future__ import annotations

import json
import pathlib
from dataclasses import replace
from typing import Any

import pytest

from trekking_mcp.config import Config
from trekking_mcp.risorse import Risorse

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def carica_fixture(*parti: str) -> dict[str, Any]:
    """Carica un JSON sotto `tests/fixtures/` (es. `caaml`, `aineva_latest_slice.json`)."""
    percorso = FIXTURES.joinpath(*parti)
    return json.loads(percorso.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _ambiente_pulito(monkeypatch):
    """Evita che le variabili d'ambiente della macchina alterino i test."""
    for chiave in (
        "OVERPASS_URL",
        "AINEVA_CAAML_URL",
        "SLF_CAAML_URL",
        "METEO_URL",
        "HTTP_RATE_LIMIT_RPM",
        "HTTP_RATE_LIMIT_BURST",
    ):
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

"""Configurazione pytest condivisa."""

import pytest


@pytest.fixture(autouse=True)
def _ambiente_pulito(monkeypatch):
    """Evita che le variabili d'ambiente della macchina alterino i test."""
    for chiave in ("OVERPASS_URL", "AINEVA_CAAML_URL", "SLF_CAAML_URL", "METEO_URL"):
        monkeypatch.delenv(chiave, raising=False)

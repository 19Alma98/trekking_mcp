"""Comportamento sotto chiamate concorrenti.

Un agente non chiama i tool uno alla volta: fa fan-out. Questi test
riproducono quel caso, che e' dove si vedono le corse che un test
sequenziale non tocca mai.
"""

from __future__ import annotations

import asyncio

import pytest

from trekking_mcp.payloads import EawsFeatureCollection
from trekking_mcp.sources import eaws

GEOJSON_UNA_ZONA: EawsFeatureCollection = {
    "features": [
        {
            "properties": {"id": "IT-21-TEST", "name": "Zona di prova"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[7.0, 45.0], [7.1, 45.0], [7.1, 45.1], [7.0, 45.1], [7.0, 45.0]]],
            },
        }
    ]
}

DENTRO = (45.05, 7.05)


@pytest.fixture
def indice(monkeypatch, risorse):
    """Indice isolato, con un solo territorio e un download finto ma lento."""
    monkeypatch.setattr(eaws, "TERRITORI_ITALIA", ["IT-21"])
    idx = risorse.eaws
    idx.scaricamenti = 0

    async def _scarica(territorio: str) -> EawsFeatureCollection:
        idx.scaricamenti += 1
        # La latenza e' il punto: senza un await qui non c'e' finestra di corsa.
        await asyncio.sleep(0.01)
        return GEOJSON_UNA_ZONA

    monkeypatch.setattr(idx, "_scarica", _scarica)
    return idx


async def test_due_ricerche_concorrenti_caricano_l_indice_una_volta_sola(indice):
    await asyncio.gather(indice.cerca(*DENTRO), indice.cerca(*DENTRO))

    assert indice.scaricamenti == 1, "il territorio e' stato scaricato piu' volte"


async def test_la_concorrenza_non_duplica_le_micro_regioni(indice):
    await asyncio.gather(*(indice.cerca(*DENTRO) for _ in range(5)))

    id_zone = [r.id_zona for r in indice.regioni]
    assert id_zone == ["IT-21-TEST"], f"micro-regioni duplicate in indice: {id_zone}"


async def test_un_punto_resta_in_una_zona_sola_dopo_il_fan_out(indice):
    """I duplicati in indice si vedevano qui: lo stesso punto in N zone identiche."""
    await asyncio.gather(*(indice.cerca(*DENTRO) for _ in range(5)))

    assert len(await indice.cerca(*DENTRO)) == 1


async def test_un_territorio_gia_caricato_non_viene_riscaricato(indice):
    await indice.carica()
    await indice.carica()

    assert indice.scaricamenti == 1

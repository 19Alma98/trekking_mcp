from __future__ import annotations

import pytest
import respx

from trekking_mcp.sources import nominatim
from trekking_mcp.sources.http import CLIENT


@pytest.fixture(autouse=True)
async def _svuota_cache():
    await CLIENT.cache.svuota()
    yield
    await CLIENT.cache.svuota()


async def _no_attendi() -> None:
    return None


def _nominatim_senza_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _orig_json = CLIENT.json

    async def _json_no_cache(*args, **kwargs):
        kwargs["ttl_s"] = None
        return await _orig_json(*args, **kwargs)

    monkeypatch.setattr(CLIENT, "json", _json_no_cache)


async def test_nominatim_scarta_hit_oltre_raggio(httpx2_mock: respx.Router, monkeypatch):
    import httpx

    monkeypatch.setattr(nominatim.LIMITATORE, "attendi", _no_attendi)
    _nominatim_senza_cache(monkeypatch)
    httpx2_mock.get(url__startswith="https://nominatim.openstreetmap.org").respond(
        200,
        json=[
            {
                "lat": "39.3",
                "lon": "16.3",
                "type": "peak",
                "display_name": "Fiume Mucone CS",
                "osm_type": "way",
                "osm_id": 9,
            },
            {
                "lat": "45.61",
                "lon": "7.95",
                "type": "peak",
                "display_name": "Monte Mucrone",
                "osm_type": "node",
                "osm_id": 1,
                "extratags": {"ele": "2335"},
            },
        ],
    )
    esito = await nominatim.cerca("Mucone", lat=45.57, lon=8.05, raggio_km=30, limite=5)
    assert len(esito) == 1
    assert esito[0].nome == "Monte Mucrone"


async def test_nominatim_contestuale_non_fa_bounded_zero(httpx2_mock: respx.Router, monkeypatch):
    import httpx

    monkeypatch.setattr(nominatim.LIMITATORE, "attendi", _no_attendi)
    _nominatim_senza_cache(monkeypatch)
    rotta = httpx2_mock.get(url__startswith="https://nominatim.openstreetmap.org").mock(
        side_effect=[
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
        ]
    )
    esito = await nominatim.cerca("Xyzzy", lat=45.57, lon=8.05, raggio_km=30)
    assert esito == []
    assert rotta.call_count == 2
    assert all(dict(c.request.url.params).get("bounded") == "1" for c in rotta.calls)


from trekking_mcp.models import Coord, Localita
from trekking_mcp.sources import luoghi_simili


def test_similarita_mucone_mucrone_sopra_soglia():
    assert luoghi_simili.similarita_nome("Mucone", "Monte Mucrone") >= luoghi_simili.SOGLIA_SIMILARITA


def test_similarita_biella_mucrone_sotto_soglia():
    assert luoghi_simili.similarita_nome("Biella", "Monte Mucrone") < luoghi_simili.SOGLIA_SIMILARITA


def test_filtra_simili_ordina_per_ratio_poi_distanza():
    lat, lon = 45.57, 8.05
    candidati = [
        Localita(nome="Monte Mucrone", tipo="peak", coord=Coord(lat=45.61, lon=7.95), quota_m=2335),
        Localita(nome="Mucrone Basso", tipo="peak", coord=Coord(lat=45.575, lon=8.04)),  # piu' vicino, nome meno simile
        Localita(nome="Biella", tipo="town", coord=Coord(lat=45.57, lon=8.05)),
    ]
    out = luoghi_simili.filtra_simili("Mucone", candidati, lat=lat, lon=lon)
    assert [c.nome for c in out][0] == "Monte Mucrone"
    assert all(luoghi_simili.similarita_nome("Mucone", c.nome) >= luoghi_simili.SOGLIA_SIMILARITA for c in out)
    assert len(out) <= luoghi_simili.MAX_CANDIDATI_SIMILI

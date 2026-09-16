from __future__ import annotations

from urllib.parse import parse_qs

import pytest
import respx

from trekking_mcp.models import Coord, Sentiero
from trekking_mcp.sources import overpass
from trekking_mcp.sources.http import CLIENT
from trekking_mcp.tools import sentieri as tool_sentieri


@pytest.fixture(autouse=True)
async def _svuota_cache_latency():
    await CLIENT.cache.svuota()
    yield
    await CLIENT.cache.svuota()


def _sentiero(osm_id: int, ref: str | None, lat: float, lon: float) -> Sentiero:
    return Sentiero(
        osm_relation_id=osm_id,
        ref=ref,
        centro=Coord(lat=lat, lon=lon),
        osm_url=f"https://www.openstreetmap.org/relation/{osm_id}",
    )


def test_ordina_sentieri_per_distanza_tiene_i_piu_vicini():
    # Punto query: Biella ~45.57, 8.05
    lontani_prima_per_ref = [
        _sentiero(1, "Z99", 46.0, 8.5),   # lontano
        _sentiero(2, "A01", 45.58, 8.06),  # vicino
        _sentiero(3, None, 45.575, 8.055), # vicinissimo, senza ref
    ]
    esito = tool_sentieri.ordina_sentieri_per_distanza(
        lontani_prima_per_ref, lat=45.57, lon=8.05, limite=2
    )
    assert [s.osm_relation_id for s in esito] == [3, 2]
    assert esito[0].distanza_km is not None
    assert esito[0].distanza_km <= esito[1].distanza_km
    # arrotondato a 0.1 km
    assert esito[0].distanza_km == round(esito[0].distanza_km, 1)


async def test_leggi_geometria_senza_way_non_chiama_out_geom(httpx2_mock: respx.Router):
    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(
        200,
        json={
            "elements": [
                {
                    "type": "relation",
                    "id": 42,
                    "tags": {"ref": "X"},
                    "members": [{"type": "node", "ref": 1, "role": ""}],
                }
            ]
        },
    )
    esito = await overpass.leggi_geometria(42)
    assert esito is not None
    sentiero, punti = esito
    assert sentiero.osm_relation_id == 42
    assert punti == []
    assert rotta.call_count == 1  # solo query leggera (out;), niente out geom

    body = rotta.calls[0].request.content
    if isinstance(body, bytes):
        body = body.decode()
    ql = parse_qs(body)["data"][0]
    assert "out;" in ql
    assert "out tags geom" not in ql
    assert "out geom" not in ql


async def _no_attendi() -> None:
    return None


def test_testo_da_toponimo_usa_ultima_parola_significativa():
    from trekking_mcp.tools.sentieri import testo_da_toponimo

    assert testo_da_toponimo("Monte Mucrone") == "Mucrone"
    assert testo_da_toponimo("Mucrone") == "Mucrone"
    assert testo_da_toponimo("Rifugio Gastaldi") == "Gastaldi"


async def test_esegui_sentieri_verso_localita(httpx2_mock: respx.Router, monkeypatch):
    import httpx
    from trekking_mcp.tools.sentieri import esegui_sentieri_verso_localita

    monkeypatch.setattr("trekking_mcp.sources.nominatim.LIMITATORE.attendi", _no_attendi)
    httpx2_mock.get(url__startswith="https://nominatim.openstreetmap.org").respond(
        200,
        json=[
            {
                "lat": "45.61",
                "lon": "7.95",
                "type": "peak",
                "display_name": "Monte Mucrone",
                "osm_type": "node",
                "osm_id": 1,
                "extratags": {"ele": "2335"},
            }
        ],
    )
    httpx2_mock.post(url__startswith="https://overpass-api.de").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "relation",
                            "id": 100,
                            "tags": {"ref": "C19", "name": "verso Mucrone"},
                            "center": {"lat": 45.60, "lon": 7.96},
                        }
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "elements": [
                        {
                            "type": "node",
                            "id": 50,
                            "lat": 45.60,
                            "lon": 7.96,
                            "tags": {"tourism": "alpine_hut", "name": "Rifugio"},
                        }
                    ]
                },
            ),
        ]
    )

    out = await esegui_sentieri_verso_localita(
        nome="Monte Mucrone",
        vicino_a_lat=45.57,
        vicino_a_lon=8.05,
        raggio_km=5,
        limite=15,
        includi_ricoveri=True,
    )
    assert out.localita.nome == "Monte Mucrone"
    assert len(out.sentieri) == 1
    assert out.sentieri[0].ref == "C19"
    assert out.sentieri[0].distanza_km is not None
    assert len(out.ricoveri) == 1

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import respx
from mcp.server.elicitation import AcceptedElicitation, CancelledElicitation, DeclinedElicitation
from pydantic import BaseModel

from trekking_mcp.errors import FonteNonDisponibile, NonTrovato
from trekking_mcp.models import Coord, Localita
from trekking_mcp.sources import luoghi_simili, nominatim
from trekking_mcp.sources.http import CLIENT
from trekking_mcp.sources.luoghi_simili import (
    cerca_simili_nel_raggio,
    localita_da_elemento,
    query_luoghi_bbox,
)
from trekking_mcp.tools import geocode_risolvi


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
    assert next(c.nome for c in out) == "Monte Mucrone"
    assert all(luoghi_simili.similarita_nome("Mucone", c.nome) >= luoghi_simili.SOGLIA_SIMILARITA for c in out)
    assert len(out) <= luoghi_simili.MAX_CANDIDATI_SIMILI


def test_query_luoghi_bbox_include_tipi_utili():
    ql = query_luoghi_bbox(45.0, 7.0, 46.0, 8.0)
    assert '["natural"~"^(peak|saddle)$"]' in ql
    assert '["tourism"~"^(alpine_hut|wilderness_hut)$"]' in ql
    assert '["place"~"^(village|hamlet|town|locality|isolated_dwelling)$"]' in ql
    assert "out tags center" in ql


def test_localita_da_elemento_peak():
    loc = localita_da_elemento(
        {
            "type": "node",
            "id": 1,
            "lat": 45.61,
            "lon": 7.95,
            "tags": {"natural": "peak", "name": "Monte Mucrone", "ele": "2335"},
        }
    )
    assert loc is not None
    assert loc.nome == "Monte Mucrone"
    assert loc.tipo == "peak"
    assert loc.quota_m == 2335
    assert loc.osm_url == "https://www.openstreetmap.org/node/1"


async def test_cerca_simili_nel_raggio_mock_overpass(httpx2_mock: respx.Router):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(
        200,
        json={
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 45.61,
                    "lon": 7.95,
                    "tags": {"natural": "peak", "name": "Monte Mucrone", "ele": "2335"},
                },
                {
                    "type": "node",
                    "id": 2,
                    "lat": 45.57,
                    "lon": 8.05,
                    "tags": {"place": "town", "name": "Biella"},
                },
            ]
        },
    )
    out = await cerca_simili_nel_raggio("Mucone", lat=45.57, lon=8.05, raggio_km=30)
    assert len(out) == 1
    assert out[0].nome == "Monte Mucrone"


async def test_cerca_simili_overpass_giu_restituisce_lista_vuota(monkeypatch):
    async def _boom(ql: str, *, ttl_s=None):
        raise FonteNonDisponibile("overpass", "test")

    monkeypatch.setattr("trekking_mcp.sources.overpass.esegui", _boom)
    out = await cerca_simili_nel_raggio("Mucone", lat=45.57, lon=8.05, raggio_km=30)
    assert out == []


@dataclass
class FakeCtx:
    elicit_calls: list[tuple[str, type]] = field(default_factory=list)
    elicit_results: list[Any] = field(default_factory=list)

    async def elicit(self, message: str, schema: type[BaseModel]):
        self.elicit_calls.append((message, schema))
        return self.elicit_results.pop(0)


async def test_risolvi_match_esatto_non_elicit(httpx2_mock: respx.Router, monkeypatch):
    monkeypatch.setattr(nominatim.LIMITATORE, "attendi", _no_attendi)
    _nominatim_senza_cache(monkeypatch)
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
    ctx = FakeCtx()
    out = await geocode_risolvi.risolvi_localita(ctx, "Mucrone", lat=45.57, lon=8.05)  # type: ignore[arg-type]
    assert len(out) == 1
    assert out[0].nome == "Monte Mucrone"
    assert ctx.elicit_calls == []


async def test_risolvi_simile_usa_1(httpx2_mock: respx.Router, monkeypatch):
    monkeypatch.setattr(nominatim.LIMITATORE, "attendi", _no_attendi)
    _nominatim_senza_cache(monkeypatch)
    httpx2_mock.get(url__startswith="https://nominatim.openstreetmap.org").respond(200, json=[])

    async def _simili(nome, *, lat, lon, raggio_km):
        return [
            Localita(
                nome="Monte Mucrone",
                tipo="peak",
                coord=Coord(lat=45.61, lon=7.95),
                quota_m=2335,
            )
        ]

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.cerca_simili_nel_raggio", _simili)
    ctx = FakeCtx(
        elicit_results=[AcceptedElicitation(data=geocode_risolvi.SceltaGeocode(azione="usa_1", nuovo_raggio_km=50))]
    )
    out = await geocode_risolvi.risolvi_localita(ctx, "Mucone", lat=45.57, lon=8.05)  # type: ignore[arg-type]
    assert len(out) == 1
    assert out[0].nome == "Monte Mucrone"
    assert len(ctx.elicit_calls) == 1
    assert "Mucone" in ctx.elicit_calls[0][0]
    assert "usa_1" in ctx.elicit_calls[0][0] or "1)" in ctx.elicit_calls[0][0]


async def test_risolvi_espandi_poi_match(monkeypatch):
    chiamate: list[float] = []

    async def _cerca(nome, *, limite=5, solo_montagna=True, lat=None, lon=None, raggio_km=30):
        chiamate.append(raggio_km)
        if raggio_km >= 50:
            return [Localita(nome="Monte Mucrone", tipo="peak", coord=Coord(lat=45.61, lon=7.95))]
        return []

    async def _nessun_simile(nome, *, lat, lon, raggio_km):
        return []

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.nominatim.cerca", _cerca)
    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.cerca_simili_nel_raggio", _nessun_simile)
    ctx = FakeCtx(
        elicit_results=[AcceptedElicitation(data=geocode_risolvi.SceltaGeocode(azione="espandi", nuovo_raggio_km=50))]
    )
    out = await geocode_risolvi.risolvi_localita(ctx, "Mucone", lat=45.57, lon=8.05, raggio_km=30)  # type: ignore[arg-type]
    assert out[0].nome == "Monte Mucrone"
    assert chiamate == [30.0, 50.0]


async def test_risolvi_decline_solleva_non_trovato(monkeypatch):
    async def _vuoto(*args, **kwargs):
        return []

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.nominatim.cerca", _vuoto)
    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.cerca_simili_nel_raggio", _vuoto)
    ctx = FakeCtx(elicit_results=[DeclinedElicitation()])
    with pytest.raises(NonTrovato):
        await geocode_risolvi.risolvi_localita(ctx, "Mucone", lat=45.57, lon=8.05)  # type: ignore[arg-type]


async def test_risolvi_cancel_solleva_non_trovato(monkeypatch):
    async def _vuoto(*args, **kwargs):
        return []

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.nominatim.cerca", _vuoto)
    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.cerca_simili_nel_raggio", _vuoto)
    ctx = FakeCtx(elicit_results=[CancelledElicitation()])
    with pytest.raises(NonTrovato):
        await geocode_risolvi.risolvi_localita(ctx, "Mucone", lat=45.57, lon=8.05)  # type: ignore[arg-type]


async def test_risolvi_terza_espansione_solleva_non_trovato(monkeypatch):
    async def _vuoto(*args, **kwargs):
        return []

    async def _nessun_simile(*args, **kwargs):
        return []

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.nominatim.cerca", _vuoto)
    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.cerca_simili_nel_raggio", _nessun_simile)
    ctx = FakeCtx(
        elicit_results=[
            AcceptedElicitation(data=geocode_risolvi.SceltaGeocode(azione="espandi", nuovo_raggio_km=50)),
            AcceptedElicitation(data=geocode_risolvi.SceltaGeocode(azione="espandi", nuovo_raggio_km=80)),
            AcceptedElicitation(data=geocode_risolvi.SceltaGeocode(azione="espandi", nuovo_raggio_km=110)),
        ]
    )
    with pytest.raises(NonTrovato):
        await geocode_risolvi.risolvi_localita(ctx, "Mucone", lat=45.57, lon=8.05, raggio_km=30)  # type: ignore[arg-type]


async def test_risolvi_usa_n_invalido_solleva_non_trovato(monkeypatch):
    async def _vuoto(*args, **kwargs):
        return []

    async def _simili(nome, *, lat, lon, raggio_km):
        return [
            Localita(nome="Monte Mucrone", tipo="peak", coord=Coord(lat=45.61, lon=7.95)),
        ]

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.nominatim.cerca", _vuoto)
    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.cerca_simili_nel_raggio", _simili)
    ctx = FakeCtx(
        elicit_results=[
            AcceptedElicitation(data=geocode_risolvi.SceltaGeocode(azione="usa_99", nuovo_raggio_km=50)),
        ]
    )
    with pytest.raises(NonTrovato):
        await geocode_risolvi.risolvi_localita(ctx, "Mucone", lat=45.57, lon=8.05)  # type: ignore[arg-type]


async def test_risolvi_raggio_non_crescente_solleva_non_trovato(monkeypatch):
    async def _vuoto(*args, **kwargs):
        return []

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.nominatim.cerca", _vuoto)
    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.cerca_simili_nel_raggio", _vuoto)
    ctx = FakeCtx(
        elicit_results=[
            AcceptedElicitation(data=geocode_risolvi.SceltaGeocode(azione="espandi", nuovo_raggio_km=50)),
        ]
    )
    with pytest.raises(NonTrovato) as exc:
        await geocode_risolvi.risolvi_localita(ctx, "Mucone", lat=45.57, lon=8.05, raggio_km=60)  # type: ignore[arg-type]
    assert exc.value.alternative == ["nuovo_raggio_km deve essere > 60"]


async def test_cerca_localita_usa_risolvi_con_contesto(monkeypatch):
    from trekking_mcp.server import crea_server

    async def _risolvi(ctx, nome, *, lat, lon, raggio_km=30, limite=5):
        assert nome == "Mucone"
        assert lat == 45.57 and lon == 8.05
        assert raggio_km == 30
        assert limite == 5
        return [Localita(nome="Monte Mucrone", tipo="peak", coord=Coord(lat=45.61, lon=7.95))]

    monkeypatch.setattr("trekking_mcp.tools.geocode_risolvi.risolvi_localita", _risolvi)
    mcp = crea_server()
    ctx = FakeCtx()
    esito = await mcp.call_tool(
        "cerca_localita",
        {"nome": "Mucone", "lat": 45.57, "lon": 8.05, "raggio_km": 30, "limite": 5},
        context=ctx,  # type: ignore[arg-type]
    )
    assert not esito.is_error
    localita = esito.structured_content["result"]
    assert localita[0]["nome"] == "Monte Mucrone"


async def test_esegui_sentieri_verso_usa_risolvi_con_contesto(monkeypatch):
    from trekking_mcp.tools.sentieri import esegui_sentieri_verso_localita

    async def _risolvi(ctx, nome, *, lat, lon, raggio_km=30, limite=5):
        assert nome == "Mucone"
        assert lat == 45.57 and lon == 8.05
        assert raggio_km == 30
        assert limite == 1
        return [Localita(nome="Monte Mucrone", tipo="peak", coord=Coord(lat=45.61, lon=7.95))]

    async def _sentieri(**kwargs):
        return []

    async def _ricoveri(**kwargs):
        return []

    monkeypatch.setattr("trekking_mcp.tools.sentieri.risolvi_localita", _risolvi)
    monkeypatch.setattr("trekking_mcp.tools.sentieri.overpass.cerca_sentieri", _sentieri)
    monkeypatch.setattr("trekking_mcp.tools.sentieri.overpass.cerca_ricoveri", _ricoveri)
    ctx = FakeCtx()
    out = await esegui_sentieri_verso_localita(
        ctx=ctx,  # type: ignore[arg-type]
        nome="Mucone",
        vicino_a_lat=45.57,
        vicino_a_lon=8.05,
        raggio_km=5,
        raggio_geocode_km=30,
        includi_ricoveri=False,
    )
    assert out.localita.nome == "Monte Mucrone"

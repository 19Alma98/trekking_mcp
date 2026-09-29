from __future__ import annotations

import math

import pytest
from respx import Router

from tests.conftest import carica_fixture
from trekking_mcp.models import DifficoltaCAI, GradoPericolo
from trekking_mcp.risorse import Risorse
from trekking_mcp.sources import caaml, overpass


def _prima_zona(bulletins: list[dict], *, prefisso: str) -> str:
    for b in bulletins:
        for r in b.get("regions") or []:
            rid = r.get("regionID")
            if isinstance(rid, str) and rid.startswith(prefisso):
                return rid
    raise AssertionError(f"nessuna zona {prefisso}* nella fixture")


@pytest.mark.parametrize(
    ("file_fixture", "prefisso", "provider"),
    [
        ("aineva_latest_slice.json", "IT-", "aineva"),
        ("slf_latest_slice.json", "CH-", "slf"),
    ],
)
def test_normalizza_ogni_bulletin_della_fixture(file_fixture: str, prefisso: str, provider: str):
    grezzo = carica_fixture("caaml", file_fixture)
    bulletins = grezzo["bulletins"]
    assert bulletins, f"{file_fixture} senza bulletins"

    con_valutazioni = 0
    for b in bulletins:
        zona = _prima_zona([b], prefisso=prefisso)
        out = caaml.normalizza(b, zona_id=zona, provider=provider, url="https://fixture.test")
        assert out.id_bollettino
        assert out.zona_id == zona
        assert out.fonte == provider
        assert out.avvertenza
        for v in out.valutazioni:
            assert isinstance(v.grado, GradoPericolo)
        if b.get("dangerRatings"):
            assert out.valutazioni, "dangerRatings presenti ma valutazioni vuote"
            con_valutazioni += 1
        highlights = b.get("highlights") or b.get("avalancheActivity")
        if isinstance(highlights, dict):
            assert out.sintesi, "TextBlock presente ma sintesi vuota"

    assert con_valutazioni >= 1, f"{file_fixture}: almeno un bulletin con gradi"


async def test_leggi_bollettino_aineva_da_fixture(httpx2_mock: Router, risorse: Risorse):
    payload = carica_fixture("caaml", "aineva_latest_slice.json")
    zona = _prima_zona(payload["bulletins"], prefisso="IT-")
    httpx2_mock.get(url__startswith="https://bollettini.aineva.it").respond(200, json=payload)

    b = await caaml.leggi_bollettino(risorse, zona_id=zona, provider="aineva")
    assert b.zona_id == zona
    assert b.fonte == "aineva"
    assert b.avvertenza


async def test_leggi_bollettino_slf_da_fixture(httpx2_mock: Router, risorse: Risorse):
    payload = carica_fixture("caaml", "slf_latest_slice.json")
    zona = _prima_zona(payload["bulletins"], prefisso="CH-")
    httpx2_mock.get(url__startswith="https://aws.slf.ch").respond(200, json=payload)

    b = await caaml.leggi_bollettino(risorse, zona_id=zona, provider="slf")
    assert b.zona_id == zona
    assert b.fonte == "slf"
    assert b.avvertenza


def test_sentieri_da_relation_centro_reale():
    dati = carica_fixture("overpass", "relation_centro.json")
    relazioni = [el for el in dati["elements"] if el.get("type") == "relation"]
    assert relazioni
    for rel in relazioni:
        s = overpass.sentiero_da_relation(rel)
        assert s.ref or s.nome
        assert s.difficolta_cai in DifficoltaCAI
        assert s.osm_relation_id == rel["id"]


def test_polilinea_da_geom_reale():
    dati = carica_fixture("overpass", "relation_geom.json")
    rel = next(el for el in dati["elements"] if el.get("type") == "relation")
    punti = overpass.polilinea(rel)
    assert len(punti) >= 2
    assert all(math.isfinite(p.lat) and math.isfinite(p.lon) for p in punti)


def test_ricoveri_da_nodi_reali():
    dati = carica_fixture("overpass", "ricoveri_nodo.json")
    elementi = [el for el in dati["elements"] if el.get("tags")]
    assert elementi
    for el in elementi:
        r = overpass.ricovero_da_element(el)
        assert r is not None
        assert math.isfinite(r.coord.lat) and math.isfinite(r.coord.lon)


async def test_cerca_sentieri_con_fixture_http(httpx2_mock: Router, risorse: Risorse):
    payload = carica_fixture("overpass", "relation_centro.json")
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=payload)

    esito = await overpass.cerca_sentieri(risorse, sud=45.50, ovest=7.85, nord=45.75, est=8.20)
    assert esito
    assert esito[0].ref or esito[0].nome


async def test_leggi_geometria_con_fixture_http(httpx2_mock: Router, risorse: Risorse):
    payload = carica_fixture("overpass", "relation_geom.json")
    rel = next(el for el in payload["elements"] if el.get("type") == "relation")
    osm_id = int(rel["id"])
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=payload)

    esito = await overpass.leggi_geometria(risorse, osm_id)
    assert esito is not None
    sentiero, punti = esito
    assert sentiero.osm_relation_id == osm_id
    assert len(punti) >= 2

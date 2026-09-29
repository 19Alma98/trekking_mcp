from datetime import UTC, datetime

import pytest

from trekking_mcp.models import (
    Bollettino,
    DifficoltaCAI,
    GradoPericolo,
    Ricovero,
    SacScale,
    Sentiero,
    TipoRicovero,
)
from trekking_mcp.sources.overpass import ricovero_da_element, sentiero_da_relation


def test_relation_completa():
    rel = {
        "type": "relation",
        "id": 123456,
        "center": {"lat": 45.07, "lon": 7.68},
        "tags": {
            "route": "hiking",
            "ref": "103",
            "name": "Sentiero del Vallone",
            "from": "Balme",
            "to": "Rifugio Gastaldi",
            "operator": "CAI Torino",
            "network": "lwn",
            "sac_scale": "mountain_hiking",
            "trail_visibility": "good",
            "distance": "8.5 km",
        },
    }
    s = sentiero_da_relation(rel)

    assert s.ref == "103"
    assert s.da == "Balme"
    assert s.sac_scale is SacScale.T2
    assert s.difficolta_cai is DifficoltaCAI.E
    assert s.lunghezza_km == pytest.approx(8.5)
    assert s.osm_url.endswith("/relation/123456")


def test_relation_minima():
    s = sentiero_da_relation({"type": "relation", "id": 1, "tags": {"route": "hiking"}})

    assert s.ref is None
    assert s.difficolta_cai is DifficoltaCAI.SCONOSCIUTA
    assert s.centro is None


def test_lo_schema_di_sentiero_spiega_i_campi_osm_incompleti():
    props = Sentiero.model_json_schema()["properties"]
    assert "sconosciuta" in props["difficolta_cai"]["description"].lower()
    assert "facile" in props["difficolta_cai"]["description"].lower()
    assert (
        "null" in props["lunghezza_km"]["description"].lower()
        or "assente" in props["lunghezza_km"]["description"].lower()
    )
    assert (
        "non mappato" in props["sac_scale"]["description"].lower()
        or "assente" in props["sac_scale"]["description"].lower()
    )


def test_lo_schema_di_ricovero_spiega_i_contatti_opzionali():
    props = Ricovero.model_json_schema()["properties"]
    for campo in ("posti_letto", "telefono", "sito_web"):
        assert "osm" in props[campo]["description"].lower() or "mappatura" in props[campo]["description"].lower()


def test_sac_scale_ignoto_non_rompe():
    s = sentiero_da_relation({"type": "relation", "id": 2, "tags": {"sac_scale": "molto_difficile"}})

    assert s.sac_scale is None
    assert s.difficolta_cai is DifficoltaCAI.SCONOSCIUTA


@pytest.mark.parametrize(
    ("sac", "atteso"),
    [
        ("hiking", DifficoltaCAI.T),
        ("demanding_mountain_hiking", DifficoltaCAI.EE),
        ("alpine_hiking", DifficoltaCAI.EE),
        ("difficult_alpine_hiking", DifficoltaCAI.EEA),
    ],
)
def test_conversione_scale(sac: str, atteso: DifficoltaCAI):
    s = sentiero_da_relation({"type": "relation", "id": 3, "tags": {"sac_scale": sac}})
    assert s.difficolta_cai is atteso


def test_ricovero_da_nodo():
    el = {
        "type": "node",
        "id": 999,
        "lat": 45.30,
        "lon": 7.12,
        "tags": {
            "tourism": "alpine_hut",
            "name": "Rifugio Gastaldi",
            "ele": "2659",
            "beds": "80",
            "phone": "+39 0123 000000",
        },
    }
    r = ricovero_da_element(el)

    assert r.tipo is TipoRicovero.RIFUGIO
    assert r.quota_m == 2659
    assert r.posti_letto == 80


def test_ricovero_quota_decimale():
    el = {"type": "node", "id": 1, "lat": 45.0, "lon": 7.0, "tags": {"tourism": "wilderness_hut", "ele": "2659.4"}}
    r = ricovero_da_element(el)

    assert r.tipo is TipoRicovero.BIVACCO
    assert r.quota_m == 2659


def test_etichette_pericolo():
    assert GradoPericolo.MARCATO.etichetta == "Marcato"
    assert int(GradoPericolo.MOLTO_FORTE) == 5


def test_un_ricovero_sull_equatore_non_esplode():
    ricovero = ricovero_da_element(
        {"id": 7, "type": "node", "lat": 0.0, "lon": 0.0, "tags": {"tourism": "alpine_hut", "name": "Zero"}}
    )

    assert (ricovero.coord.lat, ricovero.coord.lon) == (0.0, 0.0)


def test_un_elemento_senza_coordinate_viene_saltato():
    assert ricovero_da_element({"id": 8, "type": "node", "tags": {"tourism": "alpine_hut"}}) is None


async def test_cerca_ricoveri_salta_elementi_senza_coordinate(httpx2_mock, risorse):
    from trekking_mcp.sources import overpass

    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(
        200,
        json={
            "elements": [
                {"type": "node", "id": 1, "tags": {"tourism": "alpine_hut", "name": "SenzaCoord"}},
                {
                    "type": "node",
                    "id": 2,
                    "lat": 45.3,
                    "lon": 7.1,
                    "tags": {"tourism": "alpine_hut", "name": "Gastaldi"},
                },
            ]
        },
    )
    esito = await overpass.cerca_ricoveri(risorse, lat=45.3, lon=7.1, raggio_m=5000)
    assert len(esito) == 1
    assert esito[0].nome == "Gastaldi"


@pytest.mark.parametrize(
    ("raw", "atteso"),
    [
        ("8500 m", 8.5),
        ("5.3 mi", pytest.approx(5.3 * 1.609344)),
        ("12", 12.0),
        ("8,5 km", 8.5),
        ("foo", None),
    ],
)
def test_distance_tag_con_unita(raw: str, atteso: float | None):
    s = sentiero_da_relation({"type": "relation", "id": 1, "tags": {"route": "hiking", "distance": raw}})
    if atteso is None:
        assert s.lunghezza_km is None
    else:
        assert s.lunghezza_km == atteso


def test_un_bollettino_senza_gradi_leggibili_non_dichiara_pericolo_debole():
    senza = Bollettino(
        id_bollettino="x",
        zona_id="IT-21-TEST",
        valido_da=datetime(2026, 1, 1, tzinfo=UTC),
        valido_fino=datetime(2026, 1, 2, tzinfo=UTC),
        valutazioni=[],
        fonte="aineva",
        fonte_url="https://esempio.test",
    )

    assert senza.grado_massimo is None

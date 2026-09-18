import pytest

from trekking_mcp.models import (
    DifficoltaCAI,
    GradoPericolo,
    Ricovero,
    SacScale,
    Sentiero,
    TipoRicovero,
)


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
    s = Sentiero.da_relation(rel)

    assert s.ref == "103"
    assert s.da == "Balme"
    assert s.sac_scale is SacScale.T2
    assert s.difficolta_cai is DifficoltaCAI.E
    assert s.lunghezza_km == pytest.approx(8.5)
    assert s.osm_url.endswith("/relation/123456")


def test_relation_minima():
    s = Sentiero.da_relation({"type": "relation", "id": 1, "tags": {"route": "hiking"}})

    assert s.ref is None
    assert s.difficolta_cai is DifficoltaCAI.SCONOSCIUTA
    assert s.centro is None


def test_sac_scale_ignoto_non_rompe():
    s = Sentiero.da_relation({"type": "relation", "id": 2, "tags": {"sac_scale": "molto_difficile"}})

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
    s = Sentiero.da_relation({"type": "relation", "id": 3, "tags": {"sac_scale": sac}})
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
    r = Ricovero.da_element(el)

    assert r.tipo is TipoRicovero.RIFUGIO
    assert r.quota_m == 2659
    assert r.posti_letto == 80


def test_ricovero_quota_decimale():
    el = {"type": "node", "id": 1, "lat": 45.0, "lon": 7.0, "tags": {"tourism": "wilderness_hut", "ele": "2659.4"}}
    r = Ricovero.da_element(el)

    assert r.tipo is TipoRicovero.BIVACCO
    assert r.quota_m == 2659


def test_etichette_pericolo():
    assert GradoPericolo.MARCATO.etichetta == "Marcato"
    assert int(GradoPericolo.MOLTO_FORTE) == 5

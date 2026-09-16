from __future__ import annotations

import pytest
import respx

from trekking_mcp.geo import anelli_di_geometria, contiene, nel_riquadro, riquadro_di
from trekking_mcp.models import Coord
from trekking_mcp.sources import eaws, elevation, nominatim, overpass
from trekking_mcp.sources.http import CLIENT

# Quadrato unitario con un buco quadrato al centro.
QUADRATO_CON_BUCO = {
    "type": "Polygon",
    "coordinates": [
        [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
    ],
}

GEOJSON_ZONE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"id": "IT-21-TO-05", "name": "Valli di Lanzo"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[7.0, 45.0], [7.5, 45.0], [7.5, 45.5], [7.0, 45.5], [7.0, 45.0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"id": "IT-21-TO-06", "name": "Val Susa"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[6.5, 45.0], [7.0, 45.0], [7.0, 45.5], [6.5, 45.5], [6.5, 45.0]]],
            },
        },
    ],
}


@pytest.fixture(autouse=True)
async def _pulisci(tmp_path, monkeypatch):
    """Cache HTTP e su disco isolate per ogni test."""
    from dataclasses import replace

    from trekking_mcp.config import CONFIG

    finta = replace(CONFIG, cache_dir=str(tmp_path))
    monkeypatch.setattr("trekking_mcp.sources.eaws.CONFIG", finta)
    await CLIENT.cache.svuota()
    eaws.INDICE.svuota()
    yield
    await CLIENT.cache.svuota()
    eaws.INDICE.svuota()


# --- geometria ---------------------------------------------------------------


def test_riquadro_e_prefiltro():
    anelli = anelli_di_geometria(QUADRATO_CON_BUCO)
    riquadro = riquadro_di([anelli[0][0]])

    assert riquadro == (0, 0, 10, 10)
    assert nel_riquadro(5, 5, riquadro)
    assert not nel_riquadro(5, 20, riquadro)


def test_punto_dentro_e_fuori():
    poligoni = anelli_di_geometria(QUADRATO_CON_BUCO)

    assert contiene(lat=2, lon=2, poligoni=poligoni)
    assert not contiene(lat=20, lon=20, poligoni=poligoni)


def test_il_buco_e_fuori():
    """Un punto nel buco e' dentro l'anello esterno ma fuori dal poligono."""
    poligoni = anelli_di_geometria(QUADRATO_CON_BUCO)

    assert not contiene(lat=5, lon=5, poligoni=poligoni)


def test_multipolygon():
    geometria = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]],
        ],
    }
    poligoni = anelli_di_geometria(geometria)

    assert len(poligoni) == 2
    assert contiene(lat=0.5, lon=0.5, poligoni=poligoni)
    assert contiene(lat=10.5, lon=10.5, poligoni=poligoni)
    assert not contiene(lat=5, lon=5, poligoni=poligoni)


def test_geometria_non_supportata_non_esplode():
    assert anelli_di_geometria({"type": "Point", "coordinates": [1, 2]}) == []
    assert anelli_di_geometria({}) == []


# --- zone valanghe -----------------------------------------------------------


async def test_lookup_zona_da_coordinate(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://regions.avalanches.org").respond(200, json=GEOJSON_ZONE)
    zona = await eaws.zona_da_coordinate(45.25, 7.25)

    assert zona.id_zona == "IT-21-TO-05"
    assert zona.nome == "Valli di Lanzo"


async def test_zone_confinanti_non_si_confondono(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://regions.avalanches.org").respond(200, json=GEOJSON_ZONE)
    ovest = await eaws.zona_da_coordinate(45.25, 6.75)

    assert ovest.id_zona == "IT-21-TO-06"


async def test_punto_fuori_suggerisce_le_zone_vicine(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://regions.avalanches.org").respond(200, json=GEOJSON_ZONE)
    from trekking_mcp.errors import NonTrovato

    with pytest.raises(NonTrovato) as exc:
        await eaws.zona_da_coordinate(41.9, 12.5)  # Roma: fuori dall'arco alpino

    messaggio = exc.value.messaggio_utente()
    assert "IT-21-TO-0" in messaggio


async def test_la_cache_su_disco_evita_il_riscarico(httpx2_mock: respx.Router):
    rotta = httpx2_mock.get(url__startswith="https://regions.avalanches.org").respond(200, json=GEOJSON_ZONE)
    await eaws.zona_da_coordinate(45.25, 7.25)
    chiamate_primo_giro = rotta.call_count

    eaws.INDICE.svuota()  # simula un riavvio del processo
    await eaws.zona_da_coordinate(45.25, 7.25)

    assert rotta.call_count == chiamate_primo_giro


async def test_un_territorio_mancante_non_blocca_gli_altri(httpx2_mock: respx.Router):
    """Meglio un indice parziale che nessun indice."""
    httpx2_mock.get(url__regex=r".*IT-21_micro.*").respond(200, json=GEOJSON_ZONE)
    httpx2_mock.get(url__startswith="https://regions.avalanches.org").respond(404)

    trovate = await eaws.INDICE.cerca(45.25, 7.25)

    assert [r.id_zona for r in trovate] == ["IT-21-TO-05"]


# --- profilo altimetrico -----------------------------------------------------


def test_campionamento_conserva_gli_estremi():
    punti = [Coord(lat=45.0 + i * 0.001, lon=7.0) for i in range(500)]
    campionati = elevation.campiona(punti, passo_m=200, massimo=50)

    assert len(campionati) <= 50
    assert campionati[0] == punti[0]
    assert campionati[-1] == punti[-1]


def test_campionamento_su_polilinea_corta():
    punti = [Coord(lat=45.0, lon=7.0), Coord(lat=45.1, lon=7.1)]
    assert elevation.campiona(punti) == punti


def test_dislivello_ignora_il_rumore():
    """Oscillazioni sotto soglia non devono gonfiare il dislivello.

    Senza filtro, 1000 micro-oscillazioni da 1 m darebbero centinaia di metri
    di salita inesistente. E' l'errore piu' comune nel calcolo dei profili.
    """
    piatto_rumoroso = [1000 + (1 if i % 2 else -1) for i in range(200)]
    salita, discesa = elevation._dislivelli(piatto_rumoroso)

    assert salita == 0
    assert discesa == 0


def test_dislivello_reale():
    quote = [1000, 1200, 1500, 1300, 1800]
    salita, discesa = elevation._dislivelli(quote)

    assert salita == 1000  # +200 +300 +500
    assert discesa == 200


async def test_profilo_completo(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://api.open-meteo.com/v1/elevation").respond(
        200, json={"elevation": [1000, 1400, 1800]}
    )
    punti = [Coord(lat=45.0, lon=7.0), Coord(lat=45.05, lon=7.0), Coord(lat=45.1, lon=7.0)]
    profilo = await elevation.profilo(punti, passo_m=1000)

    assert profilo.dislivello_positivo_m == 800
    assert profilo.quota_massima_m == 1800
    assert profilo.lunghezza_km > 0


# --- polilinea ---------------------------------------------------------------


def test_ricucitura_inverte_il_tratto_al_contrario():
    """Le way di una relation non sono ne' ordinate ne' orientate."""
    elemento = {
        "members": [
            {"type": "way", "geometry": [{"lat": 45.0, "lon": 7.0}, {"lat": 45.1, "lon": 7.1}]},
            # Questo tratto e' memorizzato al contrario.
            {"type": "way", "geometry": [{"lat": 45.3, "lon": 7.3}, {"lat": 45.1, "lon": 7.1}]},
        ]
    }
    percorso = overpass.polilinea(elemento)

    assert [round(c.lat, 1) for c in percorso] == [45.0, 45.1, 45.3]


def test_polilinea_scarta_i_membri_senza_geometria():
    elemento = {
        "members": [
            {"type": "node", "geometry": None},
            {"type": "way", "geometry": [{"lat": 45.0, "lon": 7.0}]},  # un solo punto
        ]
    }
    assert overpass.polilinea(elemento) == []


# --- geocoding ---------------------------------------------------------------


async def _no_attendi_nominatim() -> None:
    return None


def _nominatim_senza_cache(monkeypatch) -> None:
    """Identical Nominatim params must not reuse cached [] between fallback calls."""
    _orig_json = CLIENT.json

    async def _json_no_cache(*args, **kwargs):
        kwargs["ttl_s"] = None
        return await _orig_json(*args, **kwargs)

    monkeypatch.setattr(CLIENT, "json", _json_no_cache)


async def test_nominatim_con_coordinate_usa_viewbox_e_bounded(httpx2_mock: respx.Router, monkeypatch):
    import httpx

    monkeypatch.setattr(nominatim.LIMITATORE, "attendi", _no_attendi_nominatim)
    _nominatim_senza_cache(monkeypatch)
    rotta = httpx2_mock.get(url__startswith="https://nominatim.openstreetmap.org").mock(
        side_effect=[
            httpx.Response(
                200,
                json=[
                    {
                        "lat": "39.3",
                        "lon": "16.3",
                        "type": "peak",
                        "display_name": "Mucone CS",
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
        ]
    )
    esito = await nominatim.cerca("Mucrone", lat=45.57, lon=8.05, limite=5)

    params = dict(rotta.calls[0].request.url.params)
    assert params.get("bounded") == "1"
    assert "viewbox" in params
    assert esito[0].nome == "Monte Mucrone"


async def test_nominatim_fallback_senza_montagna_nella_viewbox(httpx2_mock: respx.Router, monkeypatch):
    import httpx

    monkeypatch.setattr(nominatim.LIMITATORE, "attendi", _no_attendi_nominatim)
    _nominatim_senza_cache(monkeypatch)
    rotta = httpx2_mock.get(url__startswith="https://nominatim.openstreetmap.org").mock(
        side_effect=[
            httpx.Response(200, json=[]),  # solo_montagna=True → vuoto
            httpx.Response(
                200,
                json=[
                    {
                        "lat": "45.57",
                        "lon": "8.05",
                        "type": "suburb",
                        "display_name": "Quartiere",
                        "osm_type": "node",
                        "osm_id": 2,
                    }
                ],
            ),
        ]
    )
    esito = await nominatim.cerca("Xyzzy", lat=45.57, lon=8.05)
    assert len(esito) == 1
    assert esito[0].tipo == "suburb"
    assert rotta.call_count == 2
    for call in rotta.calls:
        assert dict(call.request.url.params).get("bounded") == "1"


async def test_ricerca_localita_filtra_per_tipo(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://nominatim.openstreetmap.org").respond(
        200,
        json=[
            {
                "lat": "45.30",
                "lon": "7.12",
                "type": "alpine_hut",
                "display_name": "Rifugio Gastaldi",
                "osm_type": "node",
                "osm_id": 1,
                "extratags": {"ele": "2659"},
            },
            {"lat": "45.0", "lon": "7.0", "type": "restaurant", "display_name": "Pizzeria"},
        ],
    )
    esito = await nominatim.cerca("Rifugio Gastaldi")

    assert len(esito) == 1
    assert esito[0].quota_m == 2659


async def test_il_limitatore_serializza_le_richieste():
    """La usage policy di Nominatim impone una richiesta al secondo."""
    import time

    limitatore = nominatim.Limitatore(0.05)
    inizio = time.monotonic()
    for _ in range(3):
        await limitatore.attendi()

    assert time.monotonic() - inizio >= 0.09

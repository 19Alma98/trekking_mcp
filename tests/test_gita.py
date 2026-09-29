from datetime import UTC, datetime
from urllib.parse import parse_qs

import respx
from mcp import Client
from mcp.client.session import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult

from trekking_mcp.models import Bollettino, DifficoltaCAI, ProfiloAltimetrico
from trekking_mcp.server import crea_server
from trekking_mcp.tools.gita import ProfiloUscita, _segnali


def _risponde(difficolta_max: str = "E", artva: bool = True):
    chiamate: list[str] = []

    async def callback(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        chiamate.append(params.message)
        return ElicitResult(
            action="accept",
            content={"difficolta_max": difficolta_max, "attrezzatura_artva": artva, "persone": 2},
        )

    return callback, chiamate


def _ql_delle_chiamate(rotta: respx.Route) -> list[str]:
    query = []
    for chiamata in rotta.calls:
        corpo = chiamata.request.content
        if isinstance(corpo, bytes):
            corpo = corpo.decode()
        query.append(parse_qs(corpo)["data"][0])
    return query


RELATION_CON_CENTRO = {
    "elements": [
        {
            "type": "relation",
            "id": 42,
            "tags": {"ref": "D23A", "name": "prova"},
            "center": {"lat": 45.6356, "lon": 7.9363},
            "members": [],
        }
    ]
}


RELATION_SENZA_POSIZIONE = {
    "elements": [
        {
            "type": "relation",
            "id": 42,
            "tags": {"ref": "103", "name": "Sentiero di prova", "sac_scale": "alpine_hiking"},
            "members": [{"type": "node", "ref": 1, "role": ""}],
        }
    ]
}


async def test_di_default_non_scarica_la_geometria(httpx2_mock: respx.Router):
    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
    callback, _ = _risponde()

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42})

    assert not esito.is_error
    query = _ql_delle_chiamate(rotta)
    assert query and all("geom" not in ql for ql in query)


async def test_il_profilo_elicitato_arriva_nel_corpo_del_tool(httpx2_mock: respx.Router):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
    callback, chiamate = _risponde(difficolta_max="T")

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42})

    assert len(chiamate) == 1
    segnali = esito.structured_content["segnali"]
    difficolta = [s for s in segnali if s["categoria"] == "difficolta"]
    assert difficolta and difficolta[0]["severita"] == "critico"
    assert "EE" in difficolta[0]["messaggio"]


async def test_una_relation_senza_posizione_produce_un_segnale(httpx2_mock: respx.Router):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
    callback, _ = _risponde()

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42})

    risultato = esito.structured_content
    assert risultato["ricoveri_vicini"] == []
    assert risultato["meteo"] == []
    assert risultato["zona_valanghe"] is None

    dati = [s for s in risultato["segnali"] if s["categoria"] == "dati"]
    assert any("posizione utilizzabile" in s["messaggio"] for s in dati)


async def test_con_profilo_senza_geometria_lo_dichiara(httpx2_mock: respx.Router):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
    callback, _ = _risponde()

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42, "con_profilo": True})

    dati = [s for s in esito.structured_content["segnali"] if s["categoria"] == "dati"]
    assert any("geometria utilizzabile" in s["messaggio"] for s in dati)


async def test_il_rifiuto_dell_elicitation_ferma_la_chiamata(httpx2_mock: respx.Router):
    async def rifiuta(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with Client(crea_server(), elicitation_callback=rifiuta) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42})

    assert esito.is_error
    assert not httpx2_mock.calls


async def test_l_elicitation_funziona_con_chiavi_di_stato_condivise(httpx2_mock: respx.Router, risorse_con):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
    callback, chiamate = _risponde(difficolta_max="T")
    risorse = risorse_con(state_keys=("0" * 64,))

    async with Client(crea_server(risorse=risorse), elicitation_callback=callback) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42})

    assert not esito.is_error
    assert chiamate, "il resolver non ha chiesto niente al client"


GEOJSON_CH_7121 = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"id": "CH-7121", "name": "Bernina"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[9.8, 46.3], [10.1, 46.3], [10.1, 46.5], [9.8, 46.5], [9.8, 46.3]]],
            },
        }
    ],
}


async def test_una_zona_svizzera_non_viene_chiesta_ad_aineva(httpx2_mock: respx.Router, risorse_con, tmp_path):
    # Cache e territori isolati: altrimenti un indice EAWS gia' su disco salta
    # la GET e respx segna la rotta come non chiamata.
    risorse = risorse_con(cache_dir=str(tmp_path), eaws_territori=("CH",))
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
    httpx2_mock.get(url__startswith="https://regions.avalanches.org").respond(200, json=GEOJSON_CH_7121)
    slf = httpx2_mock.get(url__startswith="https://aws.slf.ch").respond(
        200,
        json={
            "bulletins": [
                {
                    "bulletinID": "ch-1",
                    "regions": [{"regionID": "CH-7121", "name": "Zona svizzera"}],
                    "dangerRatings": [{"mainValue": "considerable"}],
                }
            ]
        },
    )
    callback, _ = _risponde()

    async with Client(crea_server(risorse=risorse), elicitation_callback=callback) as client:
        esito = await client.call_tool(
            "valuta_gita", {"osm_relation_id": 42, "zona_valanghe": "CH-7121", "quota_riferimento_m": 2500}
        )

    assert not esito.is_error
    assert slf.called
    dati = esito.structured_content or {}
    assert dati["bollettino"]["fonte"] == "slf"
    assert any("WSL-SLF" in fonte for fonte in dati["fonti"]), "l'attribuzione deve essere quella del provider usato"
    zona = dati["zona_valanghe"]
    assert zona is not None, "zona passata come argomento deve comparire nel risultato"
    assert zona["id_zona"] == "CH-7121"
    assert zona["nome"] == "Bernina"
    assert zona["coord_richiesta"] is None, "senza punto di origine la coord non si inventa"
    assert any("EAWS" in fonte for fonte in dati["fonti"])


def test_un_bollettino_senza_grado_leggibile_produce_un_segnale():
    senza_gradi = Bollettino(
        id_bollettino="x",
        zona_id="IT-21-TEST",
        valido_da=datetime(2026, 1, 1, tzinfo=UTC),
        valido_fino=datetime(2026, 1, 2, tzinfo=UTC),
        valutazioni=[],
        fonte="aineva",
        fonte_url="https://esempio.test",
    )
    profilo = ProfiloUscita(difficolta_max="EE", attrezzatura_artva=False, persone=2)

    segnali = _segnali(DifficoltaCAI.E, profilo, senza_gradi, [])

    valanghe = [s for s in segnali if s.categoria == "valanghe"]
    assert valanghe, "un bollettino illeggibile deve dirlo"
    assert "non riporta un grado" in valanghe[0].messaggio
    assert valanghe[0].severita == "attenzione"


def test_lunghezza_km_assente_produce_un_segnale_dati():
    profilo = ProfiloUscita(difficolta_max="E", attrezzatura_artva=True, persone=2)

    segnali = _segnali(DifficoltaCAI.E, profilo, None, [], lunghezza_km=None)

    dati = [s for s in segnali if s.categoria == "dati" and "lunghezza" in s.messaggio.lower()]
    assert dati, "lunghezza OSM assente deve diventare un segnale"
    assert dati[0].severita == "info"


def test_con_profilo_altimetrico_non_segnala_lunghezza_assente():
    profilo = ProfiloUscita(difficolta_max="E", attrezzatura_artva=True, persone=2)
    profilo_alt = ProfiloAltimetrico(
        lunghezza_km=8.2,
        dislivello_positivo_m=600,
        dislivello_negativo_m=580,
    )

    segnali = _segnali(
        DifficoltaCAI.E,
        profilo,
        None,
        [],
        profilo_alt,
        lunghezza_km=None,
    )

    assert not any(s.categoria == "dati" and "lunghezza" in s.messaggio.lower() for s in segnali)


async def test_valuta_gita_estate_salta_valanghe_senza_chiamare_caaml(httpx2_mock: respx.Router, monkeypatch):
    import httpx

    httpx2_mock.post(url__startswith="https://overpass-api.de").mock(
        side_effect=[
            httpx.Response(200, json=RELATION_CON_CENTRO),
            httpx.Response(200, json={"elements": []}),
        ]
    )
    httpx2_mock.get(url__startswith="https://api.open-meteo.com/v1/forecast").respond(
        200,
        json={
            "hourly": {
                "time": ["2026-07-15T08:00"],
                "temperature_2m": [18.0],
                "precipitation": [0.0],
                "snowfall": [0.0],
                "cloud_cover": [10],
                "wind_speed_10m": [5.0],
                "wind_gusts_10m": [10.0],
                "wind_direction_10m": [180],
                "freezing_level_height": [4000],
            }
        },
    )
    callback, _ = _risponde()

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool(
            "valuta_gita",
            {"osm_relation_id": 42, "data": "2026-07-15"},
        )

    assert not esito.is_error
    body = esito.structured_content
    assert body["bollettino"] is None
    assert body["zona_valanghe"] is None
    assert any(s["categoria"] == "valanghe" and "estiva" in s["messaggio"].lower() for s in body["segnali"])
    chiamate_valanghe = [
        str(c.request.url)
        for c in httpx2_mock.calls
        if "aineva" in str(c.request.url)
        or "regions.avalanches.org" in str(c.request.url)
        or "slf.ch" in str(c.request.url)
    ]
    assert chiamate_valanghe == []


async def test_valuta_gita_ricoveri_overpass_giu_non_affonda(httpx2_mock: respx.Router, monkeypatch):
    from trekking_mcp.errors import FonteNonDisponibile
    from trekking_mcp.models import Coord, DifficoltaCAI, Sentiero

    async def _sentiero(risorse, osm_id):
        return Sentiero(
            osm_relation_id=osm_id,
            ref="D23A",
            nome=None,
            da=None,
            a=None,
            operatore=None,
            rete=None,
            sac_scale=None,
            difficolta_cai=DifficoltaCAI.SCONOSCIUTA,
            visibilita=None,
            lunghezza_km=None,
            centro=Coord(lat=45.63, lon=7.93),
            osm_url=f"https://www.openstreetmap.org/relation/{osm_id}",
        )

    async def _boom(*args, **kwargs):
        raise FonteNonDisponibile("overpass", "HTTP 504")

    async def _meteo_vuoto(*args, **kwargs):
        return []

    monkeypatch.setattr("trekking_mcp.tools.gita.overpass.leggi_sentiero", _sentiero)
    monkeypatch.setattr("trekking_mcp.tools.gita.overpass.cerca_ricoveri", _boom)
    monkeypatch.setattr("trekking_mcp.tools.gita.meteo.previsione", _meteo_vuoto)
    callback, _ = _risponde()

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool(
            "valuta_gita",
            {"osm_relation_id": 42, "data": "2026-07-15"},
        )

    assert not esito.is_error
    body = esito.structured_content
    assert body["ricoveri_vicini"] == []
    dati = [s for s in body["segnali"] if s["categoria"] == "dati"]
    assert any(
        ("rifugi" in s["messaggio"].lower() or "ricoveri" in s["messaggio"].lower())
        and ("overpass" in s["messaggio"].lower() or "non" in s["messaggio"].lower())
        for s in dati
    )


def test_difficolta_sconosciuta_cita_la_visibilita_se_c_e():
    profilo = ProfiloUscita(difficolta_max="E", attrezzatura_artva=True, persone=2)

    segnali = _segnali(
        DifficoltaCAI.SCONOSCIUTA,
        profilo,
        None,
        [],
        lunghezza_km=5.0,
        visibilita="bad",
    )

    difficolta = [s for s in segnali if s.categoria == "difficolta"]
    assert difficolta
    assert "visibilit" in difficolta[0].messaggio.lower()
    assert "bad" in difficolta[0].messaggio

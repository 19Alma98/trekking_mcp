from datetime import UTC, datetime
from urllib.parse import parse_qs

import respx
from mcp import Client
from mcp.client.session import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult

from trekking_mcp.models import Bollettino, DifficoltaCAI
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


async def test_una_zona_svizzera_non_viene_chiesta_ad_aineva(httpx2_mock: respx.Router):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
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

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool(
            "valuta_gita", {"osm_relation_id": 42, "zona_valanghe": "CH-7121", "quota_riferimento_m": 2500}
        )

    assert not esito.is_error
    assert slf.called
    dati = esito.structured_content or {}
    assert dati["bollettino"]["fonte"] == "slf"
    assert any("WSL-SLF" in fonte for fonte in dati["fonti"]), "l'attribuzione deve essere quella del provider usato"


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

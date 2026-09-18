"""`valuta_gita` end-to-end, con un client MCP in-process.

E' l'unico punto in cui si vede il giro completo: il client risponde
all'elicitation, il valore iniettato arriva nel corpo del tool e i buchi di
copertura escono come segnali invece che come campi vuoti.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import pytest
import respx
from mcp import Client
from mcp.client.session import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult

from trekking_mcp.server import crea_server
from trekking_mcp.sources.http import CLIENT


@pytest.fixture(autouse=True)
async def _svuota_cache():
    await CLIENT.cache.svuota()
    yield
    await CLIENT.cache.svuota()


def _risponde(difficolta_max: str = "E", artva: bool = True):
    """Client che accetta l'elicitation, come farebbe un utente reale."""
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
    """`out geom` e' la query che fa cadere Overpass: non deve partire da sola."""
    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json=RELATION_SENZA_POSIZIONE)
    callback, _ = _risponde()

    async with Client(crea_server(), elicitation_callback=callback) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42})

    assert not esito.is_error
    query = _ql_delle_chiamate(rotta)
    assert query and all("geom" not in ql for ql in query)


async def test_il_profilo_elicitato_arriva_nel_corpo_del_tool(httpx2_mock: respx.Router):
    """Il gruppo dichiara T, il sentiero e' EE: il segnale critico prova il giro completo."""
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
    """Senza centro non si raccolgono rifugi, zona e meteo.

    Tre liste vuote si leggono come "non c'e' niente nei dintorni", che e' il
    contrario di quello che e' successo. Il buco va dichiarato.
    """
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
    """Rifiutare e' un esito legittimo: il tool non deve proseguire con un default.

    Il resolver gira *prima* del corpo, quindi il rifiuto costa zero richieste:
    nessuna fonte esterna viene toccata per una chiamata che l'utente ha fermato.
    """

    async def rifiuta(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
        return ElicitResult(action="decline")

    async with Client(crea_server(), elicitation_callback=rifiuta) as client:
        esito = await client.call_tool("valuta_gita", {"osm_relation_id": 42})

    assert esito.is_error
    assert not httpx2_mock.calls

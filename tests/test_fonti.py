from __future__ import annotations

from dataclasses import replace

import pytest
import respx

from trekking_mcp.config import CONFIG
from trekking_mcp.errors import FonteNonDisponibile, NonTrovato
from trekking_mcp.models import GradoPericolo
from trekking_mcp.sources import caaml, overpass
from trekking_mcp.sources.http import CLIENT

CAAML_ESEMPIO = {
    "bulletins": [
        {
            "bulletinID": "test-001",
            "regions": [{"regionID": "IT-21-TO-05", "name": "Valli di Lanzo"}],
            "validTime": {"startTime": "2026-02-01T17:00:00Z", "endTime": "2026-02-02T17:00:00Z"},
            "dangerRatings": [
                {"mainValue": "considerable", "elevation": {"lowerBound": "2200"}},
                {"mainValue": "moderate", "elevation": {"upperBound": "2200"}},
            ],
            "avalancheProblems": [
                {
                    "problemType": "wind_slab",
                    "aspects": ["n", "ne", "e"],
                    "elevation": {"lowerBound": "2000"},
                }
            ],
            "highlights": "Neve ventata sui pendii settentrionali.",
        }
    ]
}


@pytest.fixture(autouse=True)
async def _svuota_cache():
    """La cache e' per-processo: senza reset i test si contaminano a vicenda."""
    await CLIENT.cache.svuota()
    yield
    await CLIENT.cache.svuota()


def test_query_sentieri_filtra_su_ref_non_su_name():
    """Il numero del sentiero sta in `ref`: cercarlo in `name` e' l'errore classico."""
    ql = overpass.query_sentieri(sud=45.0, ovest=7.0, nord=45.5, est=7.5, ref="103")

    assert '["ref"="103"]' in ql
    assert '["route"="hiking"]' in ql
    assert "name" not in ql
    assert "45.0,7.0,45.5,7.5" in ql


def test_query_escapa_gli_apici():
    """Overpass non ha query parametrizzate: l'escaping e' a carico nostro."""
    ql = overpass.query_sentieri(sud=45.0, ovest=7.0, nord=45.5, est=7.5, ref='10"];out;//')

    assert '10\\"' in ql
    assert ql.count("out tags center;") == 1


async def test_cerca_sentieri_parsa_la_risposta(httpx2_mock: respx.Router):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(
        200,
        json={
            "elements": [
                {"type": "relation", "id": 1, "tags": {"ref": "103", "sac_scale": "mountain_hiking"}},
                {"type": "node", "id": 2, "tags": {}},  # va scartato
            ]
        },
    )
    esito = await overpass.cerca_sentieri(sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert len(esito) == 1
    assert esito[0].ref == "103"


async def test_caaml_normalizza_i_gradi(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://bollettini.aineva.it").respond(200, json=CAAML_ESEMPIO)
    b = await caaml.leggi_bollettino(zona_id="IT-21-TO-05")

    assert b.zona_nome == "Valli di Lanzo"
    assert b.grado_massimo is GradoPericolo.MARCATO
    assert len(b.valutazioni) == 2
    assert b.valutazioni[0].quota_limite_m == 2200
    assert b.problemi[0].esposizioni == ["N", "NE", "E"]
    assert b.avvertenza  # l'avvertenza non deve mai essere vuota


async def test_zona_inesistente_suggerisce_le_valide(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://bollettini.aineva.it").respond(200, json=CAAML_ESEMPIO)
    with pytest.raises(NonTrovato) as exc:
        await caaml.leggi_bollettino(zona_id="IT-99-XX-99")

    assert "IT-21-TO-05" in exc.value.messaggio_utente()


async def test_retry_e_poi_fonte_non_disponibile(httpx2_mock: respx.Router, monkeypatch):
    """Dopo i retry, l'errore httpx2 grezzo non deve uscire dal layer fonti."""
    # Config e' frozen di proposito: si sostituisce l'oggetto, non un campo.
    monkeypatch.setattr("trekking_mcp.sources.http.CONFIG", replace(CONFIG, max_retry=2))
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(429)
    with pytest.raises(FonteNonDisponibile):
        await overpass.cerca_sentieri(sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert rotta.call_count == 2


async def test_la_cache_evita_la_seconda_chiamata(httpx2_mock: respx.Router):
    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json={"elements": []})
    for _ in range(3):
        await overpass.cerca_sentieri(sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert rotta.call_count == 1


async def _no_sleep(_: float) -> None:
    return None

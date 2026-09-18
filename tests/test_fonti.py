from __future__ import annotations

import asyncio
import json
import re

import pytest
import respx

from trekking_mcp.errors import FonteNonDisponibile, NonTrovato
from trekking_mcp.models import GradoPericolo
from trekking_mcp.sources import caaml, meteo, overpass

_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

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


def test_query_sentieri_filtra_su_ref_non_su_name(config):
    """Il numero del sentiero sta in `ref`: cercarlo in `name` e' l'errore classico."""
    ql = overpass.query_sentieri(config, sud=45.0, ovest=7.0, nord=45.5, est=7.5, ref="103")

    assert '["ref"="103"]' in ql
    assert '["route"="hiking"]' in ql
    assert "name" not in ql
    assert "45.0,7.0,45.5,7.5" in ql


def test_query_escapa_gli_apici(config):
    """Overpass non ha query parametrizzate: l'escaping e' a carico nostro."""
    ql = overpass.query_sentieri(config, sud=45.0, ovest=7.0, nord=45.5, est=7.5, ref='10"];out;//')

    assert '10\\"' in ql
    assert ql.count("out tags center;") == 1


def test_query_sentieri_con_testo_usa_regex_su_tag_testuali(config):
    ql = overpass.query_sentieri(config, sud=45.0, ovest=7.0, nord=45.5, est=7.5, testo="Mucrone")
    assert '[~"^(name|from|to|description)$"~"Mucrone",i]' in ql
    assert "out tags center;" in ql


def test_query_sentieri_testo_escapa_metacaratteri_regex(config):
    ql = overpass.query_sentieri(config, sud=45.0, ovest=7.0, nord=45.5, est=7.5, testo="C.A.I. (Nord)")
    assert '["route"="hiking"]' in ql
    assert ql.count("out tags center;") == 1
    assert "\\(" in ql  # parentesi escapata da re.escape


def test_pattern_operatore_cai_matcha_punti():
    assert overpass.pattern_operatore("CAI") == r"C\.?A\.?I\.?"
    assert overpass.pattern_operatore("cai") == r"C\.?A\.?I\.?"
    assert overpass.pattern_operatore("CAI Torino") == "CAI Torino"


def test_query_sentieri_operatore_cai_non_e_letterale(config):
    pattern = overpass.pattern_operatore("CAI")
    ql = overpass.query_sentieri(config, sud=45.0, ovest=7.0, nord=45.5, est=7.5, operatore="CAI")
    assert f'["operator"~"{overpass._escape(pattern)}",i]' in ql
    assert '["operator"~"CAI",i]' not in ql


async def test_cerca_sentieri_parsa_la_risposta(httpx2_mock: respx.Router, risorse):
    httpx2_mock.post(url__startswith="https://overpass-api.de").respond(
        200,
        json={
            "elements": [
                {"type": "relation", "id": 1, "tags": {"ref": "103", "sac_scale": "mountain_hiking"}},
                {"type": "node", "id": 2, "tags": {}},  # va scartato
            ]
        },
    )
    esito = await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert len(esito) == 1
    assert esito[0].ref == "103"


async def test_caaml_normalizza_i_gradi(httpx2_mock: respx.Router, risorse):
    httpx2_mock.get(url__startswith="https://bollettini.aineva.it").respond(200, json=CAAML_ESEMPIO)
    b = await caaml.leggi_bollettino(risorse, zona_id="IT-21-TO-05")

    assert b.zona_nome == "Valli di Lanzo"
    assert b.grado_massimo is GradoPericolo.MARCATO
    assert len(b.valutazioni) == 2
    assert b.valutazioni[0].quota_limite_m == 2200
    assert b.problemi[0].esposizioni == ["N", "NE", "E"]
    assert b.avvertenza  # l'avvertenza non deve mai essere vuota


def test_gli_istanti_del_bollettino_sono_sempre_confrontabili():
    """Naive e aware nello stesso campo farebbero esplodere ogni confronto."""
    con_offset = caaml._data("2026-02-01T17:00:00Z")
    senza_offset = caaml._data("2026-02-01T17:00:00")
    mancante = caaml._data(None)

    assert con_offset.tzinfo is not None
    assert senza_offset.tzinfo is not None, "istante senza offset lasciato naive"
    assert mancante.tzinfo is not None, "fallback naive accanto a istanti aware"

    # Il punto vero: questi confronti non devono sollevare TypeError.
    assert con_offset == senza_offset
    assert con_offset < mancante


async def test_un_bollettino_senza_validtime_resta_utilizzabile(httpx2_mock: respx.Router, risorse):
    """Manca `validTime`: il modello si costruisce e la validita' si confronta."""
    senza_validita = {
        "bulletins": [
            {
                "bulletinID": "test-002",
                "regions": [{"regionID": "IT-21-TO-05", "name": "Valli di Lanzo"}],
                "dangerRatings": [{"mainValue": "moderate"}],
            }
        ]
    }
    httpx2_mock.get(url__startswith="https://bollettini.aineva.it").respond(200, json=senza_validita)

    b = await caaml.leggi_bollettino(risorse, zona_id="IT-21-TO-05")

    assert b.valido_da <= b.valido_fino


async def test_zona_inesistente_suggerisce_le_valide(httpx2_mock: respx.Router, risorse):
    httpx2_mock.get(url__startswith="https://bollettini.aineva.it").respond(200, json=CAAML_ESEMPIO)
    with pytest.raises(NonTrovato) as exc:
        await caaml.leggi_bollettino(risorse, zona_id="IT-99-XX-99")

    assert "IT-21-TO-05" in exc.value.messaggio_utente()


async def test_overpass_usa_al_massimo_due_tentativi(
    httpx2_mock: respx.Router, monkeypatch, risorse_con, config, risorse
):
    """Overpass: max_retry effettivo 2 (1 retry), indipendente da config.max_retry=3."""
    risorse = risorse_con(max_retry=3)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(504)
    with pytest.raises(FonteNonDisponibile):
        await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert rotta.call_count == 2


async def test_retry_e_poi_fonte_non_disponibile(httpx2_mock: respx.Router, monkeypatch, risorse_con, risorse):
    """Dopo i retry, l'errore httpx2 grezzo non deve uscire dal layer fonti."""
    # Config e' frozen di proposito: si costruisce l'oggetto, non si muta.
    risorse = risorse_con(max_retry=2)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(429)
    with pytest.raises(FonteNonDisponibile):
        await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert rotta.call_count == 2


async def test_retry_rispetta_retry_after(httpx2_mock: respx.Router, monkeypatch, risorse_con, risorse):
    """Su 429 con Retry-After, l'attesa deve essere almeno quel valore (più jitter)."""
    attese: list[float] = []

    async def _registra(secondi: float) -> None:
        attese.append(secondi)

    monkeypatch.setattr("asyncio.sleep", _registra)
    monkeypatch.setattr("trekking_mcp.sources.http.random.uniform", lambda _a, _b: 0.0)

    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de")
    rotta.side_effect = [
        respx.MockResponse(429, headers={"Retry-After": "7"}),
        respx.MockResponse(200, json={"elements": []}),
    ]

    await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert rotta.call_count == 2
    assert attese == [7.0]


async def test_un_retry_after_enorme_non_blocca_la_chiamata(httpx2_mock: respx.Router, monkeypatch, risorse):
    """Oltre il tetto non si aspetta: si fallisce subito dicendo quanto chiede la fonte.

    Restare in sleep un'ora terrebbe il semaforo di Overpass e con esso ogni
    altra query del processo. Meglio un errore leggibile, subito.
    """
    attese: list[float] = []

    async def _registra(secondi: float) -> None:
        attese.append(secondi)

    monkeypatch.setattr("asyncio.sleep", _registra)

    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(429, headers={"Retry-After": "3600"})

    with pytest.raises(FonteNonDisponibile) as errore:
        await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert attese == [], "ha atteso nonostante il Retry-After sopra il tetto"
    assert rotta.call_count == 1, "ha ritentato invece di fermarsi"
    assert "3600" in str(errore.value)
    # Il messaggio deve restare azionabile per chi legge dall'altra parte.
    assert "riprovare" in errore.value.messaggio_utente()


async def test_un_retry_after_sotto_il_tetto_viene_rispettato(httpx2_mock: respx.Router, monkeypatch, risorse):
    """Il tetto non deve rompere il caso normale: 30s < 120s si aspettano."""
    attese: list[float] = []

    async def _registra(secondi: float) -> None:
        attese.append(secondi)

    monkeypatch.setattr("asyncio.sleep", _registra)
    monkeypatch.setattr("trekking_mcp.sources.http.random.uniform", lambda _a, _b: 0.0)

    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de")
    rotta.side_effect = [
        respx.MockResponse(429, headers={"Retry-After": "30"}),
        respx.MockResponse(200, json={"elements": []}),
    ]

    await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert attese == [30.0]


async def test_retry_aggiunge_jitter_senza_retry_after(httpx2_mock: respx.Router, monkeypatch, risorse_con, risorse):
    """Senza Retry-After: backoff 2**n più jitter uniforme in [0, base)."""
    attese: list[float] = []

    async def _registra(secondi: float) -> None:
        attese.append(secondi)

    monkeypatch.setattr("asyncio.sleep", _registra)
    monkeypatch.setattr("trekking_mcp.sources.http.random.uniform", lambda _a, _b: 0.25)

    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de")
    rotta.side_effect = [
        respx.MockResponse(504),
        respx.MockResponse(200, json={"elements": []}),
    ]

    await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert rotta.call_count == 2
    assert attese == [1.25]  # base 2**0=1 + jitter 0.25


async def test_overpass_serializza_le_query_parallele(monkeypatch, risorse):
    """Il semaforo Overpass impedisce fan-out parallelo verso l'istanza."""
    in_volo = 0
    picco = 0

    async def _fake_json(*_a, **_k):
        nonlocal in_volo, picco
        in_volo += 1
        picco = max(picco, in_volo)
        await asyncio.sleep(0.05)
        in_volo -= 1
        return {"elements": []}

    monkeypatch.setattr(risorse.http, "json", _fake_json)

    await asyncio.gather(
        overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5),
        overpass.cerca_sentieri(risorse, sud=46.0, ovest=8.0, nord=46.5, est=8.5),
    )

    assert picco == 1


async def test_la_cache_evita_la_seconda_chiamata(httpx2_mock: respx.Router, risorse):
    rotta = httpx2_mock.post(url__startswith="https://overpass-api.de").respond(200, json={"elements": []})
    for _ in range(3):
        await overpass.cerca_sentieri(risorse, sud=45.0, ovest=7.0, nord=45.5, est=7.5)

    assert rotta.call_count == 1


async def test_meteo_serializza_istante_in_rfc3339(httpx2_mock: respx.Router, risorse):
    """Open-Meteo dà `2026-09-17T00:00` (naive); lo schema MCP vuole date-time con offset."""
    httpx2_mock.get(url__startswith="https://api.open-meteo.com/v1/forecast").respond(
        200,
        json={
            "hourly": {
                "time": ["2026-09-17T00:00", "2026-09-17T01:00"],
                "temperature_2m": [5.0, 4.5],
                "precipitation": [0.0, 0.0],
                "snowfall": [0.0, 0.0],
                "cloud_cover": [10, 20],
                "wind_speed_10m": [10.0, 12.0],
                "wind_gusts_10m": [20.0, 22.0],
                "wind_direction_10m": [180, 190],
                "freezing_level_height": [3000, 2900],
            }
        },
    )
    esito = await meteo.previsione(risorse, lat=45.07, lon=7.68, quota_m=2000, data="2026-09-17", ore_max=2)

    assert len(esito) == 2
    payload = json.loads(esito[0].model_dump_json())
    assert _RFC3339.match(payload["istante"]), payload["istante"]
    assert payload["istante"].endswith("+02:00")


async def _no_sleep(_: float) -> None:
    return None

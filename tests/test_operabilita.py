from __future__ import annotations

import json

import httpx
import pytest
import respx
from mcp import Client
from mcp.types import PromptReference, ResourceTemplateReference

from trekking_mcp import completamenti
from trekking_mcp.__main__ import impostazioni_sicurezza, main
from trekking_mcp.errors import FonteNonDisponibile
from trekking_mcp.geo import Riquadro
from trekking_mcp.metriche import METRICHE, Metriche, _percentile
from trekking_mcp.server import crea_server
from trekking_mcp.sources import eaws
from trekking_mcp.sources.http import CLIENT


@pytest.fixture(autouse=True)
async def _stato_pulito():
    await CLIENT.cache.svuota()
    METRICHE.azzera()
    yield
    await CLIENT.cache.svuota()
    METRICHE.azzera()


async def _no_sleep(_: float) -> None:
    return None


def test_bind_locale_lascia_il_default_dell_sdk():
    assert impostazioni_sicurezza("127.0.0.1", [], []) is None
    assert impostazioni_sicurezza("localhost", [], []) is None


def test_bind_pubblico_senza_allow_host_e_rifiutato():
    with pytest.raises(ValueError, match="allow-host"):
        impostazioni_sicurezza("0.0.0.0", [], [])


def test_allow_host_attiva_la_protezione():
    esito = impostazioni_sicurezza("0.0.0.0", ["trekking.example.org:*"], ["https://app.example.org"])
    assert esito is not None
    assert esito.enable_dns_rebinding_protection
    assert esito.allowed_hosts == ["trekking.example.org:*"]
    assert esito.allowed_origins == ["https://app.example.org"]


def test_main_non_avvia_un_server_pubblico_non_protetto():
    with pytest.raises(SystemExit) as esito:
        main(["--transport", "http", "--host", "0.0.0.0"])
    assert esito.value.code == 2


def test_percentile_per_rango():
    valori = [float(n) for n in range(1, 101)]
    assert _percentile(valori, 0.50) == 50
    assert _percentile(valori, 0.95) == 95
    assert _percentile([], 0.5) == 0.0
    assert _percentile([7.0], 0.95) == 7.0


def test_hit_rate_none_se_la_fonte_non_usa_la_cache():
    m = Metriche()
    m.chiamata("eaws-regions", 12.0)
    assert m.istantanea().fonti["eaws-regions"].cache_hit_rate is None


def test_conteggi_per_fonte():
    m = Metriche()
    m.cache_miss("overpass")
    m.chiamata("overpass", 100.0)
    m.stato_http("overpass", 429)
    m.retry("overpass")
    m.chiamata("overpass", 300.0)
    m.stato_http("overpass", 200)
    m.cache_hit("overpass")

    fonte = m.istantanea().fonti["overpass"]
    assert fonte.chiamate == 2
    assert fonte.rate_limit == 1
    assert fonte.server_error == 0
    assert fonte.retry == 1
    assert fonte.cache_hit_rate == 0.5
    assert fonte.latenza.max_ms == 300


def test_la_finestra_delle_latenze_non_cresce():
    m = Metriche()
    for n in range(1000):
        m.chiamata("meteo", float(n))
    assert len(m._fonti["meteo"].latenze_ms) == 256
    assert m.istantanea().fonti["meteo"].chiamate == 1000


async def test_il_client_http_registra_429_retry_e_cache(httpx2_mock: respx.Router, monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    httpx2_mock.get(url__startswith="https://esempio.test").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    await CLIENT.json("GET", "https://esempio.test/x", fonte="prova", ttl_s=60)
    await CLIENT.json("GET", "https://esempio.test/x", fonte="prova", ttl_s=60)  # dalla cache

    fonte = METRICHE.istantanea().fonti["prova"]
    assert fonte.chiamate == 2  # il 429 e' comunque una richiesta uscita
    assert fonte.rate_limit == 1
    assert fonte.retry == 1
    assert fonte.errori == 0
    assert fonte.cache_hit == 1
    assert fonte.cache_miss == 1


async def test_un_4xx_definitivo_conta_come_errore_e_non_come_retry(httpx2_mock: respx.Router):
    httpx2_mock.get(url__startswith="https://esempio.test").respond(404)

    with pytest.raises(FonteNonDisponibile):
        await CLIENT.json("GET", "https://esempio.test/x", fonte="prova", ttl_s=None)

    fonte = METRICHE.istantanea().fonti["prova"]
    assert fonte.errori == 1
    assert fonte.retry == 0


async def test_la_resource_metriche_e_leggibile():
    METRICHE.chiamata("overpass", 42.0)
    async with Client(crea_server()) as client:
        esito = await client.read_resource("metriche://fonti")
    dati = json.loads(esito.contents[0].text or "{}")
    assert dati["fonti"]["overpass"]["chiamate"] == 1
    assert "nota" in dati


def _micro_regione(id_zona: str) -> eaws.MicroRegione:
    riquadro: Riquadro = (0.0, 0.0, 1.0, 1.0)
    return eaws.MicroRegione(id_zona=id_zona, nome=id_zona, riquadro=riquadro, poligoni=[])


@pytest.fixture
def indice_finto(monkeypatch):
    indice = eaws.IndiceRegioni()
    for id_zona in ("IT-21-AO-01", "IT-21-AO-02", "IT-25-SO-01", "CH-7121"):
        indice._regioni.append(_micro_regione(id_zona))
    monkeypatch.setattr(eaws, "INDICE", indice)
    return indice


def test_zone_note_filtrate_per_provider(indice_finto):
    assert completamenti.zone_note("aineva") == ["IT-21-AO-01", "IT-21-AO-02", "IT-25-SO-01"]
    assert completamenti.zone_note("slf") == ["CH-7121"]
    assert len(completamenti.zone_note()) == 4


def test_zone_note_non_scarica_nulla(httpx2_mock: respx.Router, monkeypatch):
    monkeypatch.setattr(eaws, "INDICE", eaws.IndiceRegioni())
    assert completamenti.zone_note() == []
    assert not httpx2_mock.calls


async def test_completa_zona_id_della_resource_template(indice_finto):
    async with Client(crea_server()) as client:
        esito = await client.complete(
            ResourceTemplateReference(uri="bollettino://{provider}/{zona_id}"),
            {"name": "zona_id", "value": "IT-21"},
        )
    assert esito.completion.values == ["IT-21-AO-01", "IT-21-AO-02"]
    assert esito.completion.total == 2


async def test_il_provider_gia_scelto_restringe_le_zone(indice_finto):
    async with Client(crea_server()) as client:
        esito = await client.complete(
            ResourceTemplateReference(uri="bollettino://{provider}/{zona_id}"),
            {"name": "zona_id", "value": ""},
            context_arguments={"provider": "slf"},
        )
    assert esito.completion.values == ["CH-7121"]


async def test_completa_il_provider():
    async with Client(crea_server()) as client:
        esito = await client.complete(
            ResourceTemplateReference(uri="bollettino://{provider}/{zona_id}"),
            {"name": "provider", "value": "a"},
        )
    assert esito.completion.values == ["aineva"]


async def test_completa_l_argomento_del_prompt(indice_finto):
    async with Client(crea_server()) as client:
        esito = await client.complete(
            PromptReference(name="spiega_bollettino"),
            {"name": "zona_id", "value": "CH"},
        )
    assert esito.completion.values == ["CH-7121"]


async def test_nessun_completamento_per_riferimenti_sconosciuti():
    async with Client(crea_server()) as client:
        esito = await client.complete(
            PromptReference(name="prepara_gita"),
            {"name": "sentiero", "value": "1"},
        )
    assert esito.completion.values == []

import json

import pytest
import respx
from mcp import Client

from trekking_mcp.config import Config
from trekking_mcp.constants import TERRITORI_DEFAULT
from trekking_mcp.errors import NonTrovato
from trekking_mcp.server import crea_server
from trekking_mcp.sources import caaml


def test_ogni_provider_ha_un_prefisso_di_zona():
    for nome, dati in caaml.PROVIDER.items():
        assert dati["prefisso_zone"], f"{nome}: senza prefisso le sue zone non si autocompletano mai"


def test_i_territori_di_default_coprono_tutti_i_provider():
    territori = set(TERRITORI_DEFAULT)
    for nome, dati in caaml.PROVIDER.items():
        prefisso = dati["prefisso_zone"].rstrip("-")
        assert any(t == prefisso or t.startswith(f"{prefisso}-") for t in territori), (
            f"{nome}: nessun territorio in TERRITORI_DEFAULT produce zone {dati['prefisso_zone']}*"
        )


@pytest.mark.parametrize(
    ("zona", "atteso"),
    [
        ("IT-21-AO-01", "aineva"),
        ("CH-7121", "slf"),
    ],
)
def test_provider_dedotto_dalla_zona(zona, atteso):
    assert caaml.provider_per_zona(zona) == atteso


def test_un_prefisso_sconosciuto_non_ricade_su_aineva():
    with pytest.raises(NonTrovato) as exc:
        caaml.provider_per_zona("XX-1")
    assert exc.value.chiave == "XX-1"
    assert any("IT-" in a for a in exc.value.alternative)
    assert any("CH-" in a for a in exc.value.alternative)


async def test_leggi_bollettino_non_chiama_aineva_per_un_prefisso_sconosciuto(risorse):
    with pytest.raises(NonTrovato, match="XX-1"):
        await caaml.leggi_bollettino(risorse, zona_id="XX-1")


async def test_una_zona_svizzera_va_chiesta_a_slf(httpx2_mock: respx.Router, risorse):
    slf = httpx2_mock.get(url__startswith="https://aws.slf.ch").respond(
        200,
        json={
            "bulletins": [
                {
                    "bulletinID": "ch-1",
                    "regions": [{"regionID": "CH-7121", "name": "Zona svizzera"}],
                    "dangerRatings": [{"mainValue": "moderate"}],
                }
            ]
        },
    )
    bollettino = await caaml.leggi_bollettino(risorse, zona_id="CH-7121")

    assert bollettino.fonte == "slf"
    assert slf.called


async def test_un_provider_esplicito_resta_quello_chiesto(httpx2_mock: respx.Router, risorse):
    httpx2_mock.get(url__startswith="https://bollettini.aineva.it").respond(200, json={"bulletins": []})

    with pytest.raises(NonTrovato):
        await caaml.leggi_bollettino(risorse, zona_id="CH-7121", provider="aineva")


def test_i_territori_si_configurano():
    cfg = Config()
    assert "CH" in cfg.eaws_territori

    import os

    os.environ["EAWS_TERRITORI"] = "IT-21, IT-23"
    try:
        assert Config().eaws_territori == ("IT-21", "IT-23")
    finally:
        del os.environ["EAWS_TERRITORI"]


async def test_la_resource_delle_metriche_gira_sull_event_loop(risorse):
    mcp = crea_server(risorse=risorse)
    risorse.metriche.chiamata("overpass", 10.0)

    async with Client(mcp) as client:
        esito = await client.read_resource("metriche://fonti")

    assert json.loads(esito.contents[0].text or "{}")["fonti"]["overpass"]["chiamate"] == 1

    risorsa = await mcp.read_resource("metriche://fonti")
    assert risorsa is not None

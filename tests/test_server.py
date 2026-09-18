from __future__ import annotations

import pytest

from trekking_mcp.server import crea_server

TOOL_ATTESI = {
    "cerca_sentieri",
    "dettaglio_sentiero",
    "cerca_ricoveri",
    "sentieri_verso_localita",
    "zona_valanghe_da_coordinate",
    "cerca_localita",
    "profilo_altimetrico",
    "bollettino_valanghe",
    "meteo_quota",
    "valuta_gita",
}


@pytest.fixture
def mcp():
    return crea_server()


async def test_tool_registrati(mcp):
    nomi = {t.name for t in await mcp.list_tools()}
    assert nomi == TOOL_ATTESI


async def test_ogni_tool_ha_descrizione_e_output_schema(mcp):
    for t in await mcp.list_tools():
        assert t.description and len(t.description) > 40, f"{t.name}: descrizione assente o troppo scarna"
        assert t.output_schema is not None, f"{t.name}: manca outputSchema"


async def test_parametro_elicitato_non_e_nello_schema(mcp):
    valuta = next(t for t in await mcp.list_tools() if t.name == "valuta_gita")
    argomenti = set(valuta.input_schema.get("properties", {}))

    assert "profilo" not in argomenti
    assert "osm_relation_id" in argomenti


async def test_tool_marcati_read_only(mcp):
    for t in await mcp.list_tools():
        assert t.annotations is not None, f"{t.name}: annotations assenti"
        assert t.annotations.read_only_hint is True, f"{t.name}: non marcato readOnly"


async def test_resource_e_template(mcp):
    uri = {str(r.uri) for r in await mcp.list_resources()}
    template = {r.uri_template for r in await mcp.list_resource_templates()}

    assert "scala://pericolo-valanghe" in uri
    assert "scala://difficolta-escursionistica" in uri
    assert "metriche://fonti" in uri
    assert "bollettino://{provider}/{zona_id}" in template


async def test_valuta_gita_non_calcola_il_profilo_per_default(mcp):
    valuta = next(t for t in await mcp.list_tools() if t.name == "valuta_gita")
    con_profilo = valuta.input_schema["properties"]["con_profilo"]

    assert con_profilo["default"] is False


async def test_le_resource_statiche_sono_leggibili(mcp):
    for uri in ("scala://pericolo-valanghe", "scala://difficolta-escursionistica"):
        contenuti = list(await mcp.read_resource(uri))
        assert contenuti and len(contenuti[0].content) > 500


async def test_prompt_registrati(mcp):
    nomi = {p.name for p in await mcp.list_prompts()}
    assert nomi == {"prepara_gita", "spiega_bollettino"}


async def test_il_prompt_vieta_il_verdetto(mcp):
    risultato = await mcp.get_prompt("prepara_gita", {"sentiero": "103", "data": "2026-02-01"})
    testo = " ".join(str(m.content) for m in risultato.messages).lower()

    assert "verdetto" in testo
    assert "fonti" in testo


async def test_le_istruzioni_dichiarano_le_fonti(mcp):
    assert mcp.instructions
    for atteso in ("OpenStreetMap", "AINEVA", "CAAML"):
        assert atteso in mcp.instructions


async def test_le_istruzioni_preferiscono_sentieri_verso_localita(mcp):
    assert "sentieri_verso_localita" in mcp.instructions


async def test_le_istruzioni_indirizzano_ai_tool_di_lookup(mcp):
    assert "zona_valanghe_da_coordinate" in mcp.instructions
    assert "cerca_localita" in mcp.instructions


async def test_dettaglio_sentiero_description_sconsiglia_ridondanza(mcp):
    dettaglio = next(t for t in await mcp.list_tools() if t.name == "dettaglio_sentiero")
    testo = (dettaglio.description or "").lower()
    assert "cerca_sentieri" in testo
    assert "necessario" in testo or "solo se" in testo


async def test_cerca_localita_espone_raggio_km_non_scelta_geocode(mcp):
    tool = next(t for t in await mcp.list_tools() if t.name == "cerca_localita")
    props = tool.input_schema.get("properties", {})
    assert "raggio_km" in props
    assert "azione" not in props
    assert "nuovo_raggio_km" not in props


async def test_sentieri_verso_localita_espone_raggio_geocode_km(mcp):
    tool = next(t for t in await mcp.list_tools() if t.name == "sentieri_verso_localita")
    props = tool.input_schema.get("properties", {})
    assert "raggio_geocode_km" in props
    assert "raggio_km" in props
    assert "azione" not in props
    assert "nuovo_raggio_km" not in props

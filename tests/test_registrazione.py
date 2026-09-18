"""Come i tool vengono registrati, e cosa arriva al client quando falliscono.

Era il buco piu' grosso della suite: la traduzione degli errori e' il
contratto fra server e modello — quello che decide se il modello legge una
frase utile o un traceback — e non la copriva nessun test.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from trekking_mcp.errors import ErroreSentieri, FonteNonDisponibile, NonTrovato, ParametriNonValidi
from trekking_mcp.server import crea_server
from trekking_mcp.tools.comuni import gestisci_errori

TOOL_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "trekking_mcp" / "tools"


# --- la traduzione in se' ----------------------------------------------------


@pytest.mark.parametrize(
    ("errore", "atteso"),
    [
        (FonteNonDisponibile("overpass", "HTTP 503"), "non e' al momento raggiungibile"),
        (NonTrovato("sentiero", "999"), "Nessun risultato"),
        (NonTrovato("zona", "X", alternative=["IT-21-AO-01"]), "IT-21-AO-01"),
        (ParametriNonValidi("raggio incoerente"), "raggio incoerente"),
    ],
)
async def test_un_errore_previsto_diventa_un_messaggio_leggibile(errore: ErroreSentieri, atteso: str):
    @gestisci_errori
    async def fallisce() -> None:
        raise errore

    with pytest.raises(ToolError) as sollevato:
        await fallisce()

    assert atteso in str(sollevato.value)
    # La causa originale resta agganciata: il log tiene il contesto completo.
    assert sollevato.value.__cause__ is errore


async def test_un_errore_imprevisto_non_viene_mascherato():
    """Un bug deve restare un bug: mascherarlo da ToolError lo renderebbe invisibile."""

    @gestisci_errori
    async def esplode() -> None:
        raise ZeroDivisionError("bug vero")

    with pytest.raises(ZeroDivisionError):
        await esplode()


async def test_il_valore_di_ritorno_passa_intatto():
    @gestisci_errori
    async def ok() -> str:
        return "valore"

    assert await ok() == "valore"


# --- la traduzione vista dal client ------------------------------------------


async def test_il_client_riceve_il_messaggio_non_il_traceback(monkeypatch, risorse):
    """Fine a fine: una fonte giu' deve arrivare come testo azionabile, con is_error."""

    async def _giu(*args: object, **kwargs: object) -> None:
        raise FonteNonDisponibile("overpass", "HTTP 503")

    monkeypatch.setattr("trekking_mcp.tools.sentieri.overpass.cerca_sentieri", _giu)

    async with Client(crea_server(risorse=risorse)) as client:
        esito = await client.call_tool("cerca_sentieri", {"lat": 45.5, "lon": 7.5})

    assert esito.is_error, "l'errore deve arrivare come risultato is_error, non come crash"
    testo = "".join(c.text for c in esito.content if getattr(c, "text", None))
    assert "overpass" in testo
    assert "riprovare" in testo
    assert "Traceback" not in testo


async def test_una_zona_inesistente_suggerisce_quelle_valide(monkeypatch, risorse):
    """`NonTrovato` porta le alternative fino al client: e' meta' della sua utilita'."""

    async def _mancante(*args: object, **kwargs: object) -> None:
        raise NonTrovato("zona valanghe", "IT-99", alternative=["IT-21-AO-01", "IT-21-AO-02"])

    monkeypatch.setattr("trekking_mcp.tools.condizioni.caaml.leggi_bollettino", _mancante)

    async with Client(crea_server(risorse=risorse)) as client:
        esito = await client.call_tool("bollettino_valanghe", {"zona_id": "IT-99"})

    assert esito.is_error
    testo = "".join(c.text for c in esito.content if getattr(c, "text", None))
    assert "IT-21-AO-01" in testo


# --- la regola strutturale ---------------------------------------------------


def _moduli_tool() -> list[pathlib.Path]:
    return [f for f in TOOL_DIR.glob("*.py") if f.name not in {"__init__.py", "comuni.py"}]


def test_nessun_tool_si_registra_scavalcando_strumento():
    """`mcp.tool` diretto = un tool senza traduzione degli errori.

    La regola e' strutturale apposta: `strumento()` compone registrazione e
    `gestisci_errori`, quindi finche' si passa di li' non esiste la versione
    sbagliata da scrivere. Questo test difende l'unica porta rimasta aperta.
    """
    colpevoli = []
    for percorso in _moduli_tool():
        for nodo in ast.walk(ast.parse(percorso.read_text(encoding="utf-8"))):
            if not isinstance(nodo, ast.Call):
                continue
            fn = nodo.func
            if isinstance(fn, ast.Attribute) and fn.attr == "tool" and isinstance(fn.value, ast.Name):
                colpevoli.append(f"{percorso.name}:{nodo.lineno}")

    assert colpevoli == [], f"usa strumento() invece di mcp.tool() in: {', '.join(colpevoli)}"


async def test_ogni_tool_registrato_traduce_gli_errori():
    """Controprova dal registro: nessun tool e' sfuggito al decoratore."""
    mcp = crea_server()
    nomi = [t.name for t in await mcp.list_tools()]

    assert nomi, "nessun tool registrato"
    for nome in nomi:
        fn = mcp._tool_manager.get_tool(nome).fn  # type: ignore[attr-defined]
        assert getattr(fn, "errori_tradotti", False), f"{nome}: registrato senza gestisci_errori"

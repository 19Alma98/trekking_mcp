"""La dipendenza a senso unico, verificata invece che dichiarata.

DEVELOPMENT.md §2 promette `tools` -> `sources` -> rete, e che un adapter non
sappia di stare dietro un server MCP. Era falso in tre punti: `sources/`
importava `tools.comuni` per `distanza_km`. Un documento che descrive
un'architettura diversa da quella del codice e' peggio di nessun documento,
quindi la regola e' un test.

Gli import sotto `if TYPE_CHECKING:` si contano a parte. Non e' un'eccezione di
comodo: a runtime non esiste nessun ciclo, e l'unico riferimento verso l'alto
che resta e' il *tipo* del contenitore di dipendenze (`Risorse`), che gli
adapter accettano come primo argomento. Il guard rende quel riferimento
esplicito, e questo test lo tiene l'unico ammesso — un `sources/` che importasse
a runtime un modulo del layer sopra fallirebbe comunque.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "trekking_mcp"

# Chi puo' importare chi, dal basso verso l'alto. Un modulo puo' importare i
# livelli sotto il suo e il suo, mai sopra.
LIVELLI = [
    {"payloads", "errors", "config", "geo", "metriche"},  # fondamenta: nessuna dipendenza interna
    {"models"},  # il contratto dati verso il client
    {"cache", "sources"},  # gli adapter delle fonti
    {"tools", "resources", "prompts", "completamenti", "risorse"},  # la superficie MCP
    {"server", "__main__"},  # il montaggio
]

LIVELLO_DI = {modulo: n for n, moduli in enumerate(LIVELLI) for modulo in moduli}

# Il solo riferimento verso l'alto ammesso, e solo sotto `if TYPE_CHECKING:`.
TIPI_AMMESSI_VERSO_L_ALTO = {"risorse"}


def moduli_del_pacchetto() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.name != "__init__.py")


def _radice(percorso: Path) -> str:
    """Il nome di primo livello dentro il pacchetto: `sources/http.py` -> `sources`."""
    relativo = percorso.relative_to(SRC)
    return relativo.parts[0] if len(relativo.parts) > 1 else relativo.stem


def _e_guard_type_checking(nodo: ast.stmt) -> bool:
    if not isinstance(nodo, ast.If):
        return False
    prova = nodo.test
    if isinstance(prova, ast.Name):
        return prova.id == "TYPE_CHECKING"
    return isinstance(prova, ast.Attribute) and prova.attr == "TYPE_CHECKING"


def _radici_interne(nodi: list[ast.stmt]) -> set[str]:
    radici: set[str] = set()
    for nodo in nodi:
        for interno in ast.walk(nodo):
            moduli: list[str] = []
            if isinstance(interno, ast.ImportFrom) and interno.module:
                moduli.append(interno.module)
            elif isinstance(interno, ast.Import):
                moduli.extend(alias.name for alias in interno.names)
            for modulo in moduli:
                if modulo == "trekking_mcp" or not modulo.startswith("trekking_mcp."):
                    continue
                radici.add(modulo.split(".")[1])
    return radici


def _import_per_tipo(percorso: Path) -> tuple[set[str], set[str]]:
    """(import a runtime, import solo per i tipi) verso altri moduli del pacchetto."""
    albero = ast.parse(percorso.read_text(encoding="utf-8"))
    guard = [nodo for nodo in ast.walk(albero) if _e_guard_type_checking(nodo)]
    solo_tipi = _radici_interne([corpo for nodo in guard for corpo in nodo.body])  # type: ignore[attr-defined]
    return _radici_interne(albero.body) - solo_tipi, solo_tipi


@pytest.mark.parametrize("percorso", moduli_del_pacchetto(), ids=lambda p: str(p.relative_to(SRC)))
def test_nessun_modulo_importa_verso_l_alto(percorso: Path):
    mio_livello = LIVELLO_DI[_radice(percorso)]
    a_runtime, solo_tipi = _import_per_tipo(percorso)

    for importato in a_runtime:
        assert importato in LIVELLO_DI, f"modulo nuovo '{importato}': assegnagli un livello in questo test"
        assert LIVELLO_DI[importato] <= mio_livello, (
            f"{percorso.relative_to(SRC)} (livello {mio_livello}) importa a runtime "
            f"'{importato}' (livello {LIVELLO_DI[importato]}): la dipendenza va a senso unico, vedi §2"
        )

    for importato in solo_tipi:
        assert importato in LIVELLO_DI, f"modulo nuovo '{importato}': assegnagli un livello in questo test"
        if LIVELLO_DI[importato] > mio_livello:
            assert importato in TIPI_AMMESSI_VERSO_L_ALTO, (
                f"{percorso.relative_to(SRC)} guarda verso l'alto per il tipo '{importato}': "
                f"l'unico ammesso e' il contenitore delle dipendenze {TIPI_AMMESSI_VERSO_L_ALTO}"
            )


def test_gli_adapter_non_sanno_di_mcp():
    """Un `sources/` che importa l'SDK non e' piu' riusabile fuori da MCP (§2)."""
    for percorso in (SRC / "sources").glob("*.py"):
        testo = percorso.read_text(encoding="utf-8")
        assert "import mcp" not in testo and "from mcp" not in testo, (
            f"{percorso.name} importa l'SDK MCP: gli adapter restituiscono modelli, non risposte di protocollo"
        )


def test_il_contratto_dati_non_conosce_il_formato_delle_fonti():
    """`models.py` non deve importare `payloads`: il wire format sta negli adapter."""
    a_runtime, solo_tipi = _import_per_tipo(SRC / "models.py")
    assert "payloads" not in a_runtime | solo_tipi

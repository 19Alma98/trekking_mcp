"""Gli schemi di elicitation: cosa arriva davvero al client, e cosa lo vincola.

L'elicitation e' l'unico punto in cui il server chiede qualcosa a una persona.
Se il vincolo sta nella `description` invece che nello schema, il client non
puo' farlo rispettare e il server deve difendersi da solo: qui si verifica che
stia nello schema.
"""

from __future__ import annotations

import typing

import pytest
from mcp.server.elicitation import render_elicitation_schema
from pydantic import BaseModel, Field, ValidationError

from trekking_mcp.constants import MAX_CANDIDATI_SIMILI
from trekking_mcp.models import DifficoltaCAI
from trekking_mcp.tools.geocode_risolvi import AzioneGeocode, SceltaGeocode
from trekking_mcp.tools.gita import DifficoltaDichiarata, ProfiloUscita


def _valori(alias: object) -> list[str]:
    return list(typing.get_args(alias))


# --- l'enum arriva al client -------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "campo", "attesi"),
    [
        (SceltaGeocode, "azione", _valori(AzioneGeocode)),
        (ProfiloUscita, "difficolta_max", _valori(DifficoltaDichiarata)),
    ],
)
def test_il_campo_a_scelta_chiusa_viaggia_come_enum(schema: type[BaseModel], campo: str, attesi: list[str]):
    reso = render_elicitation_schema(schema)
    proprieta = reso["properties"][campo]

    assert proprieta.get("enum") == attesi, f"{campo}: il client non riceve le scelte come enum"
    assert proprieta["type"] == "string"


@pytest.mark.parametrize("schema", [SceltaGeocode, ProfiloUscita])
def test_gli_schemi_sono_accettati_dal_protocollo(schema: type[BaseModel]):
    """`render_elicitation_schema` solleva TypeError su quello che il profilo non ammette."""
    reso = render_elicitation_schema(schema)

    assert reso["type"] == "object"
    assert reso["properties"]


def test_uno_strenum_non_sarebbe_passato():
    """Documenta il motivo per cui qui si usa Literal e non un StrEnum.

    Pydantic rende un enum Python come `$ref` a `$defs`, che non e' una
    `PrimitiveSchemaDefinition`: l'SDK lo rifiuta. E' il vincolo che spiega
    perche' questi campi non usano `DifficoltaCAI` direttamente.
    """

    class ConStrEnum(BaseModel):
        difficolta: DifficoltaCAI = Field(default=DifficoltaCAI.E)

    with pytest.raises(TypeError, match="PrimitiveSchemaDefinition"):
        render_elicitation_schema(ConStrEnum)


# --- i valori fuori scala vengono respinti -----------------------------------


@pytest.mark.parametrize("azione", ["usa_0", "usa_99", "USA_1", "annulla", ""])
def test_un_azione_fuori_enum_e_respinta(azione: str):
    with pytest.raises(ValidationError):
        SceltaGeocode(azione=azione)  # type: ignore[arg-type]


@pytest.mark.parametrize("valore", ["sconosciuta", "F", "ee", ""])
def test_una_difficolta_fuori_scala_e_respinta(valore: str):
    with pytest.raises(ValidationError):
        ProfiloUscita(difficolta_max=valore)  # type: ignore[arg-type]


# --- i due elenchi restano agganciati alla loro fonte ------------------------


def test_le_azioni_usa_coprono_esattamente_i_candidati_possibili():
    """Se qualcuno alza MAX_CANDIDATI_SIMILI, l'enum deve seguirlo.

    Un quarto candidato senza il corrispondente `usa_4` sarebbe irraggiungibile:
    proposto nel messaggio, non selezionabile nello schema.
    """
    usa = [a for a in _valori(AzioneGeocode) if a.startswith("usa_")]

    assert usa == [f"usa_{i}" for i in range(1, MAX_CANDIDATI_SIMILI + 1)]


def test_le_difficolta_dichiarabili_sono_la_scala_cai_meno_sconosciuta():
    """`sconosciuta` e' uno stato del dato OSM, non una risposta che si possa dare."""
    scala = [d.value for d in DifficoltaCAI if d is not DifficoltaCAI.SCONOSCIUTA]

    assert _valori(DifficoltaDichiarata) == scala

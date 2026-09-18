from __future__ import annotations

from typing import Literal

from mcp.server.elicitation import AcceptedElicitation
from mcp.server.mcpserver.context import Context
from pydantic import BaseModel, Field

from trekking_mcp.errors import NonTrovato
from trekking_mcp.geo import distanza_km
from trekking_mcp.models import Localita
from trekking_mcp.risorse import Risorse
from trekking_mcp.sources import nominatim
from trekking_mcp.sources.luoghi_simili import cerca_simili_nel_raggio

MAX_ESPANSIONI = 2


# Le azioni ammesse sono un insieme chiuso: `cerca_simili_nel_raggio` ne
# restituisce al massimo MAX_CANDIDATI_SIMILI (3), piu' l'espansione del raggio.
# `test_elicitation.py` verifica che i due restino allineati.
AzioneGeocode = Literal["usa_1", "usa_2", "usa_3", "espandi"]


class SceltaGeocode(BaseModel):
    """Risposta elicitation: schema piatto (vincolo protocollo).

    `azione` e' un `Literal`, non una stringa con le opzioni scritte nella
    description: cosi' l'enum finisce nel JSON Schema che il client riceve, e
    il client puo' mostrare tre bottoni invece di un campo di testo libero.

    Un `StrEnum` qui **non** funzionerebbe: Pydantic lo rende come `$ref` a
    `$defs`, e l'SDK lo rifiuta perche' non e' una `PrimitiveSchemaDefinition`.
    Il vincolo del protocollo e' sui campi piatti, e `Literal` e' il modo di
    avere un enum restando piatti.
    """

    azione: AzioneGeocode = Field(description="Quale candidato usare, o espandi per allargare il raggio")
    nuovo_raggio_km: int = Field(
        default=50,
        ge=31,
        le=200,
        description="Usato solo se azione=espandi",
    )


def messaggio_scelta_geocode(
    nome: str,
    *,
    lat: float,
    lon: float,
    raggio_km: float,
    simili: list[Localita],
) -> str:
    linee = [
        f"Non ho trovato «{nome}» entro {raggio_km:g} km da ({lat:.2f}, {lon:.2f}).",
    ]
    if simili:
        linee.append("Intendevi:")
        for i, loc in enumerate(simili, start=1):
            d = distanza_km(lat, lon, loc.coord.lat, loc.coord.lon)
            pezzi = [loc.tipo or "luogo", f"{d:.0f} km"]
            if loc.quota_m is not None:
                pezzi.append(f"{loc.quota_m} m")
            linee.append(f"{i}) {loc.nome} ({', '.join(pezzi)})")
        azioni = ", ".join(f"usa_{i}" for i in range(1, len(simili) + 1))
        linee.append(
            f"Scegli azione={azioni} oppure azione=espandi e indica nuovo_raggio_km "
            f"(es. {max(int(raggio_km) + 20, 50)})."
        )
    else:
        linee.append(
            f"Nessun nome simile nel raggio. Scegli azione=espandi e indica nuovo_raggio_km "
            f"(es. {max(int(raggio_km) + 20, 50)}), oppure annulla."
        )
    return "\n".join(linee)


async def risolvi_localita(
    risorse: Risorse,
    ctx: Context,
    nome: str,
    *,
    lat: float,
    lon: float,
    raggio_km: float = 30,
    limite: int = 5,
) -> list[Localita]:
    raggio = float(raggio_km)
    espansioni = 0
    while True:
        esatti = await nominatim.cerca(risorse, nome, limite=limite, lat=lat, lon=lon, raggio_km=raggio)
        if esatti:
            return esatti

        simili = await cerca_simili_nel_raggio(risorse, nome, lat=lat, lon=lon, raggio_km=raggio)
        messaggio = messaggio_scelta_geocode(nome, lat=lat, lon=lon, raggio_km=raggio, simili=simili)
        esito = await ctx.elicit(messaggio, SceltaGeocode)

        if not isinstance(esito, AcceptedElicitation):
            raise NonTrovato("localita'", nome)

        scelta = esito.data
        if scelta.azione == "espandi":
            if espansioni >= MAX_ESPANSIONI:
                raise NonTrovato("localita'", nome)
            if scelta.nuovo_raggio_km <= raggio:
                raise NonTrovato(
                    "localita'",
                    nome,
                    alternative=[f"nuovo_raggio_km deve essere > {raggio:g}"],
                )
            raggio = float(scelta.nuovo_raggio_km)
            espansioni += 1
            continue

        # L'enum garantisce la forma "usa_N"; non garantisce che il candidato
        # N-esimo esista, perche' i simili trovati possono essere meno di tre.
        indice = int(scelta.azione.removeprefix("usa_")) - 1
        if 0 <= indice < len(simili):
            return [simili[indice]]

        raise NonTrovato("localita'", nome)

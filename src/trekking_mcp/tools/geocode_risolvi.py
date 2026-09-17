from __future__ import annotations

from mcp.server.mcpserver.context import Context
from pydantic import BaseModel, Field

from trekking_mcp.errors import NonTrovato
from trekking_mcp.models import Localita
from trekking_mcp.sources import nominatim
from trekking_mcp.sources.luoghi_simili import cerca_simili_nel_raggio
from trekking_mcp.tools.comuni import distanza_km

MAX_ESPANSIONI = 2


class SceltaGeocode(BaseModel):
    """Risposta elicitation: schema piatto (vincolo protocollo)."""

    azione: str = Field(description="usa_1 | usa_2 | usa_3 | espandi")
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
        esatti = await nominatim.cerca(nome, limite=limite, lat=lat, lon=lon, raggio_km=raggio)
        if esatti:
            return esatti

        simili = await cerca_simili_nel_raggio(nome, lat=lat, lon=lon, raggio_km=raggio)
        messaggio = messaggio_scelta_geocode(
            nome, lat=lat, lon=lon, raggio_km=raggio, simili=simili
        )
        esito = await ctx.elicit(messaggio, SceltaGeocode)

        if esito.action in {"decline", "cancel"}:
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

        if scelta.azione.startswith("usa_") and simili:
            try:
                indice = int(scelta.azione.split("_", 1)[1]) - 1
            except ValueError as exc:
                raise NonTrovato("localita'", nome) from exc
            if 0 <= indice < len(simili):
                return [simili[indice]]

        raise NonTrovato("localita'", nome)

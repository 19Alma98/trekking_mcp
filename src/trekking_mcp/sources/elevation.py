from __future__ import annotations

import logging
from itertools import pairwise
from typing import TYPE_CHECKING

from trekking_mcp.constants import (
    MAX_PUNTI_QUOTE,
    MAX_PUNTI_RESTITUITI,
    PASSO_M_DEFAULT,
    PUNTI_PER_RICHIESTA,
)
from trekking_mcp.geo import distanza_km
from trekking_mcp.models import Coord, ProfiloAltimetrico, PuntoQuotato

if TYPE_CHECKING:
    from trekking_mcp.risorse import Risorse

log = logging.getLogger(__name__)


def campiona(punti: list[Coord], passo_m: float = PASSO_M_DEFAULT, massimo: int = MAX_PUNTI_QUOTE) -> list[Coord]:
    """Riduce una polilinea mantenendo la forma del profilo.

    Si tiene un punto ogni `passo_m` di percorso, non uno ogni N indici: la
    densita' dei vertici in OSM e' irregolare, e campionare per indice
    infittirebbe i tornanti e diraderebbe i lunghi rettilinei, deformando il
    profilo. Primo e ultimo punto sono sempre conservati, perche' determinano
    quota di partenza e di arrivo.
    """
    if len(punti) <= 2:
        return list(punti)

    scelti = [punti[0]]
    accumulato = 0.0
    for precedente, corrente in pairwise(punti):
        accumulato += distanza_km(precedente.lat, precedente.lon, corrente.lat, corrente.lon) * 1000
        if accumulato >= passo_m:
            scelti.append(corrente)
            accumulato = 0.0

    if scelti[-1] is not punti[-1]:
        scelti.append(punti[-1])

    if len(scelti) > massimo:
        fattore = len(scelti) / (massimo - 1)
        diradati = [scelti[int(i * fattore)] for i in range(massimo - 1)]
        diradati.append(scelti[-1])
        return diradati

    return scelti


async def quote(risorse: Risorse, punti: list[Coord]) -> list[float | None]:
    """Quota del terreno per ogni punto, nell'ordine dato."""
    if not punti:
        return []

    risultato: list[float | None] = []
    for inizio in range(0, len(punti), PUNTI_PER_RICHIESTA):
        blocco = punti[inizio : inizio + PUNTI_PER_RICHIESTA]
        dati = await risorse.http.json(
            "GET",
            risorse.config.elevazione_url,
            fonte="open-meteo-elevation",
            ttl_s=risorse.config.ttl_elevazione_s,
            params={
                "latitude": ",".join(f"{p.lat:.5f}" for p in blocco),
                "longitude": ",".join(f"{p.lon:.5f}" for p in blocco),
            },
        )
        elevazioni = dati.get("elevation") or []
        for i in range(len(blocco)):
            risultato.append(elevazioni[i] if i < len(elevazioni) else None)

    return risultato


def _dislivelli(quote_m: list[float], soglia_m: float = 5.0) -> tuple[int, int]:
    """Dislivello positivo e negativo cumulati.

    La soglia elimina il rumore del modello di elevazione: senza, ogni
    oscillazione di un metro fra due punti si somma e il dislivello risulta
    gonfiato anche del 30%. E' l'errore piu' comune nel calcolo dei profili.
    """
    salita = discesa = 0.0
    riferimento = quote_m[0]

    for quota in quote_m[1:]:
        delta = quota - riferimento
        if abs(delta) < soglia_m:
            continue
        if delta > 0:
            salita += delta
        else:
            discesa += -delta
        riferimento = quota

    return round(salita), round(discesa)


def dirada(quotati: list[PuntoQuotato], massimo: int = MAX_PUNTI_RESTITUITI) -> list[PuntoQuotato]:
    """Riduce i punti da restituire tenendo primo e ultimo.

    Separato dal campionamento perche' risponde a un'altra domanda. `campiona`
    decide quanti punti *quotare*, e la risposta la da' l'accuratezza del
    dislivello; questa decide quanti *mostrarne*, e la risposta la da' il costo in
    contesto per il modello che legge.
    """
    if len(quotati) <= massimo:
        return quotati
    fattore = (len(quotati) - 1) / (massimo - 1)
    indici = sorted({round(i * fattore) for i in range(massimo)} | {len(quotati) - 1})
    return [quotati[i] for i in indici]


async def profilo(risorse: Risorse, punti: list[Coord], *, passo_m: float = PASSO_M_DEFAULT) -> ProfiloAltimetrico:
    """Profilo altimetrico di una polilinea."""
    campionati = campiona(punti, passo_m=passo_m)
    elevazioni = await quote(risorse, campionati)

    quotati = [
        PuntoQuotato(coord=coord, quota_m=quota)
        for coord, quota in zip(campionati, elevazioni, strict=False)
        if quota is not None
    ]

    if not quotati:
        return ProfiloAltimetrico(punti=[], lunghezza_km=0.0, dislivello_positivo_m=0, dislivello_negativo_m=0)

    valori = [p.quota_m for p in quotati]
    salita, discesa = _dislivelli(valori)
    lunghezza = sum(distanza_km(a.lat, a.lon, b.lat, b.lon) for a, b in pairwise(punti))
    passo_effettivo = round(lunghezza * 1000 / max(len(quotati) - 1, 1)) if lunghezza else None

    return ProfiloAltimetrico(
        punti=dirada(quotati),
        lunghezza_km=round(lunghezza, 2),
        dislivello_positivo_m=salita,
        dislivello_negativo_m=discesa,
        quota_minima_m=round(min(valori)),
        quota_massima_m=round(max(valori)),
        punti_quotati=len(quotati),
        passo_effettivo_m=passo_effettivo,
    )

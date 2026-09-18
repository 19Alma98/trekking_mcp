from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.resolve import Elicit, Resolve
from pydantic import BaseModel, Field

from trekking_mcp.errors import ErroreSentieri, NonTrovato
from trekking_mcp.models import (
    Bollettino,
    Coord,
    DifficoltaCAI,
    GradoPericolo,
    MeteoQuota,
    ProfiloAltimetrico,
    SegnaleAttenzione,
    Sentiero,
    ValutazioneGita,
    ZonaValanghe,
)
from trekking_mcp.risorse import Risorse
from trekking_mcp.sources import caaml, eaws, elevation, meteo, overpass
from trekking_mcp.tools.comuni import distanza_km, extended_tool

log = logging.getLogger(__name__)


# I quattro gradi CAI dichiarabili: `DifficoltaCAI` meno SCONOSCIUTA, che non e'
# una risposta che un utente possa dare. `test_elicitation.py` tiene allineati
# i due elenchi.
DifficoltaDichiarata = Literal["T", "E", "EE", "EEA"]


class ProfiloUscita(BaseModel):
    """Cosa serve sapere sull'utente, e che il modello non puo' dedurre.

    Lo schema di elicitation ammette solo campi primitivi e piatti: niente
    oggetti annidati. E' un vincolo del protocollo, non una scelta di stile.

    `difficolta_max` e' un `Literal` e non una stringa libera: i quattro valori
    ammessi arrivano al client come `enum` nel JSON Schema, quindi la scelta si
    presenta come tale e una risposta fuori scala viene respinta dalla
    validazione invece di arrivare fino a `_segnali`. Un `StrEnum` non andrebbe
    bene: Pydantic lo rende come `$ref`, che l'SDK rifiuta.
    """

    difficolta_max: DifficoltaDichiarata = Field(
        description="Difficolta' massima che ti senti di affrontare: T, E, EE o EEA",
        default="E",
    )
    attrezzatura_artva: bool = Field(
        description="Il gruppo ha ARTVA, pala e sonda, e sa usarli?",
        default=False,
    )
    persone: int = Field(description="Quante persone nel gruppo", default=2, ge=1, le=30)


def chiedi_profilo() -> Elicit[ProfiloUscita]:
    """Resolver: chiede il profilo al client prima di eseguire il tool."""
    return Elicit(
        "Per contestualizzare i dati della gita servono un paio di informazioni sul gruppo.",
        ProfiloUscita,
    )


def _segnali(
    difficolta: DifficoltaCAI,
    profilo: ProfiloUscita,
    bollettino: Bollettino | None,
    previsioni: list[MeteoQuota],
    profilo_alt: ProfiloAltimetrico | None = None,
) -> list[SegnaleAttenzione]:
    """Genera segnali di attenzione da regole esplicite e verificabili.

    Nessun modello, nessuna euristica opaca: sono soglie scritte a mano che si
    possono leggere, discutere e testare. Per un dominio di sicurezza e' l'unica
    scelta difendibile.
    """
    segnali: list[SegnaleAttenzione] = []
    ordine = [DifficoltaCAI.T, DifficoltaCAI.E, DifficoltaCAI.EE, DifficoltaCAI.EEA]
    grado: GradoPericolo | None = None

    if difficolta == DifficoltaCAI.SCONOSCIUTA:
        segnali.append(
            SegnaleAttenzione(
                categoria="difficolta",
                severita="info",
                messaggio="Difficolta' non mappata in OSM: verificare su una guida o carta prima di partire.",
            )
        )
    elif difficolta in ordine and ordine.index(difficolta) > ordine.index(DifficoltaCAI(profilo.difficolta_max)):
        segnali.append(
            SegnaleAttenzione(
                categoria="difficolta",
                severita="critico",
                messaggio=(
                    f"Il sentiero e' classificato {difficolta.value}, "
                    f"sopra il livello dichiarato ({profilo.difficolta_max})."
                ),
            )
        )

    if profilo_alt is not None and profilo_alt.dislivello_positivo_m >= 1200:
        segnali.append(
            SegnaleAttenzione(
                categoria="logistica",
                severita="info",
                messaggio=(
                    f"Dislivello positivo di {profilo_alt.dislivello_positivo_m} m "
                    f"su {profilo_alt.lunghezza_km} km: uscita impegnativa sul piano fisico."
                ),
            )
        )

    if bollettino is not None:
        grado = bollettino.grado_massimo

    if bollettino is not None and grado is None:
        # Il bollettino c'e' ma nessuno dei `dangerRatings` si e' potuto leggere.
        # Tacere qui equivarrebbe a dire "nessun pericolo segnalato".
        segnali.append(
            SegnaleAttenzione(
                categoria="valanghe",
                severita="attenzione",
                messaggio=(
                    "Il bollettino non riporta un grado di pericolo interpretabile: "
                    "leggere il documento originale, non dedurne l'assenza di pericolo."
                ),
            )
        )
    elif grado is not None:
        if grado >= GradoPericolo.MARCATO:
            segnali.append(
                SegnaleAttenzione(
                    categoria="valanghe",
                    severita="critico" if grado >= GradoPericolo.FORTE else "attenzione",
                    messaggio=f"Pericolo valanghe {int(grado)} ({grado.etichetta}). Leggere il bollettino integrale.",
                )
            )
        if grado >= GradoPericolo.MODERATO and not profilo.attrezzatura_artva:
            segnali.append(
                SegnaleAttenzione(
                    categoria="valanghe",
                    severita="attenzione",
                    messaggio="Pericolo valanghe non trascurabile e gruppo senza ARTVA/pala/sonda dichiarati.",
                )
            )

    if previsioni:
        raffica = max((p.raffica_kmh or 0) for p in previsioni)
        if raffica >= 60:
            segnali.append(
                SegnaleAttenzione(
                    categoria="meteo", severita="attenzione", messaggio=f"Raffiche fino a {raffica:.0f} km/h."
                )
            )
        neve = sum((p.neve_cm or 0) for p in previsioni)
        if neve >= 5:
            segnali.append(
                SegnaleAttenzione(
                    categoria="meteo",
                    severita="attenzione",
                    messaggio=f"Neve fresca prevista: {neve:.0f} cm nella finestra considerata.",
                )
            )

    return segnali


def registra(mcp: MCPServer, risorse: Risorse) -> None:
    @extended_tool(
        mcp,
        name="valuta_gita",
        title="Raccogli le condizioni per una gita",
        description=(
            "Dato un sentiero e una data, raccoglie in un colpo solo: dati del sentiero, "
            "rifugi e bivacchi vicini, bollettino valanghe della zona e meteo di quota. "
            "Restituisce fatti normalizzati e segnali di attenzione, NON un verdetto "
            "vai/non-vai: la decisione resta a chi va in montagna."
        ),
    )
    async def valuta_gita(
        ctx: Context,
        osm_relation_id: Annotated[int, Field(description="Relation OSM del sentiero", gt=0)],
        profilo: Annotated[ProfiloUscita, Resolve(chiedi_profilo)],
        data: Annotated[str | None, Field(description="Data ISO YYYY-MM-DD; default oggi")] = None,
        zona_valanghe: Annotated[
            str | None,
            Field(description="Zona del bollettino. Se assente viene dedotta dalle coordinate del sentiero."),
        ] = None,
        con_profilo: Annotated[
            bool,
            Field(
                description=(
                    "Calcola dislivello e lunghezza reali scaricando la geometria completa. "
                    "Molto piu' lento e soggetto a timeout su Overpass: attivalo solo se il "
                    "dislivello serve davvero."
                )
            ),
        ] = False,
        quota_riferimento_m: Annotated[int, Field(description="Quota per il meteo", ge=0, le=5000)] = 2000,
    ) -> ValutazioneGita:
        giorno = data or date.today().isoformat()

        passi = 6 if con_profilo else 5
        await ctx.report_progress(0, passi, "Carico il sentiero")

        punti: list[Coord] = []
        sentiero: Sentiero
        if con_profilo:
            esito = await overpass.leggi_geometria(risorse, osm_relation_id)
            if esito is None:
                raise NonTrovato("sentiero", str(osm_relation_id))
            sentiero, punti = esito
        else:
            trovato = await overpass.leggi_sentiero(risorse, osm_relation_id)
            if trovato is None:
                raise NonTrovato("sentiero", str(osm_relation_id))
            sentiero = trovato

        fonti = [overpass.ATTRIBUZIONE, meteo.ATTRIBUZIONE]
        # Ogni dato che non si e' riusciti a raccogliere diventa un segnale:
        # un campo vuoto, da solo, si legge come "niente da segnalare".
        buchi: list[SegnaleAttenzione] = []

        if sentiero.centro is None and punti:
            sentiero = sentiero.model_copy(
                update={
                    "centro": Coord(
                        lat=sum(c.lat for c in punti) / len(punti),
                        lon=sum(c.lon for c in punti) / len(punti),
                    )
                }
            )

        if con_profilo and len(punti) >= 2:
            await ctx.report_progress(1, passi, "Calcolo il dislivello")
            try:
                profilo_alt = await elevation.profilo(risorse, punti)
                sentiero = sentiero.model_copy(update={"profilo": profilo_alt})
                fonti.append(elevation.ATTRIBUZIONE)
            except ErroreSentieri as exc:
                log.warning("profilo altimetrico non calcolato: %s", exc)
                buchi.append(
                    SegnaleAttenzione(
                        categoria="dati",
                        severita="info",
                        messaggio="Dislivello non calcolato: la fonte di elevazione non ha risposto.",
                    )
                )
        elif con_profilo:
            buchi.append(
                SegnaleAttenzione(
                    categoria="dati",
                    severita="info",
                    messaggio=(
                        "La relation non ha way con geometria utilizzabile: dislivello e "
                        "lunghezza reali non disponibili."
                    ),
                )
            )

        if sentiero.centro is None:
            buchi.append(
                SegnaleAttenzione(
                    categoria="dati",
                    severita="attenzione",
                    messaggio=(
                        "La relation OSM non ha una posizione utilizzabile: rifugi, zona valanghe e "
                        "meteo non sono stati raccolti. I campi vuoti non significano che non ci sia "
                        "nulla. Riprova con con_profilo=true, che ricava il centro dalla geometria."
                    ),
                )
            )

        await ctx.report_progress(2, passi, "Cerco rifugi e bivacchi")
        ricoveri = []
        centro = sentiero.centro
        if centro is not None:
            ricoveri = await overpass.cerca_ricoveri(risorse, lat=centro.lat, lon=centro.lon, raggio_m=5000)
            ricoveri.sort(key=lambda r: distanza_km(centro.lat, centro.lon, r.coord.lat, r.coord.lon))
            ricoveri = ricoveri[:10]

        await ctx.report_progress(3, passi, "Individuo la zona valanghe")
        zona: ZonaValanghe | None = None
        if zona_valanghe is None and sentiero.centro:
            try:
                regione = await eaws.zona_da_coordinate(risorse.eaws, sentiero.centro.lat, sentiero.centro.lon)
                zona_valanghe = regione.id_zona
                zona = ZonaValanghe(id_zona=regione.id_zona, nome=regione.nome, coord_richiesta=sentiero.centro)
                fonti.append(eaws.ATTRIBUZIONE)
            except ErroreSentieri as exc:
                log.warning("zona valanghe non determinata: %s", exc)
                buchi.append(
                    SegnaleAttenzione(
                        categoria="valanghe",
                        severita="attenzione",
                        messaggio=(
                            "Zona valanghe non determinata per questo punto: nessun bollettino "
                            "associato. Consultare il servizio valanghe regionale."
                        ),
                    )
                )

        await ctx.report_progress(4, passi, "Leggo il bollettino valanghe")
        bollettino = None
        if zona_valanghe:
            # Il provider si deduce dalla zona: una zona CH- chiesta ad AINEVA
            # tornava "non trovata" con l'elenco delle zone italiane.
            provider = caaml.provider_per_zona(zona_valanghe)
            try:
                bollettino = await caaml.leggi_bollettino(risorse, zona_id=zona_valanghe, provider=provider)
                fonti.append(caaml.PROVIDER[provider]["attribuzione"])
            except ErroreSentieri as exc:
                log.warning("bollettino non disponibile: %s", exc)

        await ctx.report_progress(5, passi, "Scarico il meteo")
        previsioni: list[MeteoQuota] = []
        if sentiero.centro:
            previsioni = await meteo.previsione(
                risorse,
                lat=sentiero.centro.lat,
                lon=sentiero.centro.lon,
                quota_m=quota_riferimento_m,
                data=giorno,
            )

        segnali = _segnali(sentiero.difficolta_cai, profilo, bollettino, previsioni, sentiero.profilo)
        segnali.extend(buchi)
        if zona_valanghe and bollettino is None:
            segnali.append(
                SegnaleAttenzione(
                    categoria="valanghe",
                    severita="attenzione",
                    messaggio="Bollettino non recuperato: consultare il sito ufficiale prima di partire.",
                )
            )

        await ctx.report_progress(passi, passi, "Fatto")
        return ValutazioneGita(
            sentiero=sentiero,
            data=giorno,
            zona_valanghe=zona,
            ricoveri_vicini=ricoveri,
            bollettino=bollettino,
            meteo=previsioni,
            segnali=segnali,
            fonti=fonti,
        )

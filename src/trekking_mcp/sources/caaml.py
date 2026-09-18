"""Adapter per i bollettini valanghe in formato CAAML v6, profilo EAWS.

Tre provider parlano lo stesso schema, quindi il parsing e' scritto una volta
sola e i provider differiscono solo per URL:

- AINEVA   -> arco alpino italiano + Appennino marchigiano (piattaforma ALBINA)
- ALBINA   -> Euregio: Tirolo, Alto Adige, Trentino
- SLF      -> Svizzera (CC BY 4.0)

Questo e' il punto in cui il repo dimostra qualcosa di non banale: un layer di
normalizzazione su uno standard reale, invece di un wrapper 1:1 su una API.

ATTENZIONE: il bollettino valanghe e' un documento ufficiale di sicurezza.
Questo codice lo rilegge, non lo interpreta.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, TypedDict, cast

from trekking_mcp.config import Config
from trekking_mcp.errors import NonTrovato
from trekking_mcp.models import (
    Bollettino,
    GradoPericolo,
    ProblemaValanghivo,
    ValutazionePericolo,
)
from trekking_mcp.payloads import (
    CaamlAvalancheProblem,
    CaamlBulletin,
    CaamlDangerRating,
    CaamlElevationBound,
    CaamlResponse,
    CaamlTextBlock,
)

if TYPE_CHECKING:
    from trekking_mcp.risorse import Risorse


class _Provider(TypedDict):
    url: Callable[[Config, str], str]
    attribuzione: str
    prefisso_zone: str
    """Prefisso degli ID di zona del provider: AINEVA copre l'Italia, SLF la Svizzera."""


# L'URL e' funzione del Config, non di un singleton letto alla definizione:
# cosi' due server con configurazioni diverse non si contendono il modulo.
PROVIDER: dict[str, _Provider] = {
    "aineva": {
        "url": lambda cfg, lang: f"{cfg.aineva_url}/albina_files/latest/{lang}.json",
        "attribuzione": "Bollettino valanghe: AINEVA / servizi valanghe regionali",
        "prefisso_zone": "IT-",
    },
    "slf": {
        "url": lambda cfg, lang: f"{cfg.slf_url}/{lang}/json",
        "attribuzione": "Bollettino valanghe: WSL-SLF, CC BY 4.0",
        "prefisso_zone": "CH-",
    },
}

PROVIDER_DEFAULT = "aineva"


def provider_per_zona(zona_id: str) -> str:
    """Il provider che emette il bollettino di questa zona, dal prefisso dell'ID.

    Sta qui, accanto agli URL, perche' il legame zona -> provider e' una
    proprieta' del provider: tenerne una seconda copia altrove (era in
    `completamenti.py`) significa che un terzo provider ne aggiorna una sola.
    """
    for nome, dati in PROVIDER.items():
        if zona_id.startswith(dati["prefisso_zone"]):
            return nome
    return PROVIDER_DEFAULT


_GRADI = {
    "low": GradoPericolo.DEBOLE,
    "moderate": GradoPericolo.MODERATO,
    "considerable": GradoPericolo.MARCATO,
    "high": GradoPericolo.FORTE,
    "very_high": GradoPericolo.MOLTO_FORTE,
}


def _data(valore: str | None) -> datetime:
    """Istante CAAML, sempre timezone-aware."""
    if not valore:
        return datetime.now(UTC)
    istante = datetime.fromisoformat(valore.replace("Z", "+00:00"))
    return istante if istante.tzinfo is not None else istante.replace(tzinfo=UTC)


def _quota(valore: CaamlElevationBound | None) -> int | None:
    """`elevation` puo' essere un intero, una stringa, o 'treeline'."""
    if valore in (None, "", "treeline"):
        return None
    try:
        return int(float(valore))
    except (TypeError, ValueError):
        return None


def _valutazioni(grezze: list[CaamlDangerRating]) -> list[ValutazionePericolo]:
    esito: list[ValutazionePericolo] = []
    for v in grezze:
        grado = _GRADI.get(str(v.get("mainValue", "")).lower())
        if grado is None:
            continue
        elev = v.get("elevation") or {}
        limite = _quota(elev.get("lowerBound") or elev.get("upperBound"))
        sopra = "lowerBound" in elev
        esito.append(
            ValutazionePericolo(
                grado=grado,
                etichetta=grado.etichetta,
                quota_limite_m=limite,
                sopra_quota=sopra if limite is not None else None,
            )
        )
    return esito


def _problemi(grezzi: list[CaamlAvalancheProblem]) -> list[ProblemaValanghivo]:
    esito: list[ProblemaValanghivo] = []
    for p in grezzi:
        tipo = p.get("problemType") or p.get("type")
        if not tipo:
            continue
        elev = p.get("elevation") or {}
        esito.append(
            ProblemaValanghivo(
                tipo=str(tipo),
                esposizioni=[str(a).upper() for a in (p.get("aspects") or [])],
                quota_min_m=_quota(elev.get("lowerBound")),
                quota_max_m=_quota(elev.get("upperBound")),
            )
        )
    return esito


def _testo(blocco: str | CaamlTextBlock | None) -> str | None:
    """I campi testuali CAAML sono a volte stringhe, a volte {'highlights': ...}."""
    if isinstance(blocco, str):
        return blocco.strip() or None
    if isinstance(blocco, dict):
        for chiave in ("highlights", "comment", "avalancheActivityComment"):
            if (valore := blocco.get(chiave)) and isinstance(valore, str):
                return valore.strip()
    return None


def normalizza(grezzo: CaamlBulletin, *, zona_id: str, provider: str, url: str) -> Bollettino:
    """Converte un singolo `bulletin` CAAML v6 nel modello interno."""
    regioni = grezzo.get("regions") or []
    nome_zona = next((r.get("name") for r in regioni if r.get("regionID") == zona_id), None)
    validita = grezzo.get("validTime") or {}

    return Bollettino(
        id_bollettino=str(grezzo.get("bulletinID") or grezzo.get("id") or zona_id),
        zona_id=zona_id,
        zona_nome=nome_zona,
        valido_da=_data(validita.get("startTime")),
        valido_fino=_data(validita.get("endTime")),
        valutazioni=_valutazioni(grezzo.get("dangerRatings") or []),
        problemi=_problemi(grezzo.get("avalancheProblems") or []),
        sintesi=_testo(grezzo.get("highlights")) or _testo(grezzo.get("avalancheActivity")),
        innevamento=_testo(grezzo.get("snowpackStructure")),
        fonte=provider,
        fonte_url=url,
    )


async def leggi_bollettino(
    risorse: Risorse, *, zona_id: str, provider: str | None = None, lingua: str = "it"
) -> Bollettino:
    """Scarica il bollettino corrente e ne estrae la zona richiesta.

    Con `provider=None` lo deduce dall'ID di zona: chiedere una zona svizzera ad
    AINEVA non restituisce un errore chiaro, restituisce "zona non trovata" con
    l'elenco delle zone italiane, che e' fuorviante.
    """
    if provider is None:
        provider = provider_per_zona(zona_id)
    if provider not in PROVIDER:
        raise NonTrovato("provider", provider, list(PROVIDER))

    url = PROVIDER[provider]["url"](risorse.config, lingua)
    dati = cast(
        CaamlResponse,
        await risorse.http.json("GET", url, fonte=provider, ttl_s=risorse.config.ttl_bollettino_s),
    )

    bollettini = dati.get("bulletins") or [f.get("properties") or {} for f in dati.get("features") or []]

    zone_disponibili: list[str] = []
    for b in bollettini:
        ids = [r.get("regionID") for r in (b.get("regions") or [])]
        zone_disponibili.extend(i for i in ids if i)
        if zona_id in ids:
            return normalizza(b, zona_id=zona_id, provider=provider, url=url)

    raise NonTrovato("zona valanghe", zona_id, sorted(set(zone_disponibili)))

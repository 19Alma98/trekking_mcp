"""Adapter Open-Meteo: previsione oraria corretta per l'elevazione.

Il parametro `elevation` conta: in montagna la differenza fra la quota del
modello e quella reale del punto puo' valere diversi gradi, e quindi sposta la
quota neve. Open-Meteo e' gratuito e senza chiave.

La serie oraria che Open-Meteo restituisce comincia sempre a **mezzanotte** del
giorno richiesto, non "da adesso" e non dall'alba. Prendere le prime N ore
cosi' come arrivano significa rispondere con la notte: per una gita e' l'unica
finestra che non interessa, e il pomeriggio — quando arrivano i temporali —
resta fuori. Da qui `_finestra()`: vedi DEVELOPMENT.md §3.27.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from trekking_mcp.models import Coord, MeteoQuota

if TYPE_CHECKING:
    from trekking_mcp.risorse import Risorse

ATTRIBUZIONE = "Dati meteo: Open-Meteo.com, CC BY 4.0"
_TZ_ROMA = ZoneInfo("Europe/Rome")

# Prima ora utile di una giornata di montagna. Una partenza alpinistica e' piu'
# presto: si passa `ora_inizio` esplicita.
ORA_INIZIO_GIORNATA = 6
_ORARIE = [
    "temperature_2m",
    "precipitation",
    "snowfall",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
    "freezing_level_height",
]


def _finestra(
    istanti: list[str],
    *,
    giorno: date | None,
    ore_max: int,
    ora_inizio: int | None,
    adesso: datetime | None = None,
) -> list[tuple[int, str]]:
    """Le `ore_max` ore che interessano, con il loro indice nella serie oraria.

    Regole, in ordine:
    - `ora_inizio` esplicita vince su tutto: e' l'utente che sa a che ora parte.
    - per **oggi**, si parte dall'ora corrente: le ore gia' passate non sono una
      previsione.
    - per un giorno **futuro**, si parte da `ORA_INIZIO_GIORNATA`.

    Restituisce anche l'indice perche' le altre serie (temperatura, vento, ...)
    sono parallele a `time` e vanno lette nello stesso punto.
    """
    coppie = list(enumerate(istanti))
    if not coppie:
        return []

    if ora_inizio is not None:
        prima_ora = ora_inizio
    else:
        ora_locale = adesso if adesso is not None else datetime.now(_TZ_ROMA)
        oggi = giorno is None or giorno == ora_locale.date()
        prima_ora = ora_locale.hour if oggi else ORA_INIZIO_GIORNATA

    def da_tenere(istante: str) -> bool:
        try:
            return _parse_istante(istante).hour >= prima_ora
        except ValueError:
            return True

    # `next` sull'indice della prima ora utile invece di un filtro: la serie e'
    # ordinata, e se la finestra cade oltre la fine (previsione richiesta per
    # stasera alle 23 con ore_max alto) si degrada alle ultime ore disponibili
    # invece di restituire una lista vuota.
    inizio = next((i for i, istante in coppie if da_tenere(istante)), max(len(coppie) - ore_max, 0))
    return coppie[inizio : inizio + ore_max]


async def previsione(
    risorse: Risorse,
    *,
    lat: float,
    lon: float,
    quota_m: int,
    data: str | None = None,
    ore_max: int = 12,
    ora_inizio: int | None = None,
) -> list[MeteoQuota]:
    parametri: dict[str, object] = {
        "latitude": lat,
        "longitude": lon,
        "elevation": quota_m,
        "hourly": ",".join(_ORARIE),
        "timezone": "Europe/Rome",
        "models": "best_match",
    }
    if data:
        parametri["start_date"] = data
        parametri["end_date"] = data

    dati = await risorse.http.json(
        "GET", risorse.config.meteo_url, fonte="open-meteo", ttl_s=risorse.config.ttl_meteo_s, params=parametri
    )

    orarie = dati.get("hourly") or {}
    istanti = orarie.get("time") or []
    coord = Coord(lat=lat, lon=lon)

    def _v(chiave: str, i: int) -> float | None:
        serie = orarie.get(chiave) or []
        return serie[i] if i < len(serie) else None

    esito: list[MeteoQuota] = []
    for i, istante in _finestra(istanti, giorno=_giorno(data), ore_max=ore_max, ora_inizio=ora_inizio):
        direzione = _v("wind_direction_10m", i)
        zero = _v("freezing_level_height", i)
        copertura = _v("cloud_cover", i)
        esito.append(
            MeteoQuota(
                coord=coord,
                quota_m=quota_m,
                istante=_parse_istante(istante),
                temperatura_c=_v("temperature_2m", i),
                vento_kmh=_v("wind_speed_10m", i),
                raffica_kmh=_v("wind_gusts_10m", i),
                direzione_vento_gradi=int(direzione) if direzione is not None else None,
                precipitazioni_mm=_v("precipitation", i),
                neve_cm=_v("snowfall", i),
                copertura_nuvolosa_pct=int(copertura) if copertura is not None else None,
                zero_termico_m=int(zero) if zero is not None else None,
            )
        )
    return esito


def _giorno(data: str | None) -> date | None:
    if not data:
        return None
    try:
        return date.fromisoformat(data)
    except ValueError:
        return None


def _parse_istante(valore: str) -> datetime:
    dt = datetime.fromisoformat(valore)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_TZ_ROMA)
    return dt

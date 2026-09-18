"""Adapter Open-Meteo: previsione oraria corretta per l'elevazione.

Il parametro `elevation` conta: in montagna la differenza fra la quota del
modello e quella reale del punto puo' valere diversi gradi, e quindi sposta la
quota neve. Open-Meteo e' gratuito e senza chiave.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from trekking_mcp.models import Coord, MeteoQuota

if TYPE_CHECKING:
    from trekking_mcp.risorse import Risorse

ATTRIBUZIONE = "Dati meteo: Open-Meteo.com, CC BY 4.0"
_TZ_ROMA = ZoneInfo("Europe/Rome")
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


async def previsione(
    risorse: Risorse,
    *,
    lat: float,
    lon: float,
    quota_m: int,
    data: str | None = None,
    ore_max: int = 12,
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
    for i, istante in enumerate(istanti[:ore_max]):
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


def _parse_istante(valore: str) -> datetime:
    dt = datetime.fromisoformat(valore)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_TZ_ROMA)
    return dt

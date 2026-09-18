from datetime import date, datetime
from zoneinfo import ZoneInfo

import respx

from trekking_mcp.sources import meteo

TZ = ZoneInfo("Europe/Rome")

GIORNATA = [f"2026-09-20T{ora:02d}:00" for ora in range(24)]


def _ore(finestra: list[tuple[int, str]]) -> list[int]:
    return [datetime.fromisoformat(istante).hour for _, istante in finestra]


def test_un_giorno_futuro_parte_dall_alba_non_da_mezzanotte():
    finestra = meteo._finestra(
        GIORNATA,
        giorno=date(2026, 9, 20),
        ore_max=12,
        ora_inizio=None,
        adesso=datetime(2026, 9, 18, 21, 30, tzinfo=TZ),
    )

    assert _ore(finestra) == list(range(6, 18)), "la finestra di una gita deve coprire il giorno, non la notte"


def test_oggi_parte_dall_ora_corrente():
    finestra = meteo._finestra(
        GIORNATA,
        giorno=date(2026, 9, 20),
        ore_max=4,
        ora_inizio=None,
        adesso=datetime(2026, 9, 20, 14, 5, tzinfo=TZ),
    )

    assert _ore(finestra) == [14, 15, 16, 17], "le ore gia' passate non sono una previsione"


def test_ora_inizio_esplicita_vince():
    finestra = meteo._finestra(
        GIORNATA,
        giorno=date(2026, 9, 20),
        ore_max=3,
        ora_inizio=4,
        adesso=datetime(2026, 9, 18, 12, 0, tzinfo=TZ),
    )

    assert _ore(finestra) == [4, 5, 6], "una partenza alpinistica alle 4 deve poter chiedere le 4"


def test_l_indice_resta_allineato_alla_serie():
    finestra = meteo._finestra(
        GIORNATA,
        giorno=date(2026, 9, 20),
        ore_max=2,
        ora_inizio=9,
        adesso=datetime(2026, 9, 18, 12, 0, tzinfo=TZ),
    )

    assert [i for i, _ in finestra] == [9, 10]


def test_una_finestra_oltre_la_fine_degrada_alle_ultime_ore():
    finestra = meteo._finestra(
        GIORNATA[:2],
        giorno=date(2026, 9, 20),
        ore_max=2,
        ora_inizio=None,
        adesso=datetime(2026, 9, 18, 12, 0, tzinfo=TZ),
    )
    assert _ore(finestra) == [0, 1]


def test_una_serie_vuota_non_esplode():
    assert meteo._finestra([], giorno=None, ore_max=12, ora_inizio=None) == []


async def test_previsione_di_un_giorno_futuro_non_restituisce_la_notte(httpx2_mock: respx.Router, risorse):
    httpx2_mock.get(url__startswith="https://api.open-meteo.com/v1/forecast").respond(
        200,
        json={
            "hourly": {
                "time": GIORNATA,
                "temperature_2m": [float(ora) for ora in range(24)],
                "wind_gusts_10m": [0.0] * 24,
            }
        },
    )

    esito = await meteo.previsione(
        risorse, lat=45.07, lon=7.68, quota_m=2000, data="2026-09-20", ore_max=6, ora_inizio=8
    )

    assert [p.istante.hour for p in esito] == [8, 9, 10, 11, 12, 13]
    assert esito[0].temperatura_c == 8.0

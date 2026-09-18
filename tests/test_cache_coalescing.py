import asyncio
from dataclasses import dataclass

import httpx
import pytest
import respx

from trekking_mcp.errors import FonteNonDisponibile
from trekking_mcp.sources.http import CacheTTL

URL = "https://esempio.test/x"


async def _lascia_girare(passi: int = 20) -> None:
    for _ in range(passi):
        await asyncio.sleep(0)


@dataclass
class Rubinetto:
    arrivata: asyncio.Event
    prosegui: asyncio.Event
    uscite: list[httpx.Request]


def _rubinetto(rotta: respx.Route, risposta: httpx.Response) -> Rubinetto:
    rub = Rubinetto(asyncio.Event(), asyncio.Event(), [])

    async def gestore(request: httpx.Request) -> httpx.Response:
        rub.uscite.append(request)
        rub.arrivata.set()
        await rub.prosegui.wait()
        return risposta

    rotta.mock(side_effect=gestore)
    return rub


async def test_due_richieste_identiche_insieme_escono_una_volta_sola(httpx2_mock: respx.Router, risorse):
    rub = _rubinetto(httpx2_mock.get(url__startswith="https://esempio.test"), httpx.Response(200, json={"ok": True}))

    capofila = asyncio.create_task(risorse.http.json("GET", URL, fonte="prova", ttl_s=60))
    await rub.arrivata.wait()
    secondo = asyncio.create_task(risorse.http.json("GET", URL, fonte="prova", ttl_s=60))
    await _lascia_girare()

    rub.prosegui.set()
    esiti = await asyncio.gather(capofila, secondo)

    assert esiti == [{"ok": True}, {"ok": True}]
    assert len(rub.uscite) == 1, "un agente chiama i tool in parallelo: la seconda deve accodarsi"

    fonte = risorse.metriche.istantanea().fonti["prova"]
    assert fonte.coalescing == 1
    assert fonte.cache_miss == 1
    assert fonte.cache_hit == 0, "accodarsi non e' un cache hit: la cache era vuota"


async def test_richieste_diverse_non_si_accodano(httpx2_mock: respx.Router, risorse):
    rotta = httpx2_mock.get(url__startswith="https://esempio.test").respond(200, json={"ok": True})

    await asyncio.gather(
        risorse.http.json("GET", URL, fonte="prova", ttl_s=60, params={"a": 1}),
        risorse.http.json("GET", URL, fonte="prova", ttl_s=60, params={"a": 2}),
    )

    assert rotta.call_count == 2


async def test_chi_si_accoda_riceve_lo_stesso_errore(httpx2_mock: respx.Router, risorse_con):
    """I retry li ha gia' spesi il capofila: rifarli sarebbe martellare la fonte."""
    risorse = risorse_con(max_retry=1)
    rub = _rubinetto(httpx2_mock.get(url__startswith="https://esempio.test"), httpx.Response(503))

    capofila = asyncio.create_task(risorse.http.json("GET", URL, fonte="prova", ttl_s=60))
    await rub.arrivata.wait()
    secondo = asyncio.create_task(risorse.http.json("GET", URL, fonte="prova", ttl_s=60))
    await _lascia_girare()

    rub.prosegui.set()
    esiti = await asyncio.gather(capofila, secondo, return_exceptions=True)

    assert all(isinstance(e, FonteNonDisponibile) for e in esiti)
    assert len(rub.uscite) == 1


async def test_la_cancellazione_del_capofila_non_cancella_chi_aspetta(httpx2_mock: respx.Router, risorse):
    """Sono richieste di utenti diversi: un tool cancellato non trascina l'altro."""
    rub = _rubinetto(httpx2_mock.get(url__startswith="https://esempio.test"), httpx.Response(200, json={"ok": True}))

    capofila = asyncio.create_task(risorse.http.json("GET", URL, fonte="prova", ttl_s=60))
    await rub.arrivata.wait()
    secondo = asyncio.create_task(risorse.http.json("GET", URL, fonte="prova", ttl_s=60))
    await _lascia_girare()

    capofila.cancel()
    with pytest.raises(asyncio.CancelledError):
        await capofila

    rub.prosegui.set()
    assert await secondo == {"ok": True}, "chi aspettava non deve ereditare la cancellazione del capofila"
    assert len(rub.uscite) == 2, "deve aver rifatto la richiesta per conto proprio"


async def test_la_cache_sfratta_per_byte_non_solo_per_voci():
    cache = CacheTTL(max_entry=100, max_byte=1000)

    await cache.set("a", {"v": 1}, 60, peso=600)
    await cache.set("b", {"v": 2}, 60, peso=600)

    assert await cache.get("a") is None, "la voce piu' vecchia esce quando si sfonda il tetto"
    assert await cache.get("b") == {"v": 2}
    assert cache.byte == 600


async def test_una_risposta_piu_grande_del_tetto_non_entra():
    cache = CacheTTL(max_entry=100, max_byte=1000)
    await cache.set("a", {"v": 1}, 60, peso=100)

    await cache.set("enorme", {"v": 2}, 60, peso=5000)

    assert await cache.get("enorme") is None, "entrerebbe solo per sfrattare tutto e uscire alla voce dopo"
    assert await cache.get("a") == {"v": 1}
    assert cache.byte == 100


async def test_il_totale_resta_coerente_dopo_scadenze_e_riscritture():
    cache = CacheTTL(max_entry=100, max_byte=10_000)

    await cache.set("a", {"v": 1}, 60, peso=300)
    await cache.set("a", {"v": 2}, 60, peso=500)
    assert cache.byte == 500, "riscrivere una chiave non deve sommare due volte"

    await cache.set("b", {"v": 3}, -1, peso=200)
    assert await cache.get("b") is None
    assert cache.byte == 500, "una voce scaduta deve restituire il suo peso"

    await cache.svuota()
    assert cache.byte == 0


async def test_il_peso_arriva_dalla_risposta_grezza(httpx2_mock: respx.Router, risorse):
    corpo = {"elements": [{"id": n} for n in range(50)]}
    httpx2_mock.get(url__startswith="https://esempio.test").respond(200, json=corpo)

    await risorse.http.json("GET", URL, fonte="prova", ttl_s=60)

    assert risorse.http.cache.byte > 0, "senza peso il tetto in byte non limiterebbe nulla"


async def test_un_tetto_a_zero_non_solleva():
    """`CACHE_MAX_ENTRY=0` e' una configurazione legittima: disattiva la cache."""
    cache = CacheTTL(max_entry=0, max_byte=1000)

    await cache.set("a", {"v": 1}, 60, peso=10)

    assert await cache.get("a") is None
    assert cache.byte == 0

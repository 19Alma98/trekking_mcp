from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import Client
from mcp.server.context import ServerRequestContext
from mcp.shared.exceptions import MCPError

from trekking_mcp.__main__ import avvisa_overpass_pubblico
from trekking_mcp.config import Config
from trekking_mcp.constants import OVERPASS_URL_DEFAULT
from trekking_mcp.metriche import Metriche
from trekking_mcp.rate_limit import (
    RateLimitInbound,
    TokenBucket,
    ip_da_request,
    metodo_da_limitare,
)
from trekking_mcp.server import crea_server


class _Orologio:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def avanza(self, secondi: float) -> None:
        self.t += secondi


def test_token_bucket_accetta_fino_al_burst():
    orologio = _Orologio()
    bucket = TokenBucket(capacita=2, rpm=60, _orologio=orologio)

    assert bucket.prova() is None
    assert bucket.prova() is None
    attesa = bucket.prova()
    assert attesa is not None and attesa > 0


def test_token_bucket_si_ricarica_col_tempo():
    orologio = _Orologio()
    bucket = TokenBucket(capacita=1, rpm=60, _orologio=orologio)

    assert bucket.prova() is None
    assert bucket.prova() is not None
    orologio.avanza(1.0)
    assert bucket.prova() is None


def test_ip_da_request_legge_il_peer():
    assert ip_da_request(None) is None
    assert ip_da_request(SimpleNamespace(client=None)) is None
    assert ip_da_request(SimpleNamespace(client=SimpleNamespace(host="1.2.3.4"))) == "1.2.3.4"


def test_metodo_da_limitare():
    assert metodo_da_limitare("tools/call", {})
    assert metodo_da_limitare("resources/read", {"uri": "bollettino://aineva/IT-21-AO-01"})
    assert not metodo_da_limitare("resources/read", {"uri": "scala://pericolo-valanghe"})
    assert not metodo_da_limitare("tools/list", {})


def _ctx(*, method: str, params: dict | None, ip: str | None) -> ServerRequestContext:
    request = SimpleNamespace(client=SimpleNamespace(host=ip)) if ip else None
    return ServerRequestContext(
        session=MagicMock(),
        lifespan_context=None,
        protocol_version="2025-06-18",
        method=method,
        params=params,
        request_id=1,
        request=request,
    )


async def test_middleware_blocca_tools_call_oltre_il_burst():
    config = replace(Config(), http_rate_limit_rpm=60, http_rate_limit_burst=2)
    metriche = Metriche()
    mw = RateLimitInbound(config, metriche)
    call_next = AsyncMock(return_value={"ok": True})

    ctx = _ctx(method="tools/call", params={"name": "x"}, ip="10.0.0.1")
    assert await mw(ctx, call_next) == {"ok": True}
    assert await mw(ctx, call_next) == {"ok": True}
    esito = await mw(ctx, call_next)

    assert isinstance(esito, dict)
    assert esito.get("isError") is True
    testo = esito["content"][0]["text"]
    assert "Troppe richieste" in testo
    assert metriche.istantanea().rate_limit_inbound == 1
    assert call_next.await_count == 2


async def test_middleware_senza_request_non_limita():
    config = replace(Config(), http_rate_limit_rpm=60, http_rate_limit_burst=1)
    mw = RateLimitInbound(config, Metriche())
    call_next = AsyncMock(return_value={"ok": True})
    ctx = _ctx(method="tools/call", params={"name": "x"}, ip=None)

    for _ in range(5):
        assert await mw(ctx, call_next) == {"ok": True}
    assert call_next.await_count == 5


async def test_middleware_blocca_bollettino_con_mcp_error():
    config = replace(Config(), http_rate_limit_rpm=60, http_rate_limit_burst=1)
    mw = RateLimitInbound(config, Metriche())
    call_next = AsyncMock(return_value={"ok": True})
    ctx = _ctx(
        method="resources/read",
        params={"uri": "bollettino://aineva/IT-21-AO-01"},
        ip="10.0.0.2",
    )

    assert await mw(ctx, call_next) == {"ok": True}
    with pytest.raises(MCPError, match="Troppe richieste"):
        await mw(ctx, call_next)


async def test_client_senza_peer_http_non_e_limitato(risorse_con, monkeypatch):
    """Il Client in-process non ha Request: il tetto non si applica (stdio)."""
    risorse = risorse_con(http_rate_limit_rpm=60, http_rate_limit_burst=1)

    async def _vuoto(*_a, **_k):
        return []

    monkeypatch.setattr("trekking_mcp.tools.sentieri.overpass.cerca_sentieri", _vuoto)

    async with Client(crea_server(risorse=risorse)) as client:
        for _ in range(4):
            esito = await client.call_tool("cerca_sentieri", {"lat": 45.5, "lon": 7.5})
            assert not esito.is_error


async def test_client_con_ip_simulato_viene_limitato(risorse_con, monkeypatch):
    risorse = risorse_con(http_rate_limit_rpm=60, http_rate_limit_burst=2)
    monkeypatch.setattr("trekking_mcp.rate_limit.ip_da_request", lambda _r: "203.0.113.9")

    async def _vuoto(*_a, **_k):
        return []

    monkeypatch.setattr("trekking_mcp.tools.sentieri.overpass.cerca_sentieri", _vuoto)

    async with Client(crea_server(risorse=risorse)) as client:
        assert not (await client.call_tool("cerca_sentieri", {"lat": 45.5, "lon": 7.5})).is_error
        assert not (await client.call_tool("cerca_sentieri", {"lat": 45.5, "lon": 7.5})).is_error
        esito = await client.call_tool("cerca_sentieri", {"lat": 45.5, "lon": 7.5})

    assert esito.is_error
    testo = "".join(c.text for c in esito.content if getattr(c, "text", None))
    assert "Troppe richieste" in testo
    assert risorse.metriche.istantanea().rate_limit_inbound == 1


def test_avvisa_overpass_pubblico_solo_fuori_localhost(caplog):
    import logging

    logger = logging.getLogger("test.overpass.warn")
    with caplog.at_level(logging.WARNING, logger="test.overpass.warn"):
        avvisa_overpass_pubblico("127.0.0.1", OVERPASS_URL_DEFAULT, logger)
        assert not caplog.records
        avvisa_overpass_pubblico("0.0.0.0", "https://overpass.example.org/api/interpreter", logger)
        assert not caplog.records
        avvisa_overpass_pubblico("0.0.0.0", OVERPASS_URL_DEFAULT, logger)
    assert any("overpass-api.de" in r.message for r in caplog.records)

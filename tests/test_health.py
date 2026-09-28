from __future__ import annotations

import httpx

from trekking_mcp import __version__
from trekking_mcp.server import crea_server


async def test_health_risponde_ok(risorse):
    mcp = crea_server(risorse=risorse)
    app = mcp.streamable_http_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        risposta = await client.get("/health")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["status"] == "ok"
    assert corpo["version"] == __version__

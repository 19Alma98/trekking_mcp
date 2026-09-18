"""`ttlMs` / `cacheScope`: quello che il server dice al client su quanto vale un dato.

Tutto passa da un `Client` vero e non dalle funzioni interne: i campi viaggiano
sul filo in camelCase, e l'unico modo di sapere che ci arrivano e' rileggerli
dall'altra parte. Se l'SDK cambiasse forma, questi test lo direbbero.
"""

from __future__ import annotations

from dataclasses import replace

from mcp import Client

from trekking_mcp.cache import MS, TTL_ELENCHI_MS, TTL_SCALE_MS, freschezza_resource
from trekking_mcp.config import Config
from trekking_mcp.server import crea_server

# --- gli elenchi -------------------------------------------------------------


async def test_gli_elenchi_dichiarano_una_freschezza(risorse):
    """Registrati in crea_server() e mai piu' toccati: il client puo' tenerli."""
    async with Client(crea_server(risorse=risorse)) as client:
        elenchi = [
            await client.list_tools(),
            await client.list_prompts(),
            await client.list_resources(),
            await client.list_resource_templates(),
        ]

    for esito in elenchi:
        assert esito.ttl_ms == TTL_ELENCHI_MS
        assert esito.cache_scope == "public"


# --- le resource, una per una ------------------------------------------------


async def test_un_documento_di_riferimento_si_puo_tenere_a_lungo(risorse):
    async with Client(crea_server(risorse=risorse)) as client:
        esito = await client.read_resource("scala://difficolta-escursionistica")

    assert esito.ttl_ms == TTL_SCALE_MS
    assert esito.cache_scope == "public"


async def test_le_metriche_non_si_cachano(risorse):
    """Cambiano a ogni chiamata a una fonte: un valore vecchio non serve a niente."""
    async with Client(crea_server(risorse=risorse)) as client:
        esito = await client.read_resource("metriche://fonti")

    assert esito.ttl_ms == 0
    assert esito.cache_scope == "private"


async def test_resource_diverse_ricevono_hint_diversi(risorse):
    """Il punto del middleware: un hint per metodo non basterebbe."""
    async with Client(crea_server(risorse=risorse)) as client:
        scala = await client.read_resource("scala://pericolo-valanghe")
        metriche = await client.read_resource("metriche://fonti")

    assert scala.ttl_ms != metriche.ttl_ms


# --- la tabella, senza passare dal protocollo --------------------------------


def test_il_bollettino_eredita_il_ttl_della_cache_interna():
    """Un bollettino non puo' valere 30 minuti per il server e un'ora per il client."""
    config = replace(Config(), ttl_bollettino_s=1800)

    hint = freschezza_resource("bollettino://aineva/IT-21-AO-01", config)

    assert hint.ttl_ms == 1800 * MS
    assert hint.scope == "public"


def test_il_ttl_del_bollettino_segue_la_configurazione():
    config = replace(Config(), ttl_bollettino_s=60)

    assert freschezza_resource("bollettino://aineva/X", config).ttl_ms == 60 * MS


def test_uno_schema_sconosciuto_non_si_cacha():
    """Default prudente: se non so cos'e', non dico al client di tenerlo."""
    hint = freschezza_resource("boh://qualcosa", Config())

    assert hint.ttl_ms == 0
    assert hint.scope == "private"

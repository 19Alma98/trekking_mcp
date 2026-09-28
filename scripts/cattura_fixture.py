#!/usr/bin/env python3
"""Scarica risposte CAAML/Overpass reali, le riduce e le scrive in tests/fixtures/.

Uso (manuale, non in CI)::

    uv run python scripts/cattura_fixture.py

Exit non-zero se una fonte non restituisce elementi utili.

Fuori stagione i feed ``latest`` AINEVA/SLF possono essere vuoti o 404.
In quel caso:

- SLF: si usa ``/api/bulletin-list/caaml/{lang}/json`` (archivio recente)
- AINEVA: se ``albina_files/latest`` non risponde, si scarica un CAAML v6
  reale dal repo albina-server (stesso schema ALBINA usato da AINEVA),
  documentato nel ``.meta.json``
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx2

from trekking_mcp.config import Config
from trekking_mcp.constants import UA_DEFAULT

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

# Area Biellese (Oropa / Valle Cervo / Sessera).
BBOX_BIELLA = (45.50, 7.85, 45.75, 8.20)  # sud, ovest, nord, est
LAT_RICOVERI, LON_RICOVERI = 45.62, 7.98  # intorno a Oropa
RAGGIO_RICOVERI_M = 15_000
MAX_BULLETIN_PER_FEED = 3
MAX_GEOM_NODES = 800

ALBINA_CAAML_FALLBACK = (
    "https://gitlab.com/api/v4/projects/albina-euregio%2Falbina-server"
    "/repository/files/" + quote("src/test/resources/2026-04-13.caaml.v6.json", safe="") + "/raw?ref=master"
)


def _scrivi(percorso: Path, payload: dict[str, Any] | list[Any]) -> None:
    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"scritto {percorso.relative_to(ROOT)} ({percorso.stat().st_size} byte)")


def _meta(percorso: Path, **campi: Any) -> None:
    meta = {
        "catturato_il": datetime.now(UTC).isoformat(),
        **campi,
    }
    _scrivi(percorso.with_name(percorso.stem + ".meta.json"), meta)


def _client() -> httpx2.Client:
    return httpx2.Client(
        headers={"User-Agent": UA_DEFAULT, "Accept": "application/json"},
        timeout=90.0,
        follow_redirects=True,
    )


def _slice_caaml(
    grezzo: dict[str, Any],
    *,
    prefissi: tuple[str, ...],
    massimo: int,
) -> tuple[dict[str, Any], list[str]]:
    bulletins = grezzo.get("bulletins") or []
    scelti: list[dict[str, Any]] = []
    zone: list[str] = []
    for b in bulletins:
        regioni = b.get("regions") or []
        ids = [str(r.get("regionID") or "") for r in regioni]
        if not any(any(z.startswith(p) for p in prefissi) for z in ids):
            continue
        scelti.append(b)
        for z in ids:
            if any(z.startswith(p) for p in prefissi) and z not in zone:
                zone.append(z)
        if len(scelti) >= massimo:
            break
    if not scelti:
        raise SystemExit(f"nessun bulletin con regioni {prefissi!r} nel feed")
    return {"bulletins": scelti}, zone


def _feed_da_lista(lista: list[Any]) -> dict[str, Any]:
    """SLF bulletin-list: array di envelope `{bulletins: [...]}`."""
    for env in lista:
        if isinstance(env, dict) and env.get("bulletins"):
            return {"bulletins": list(env["bulletins"])}
    raise SystemExit("bulletin-list senza bulletin utili")


def cattura_aineva(client: httpx2.Client, config: Config) -> None:
    url_latest = f"{config.aineva_url}/albina_files/latest/it.json"
    fonte = url_latest
    grezzo: dict[str, Any] | None = None
    nota = None

    r = client.get(url_latest)
    if r.status_code == 200:
        try:
            grezzo = r.json()
        except json.JSONDecodeError:
            grezzo = None
        if grezzo and grezzo.get("bulletins"):
            pass
        else:
            grezzo = None
            nota = f"latest vuoto o non-JSON (HTTP {r.status_code})"
    else:
        nota = f"latest HTTP {r.status_code}"

    if grezzo is None:
        print(f"  AINEVA latest non usabile ({nota}); fallback ALBINA CAAML v6…")
        fonte = ALBINA_CAAML_FALLBACK
        r = client.get(fonte)
        r.raise_for_status()
        grezzo = r.json()
        if not grezzo.get("bulletins"):
            raise SystemExit("fallback ALBINA senza bulletins")

    try:
        slice_, zone = _slice_caaml(grezzo, prefissi=("IT-21-",), massimo=MAX_BULLETIN_PER_FEED)
    except SystemExit:
        slice_, zone = _slice_caaml(grezzo, prefissi=("IT-",), massimo=MAX_BULLETIN_PER_FEED)

    out = FIXTURES / "caaml" / "aineva_latest_slice.json"
    _scrivi(out, slice_)
    _meta(
        out,
        url=fonte,
        provider="aineva",
        zone_tenute=zone,
        bulletin=len(slice_["bulletins"]),
        nota=nota,
    )


def cattura_slf(client: httpx2.Client, config: Config) -> None:
    url_latest = f"{config.slf_url}/it/json"
    fonte = url_latest
    nota = None
    grezzo: dict[str, Any] | None = None

    r = client.get(url_latest)
    r.raise_for_status()
    grezzo = r.json()
    if not grezzo.get("bulletins"):
        nota = "latest vuoto (fuori stagione); uso bulletin-list"
        print(f"  SLF {nota}")
        url_lista = "https://aws.slf.ch/api/bulletin-list/caaml/it/json"
        fonte = url_lista
        r = client.get(url_lista)
        r.raise_for_status()
        grezzo = _feed_da_lista(r.json())

    slice_, zone = _slice_caaml(grezzo, prefissi=("CH-",), massimo=MAX_BULLETIN_PER_FEED)
    out = FIXTURES / "caaml" / "slf_latest_slice.json"
    _scrivi(out, slice_)
    _meta(
        out,
        url=fonte,
        provider="slf",
        zone_tenute=zone,
        bulletin=len(slice_["bulletins"]),
        nota=nota,
    )


def _overpass(client: httpx2.Client, config: Config, ql: str, *, tentativi: int = 4) -> dict[str, Any]:
    ultimo: Exception | None = None
    for i in range(tentativi):
        try:
            r = client.post(config.overpass_url, data={"data": ql})
            if r.status_code in {429, 502, 503, 504}:
                raise httpx2.HTTPStatusError(
                    f"HTTP {r.status_code}",
                    request=r.request,
                    response=r,
                )
            r.raise_for_status()
            return r.json()
        except (httpx2.HTTPStatusError, httpx2.TransportError) as exc:
            ultimo = exc
            attesa = 2**i
            print(f"  Overpass retry {i + 1}/{tentativi} tra {attesa}s ({exc})")
            time.sleep(attesa)
    assert ultimo is not None
    raise ultimo


def _conta_punti_geom(rel: dict[str, Any]) -> int:
    n = 0
    for m in rel.get("members") or []:
        n += len(m.get("geometry") or [])
    return n


def cattura_overpass(client: httpx2.Client, config: Config) -> None:
    sud, ovest, nord, est = BBOX_BIELLA
    ql_centro = (
        f"[out:json][timeout:60];"
        f'relation["route"="hiking"]["type"="route"]["ref"]({sud},{ovest},{nord},{est});'
        f"out tags center;"
    )
    dati_centro = _overpass(client, config, ql_centro)
    relazioni = [el for el in dati_centro.get("elements") or [] if el.get("type") == "relation" and el.get("tags")]
    if not relazioni:
        raise SystemExit("Overpass: nessuna relation route=hiking con ref nella bbox Biella")

    relazioni.sort(key=lambda el: (0 if str((el.get("tags") or {}).get("ref", "")).isdigit() else 1, el.get("id", 0)))
    out_centro = FIXTURES / "overpass" / "relation_centro.json"
    out_geom = FIXTURES / "overpass" / "relation_geom.json"

    scelta: dict[str, Any] | None = None
    rel_geom: dict[str, Any] | None = None
    osm_id = 0
    punti = 0
    for candidata in relazioni[:15]:
        cid = int(candidata["id"])
        try:
            dati_geom = _overpass(client, config, f"[out:json][timeout:90];relation({cid});out geom;")
        except (httpx2.HTTPStatusError, httpx2.TransportError) as exc:
            print(f"  salto relation {cid}: {exc}")
            continue
        rg = next((el for el in dati_geom.get("elements") or [] if el.get("type") == "relation"), None)
        if rg is None:
            continue
        p = _conta_punti_geom(rg)
        if 2 <= p <= MAX_GEOM_NODES:
            scelta, rel_geom, osm_id, punti = candidata, rg, cid, p
            break
        print(f"  relation {cid}: {p} punti, fuori range")

    if scelta is None or rel_geom is None:
        raise SystemExit("Overpass: nessuna relation Biella con geometria gestibile")

    _scrivi(out_centro, {"elements": [scelta]})
    _meta(
        out_centro,
        url=config.overpass_url,
        osm_relation_id=osm_id,
        ref=(scelta.get("tags") or {}).get("ref"),
        bbox=list(BBOX_BIELLA),
    )
    _scrivi(out_geom, {"elements": [rel_geom]})
    _meta(out_geom, url=config.overpass_url, osm_relation_id=osm_id, punti_geometria=punti)

    ql_ricoveri = (
        f"[out:json][timeout:60];("
        f'node["tourism"~"^(alpine_hut|wilderness_hut)$"](around:{RAGGIO_RICOVERI_M},{LAT_RICOVERI},{LON_RICOVERI});'
        f'way["tourism"~"^(alpine_hut|wilderness_hut)$"](around:{RAGGIO_RICOVERI_M},{LAT_RICOVERI},{LON_RICOVERI});'
        f'node["amenity"="shelter"]["shelter_type"="basic_hut"](around:{RAGGIO_RICOVERI_M},{LAT_RICOVERI},{LON_RICOVERI});'
        f");out tags center;"
    )
    dati_ric = _overpass(client, config, ql_ricoveri)
    con_tag = [el for el in dati_ric.get("elements") or [] if el.get("tags")]
    if not con_tag:
        raise SystemExit("Overpass: nessun ricovero nella zona Biella")
    con_tag = con_tag[:15]
    out_ric = FIXTURES / "overpass" / "ricoveri_nodo.json"
    _scrivi(out_ric, {"elements": con_tag})
    _meta(
        out_ric,
        url=config.overpass_url,
        lat=LAT_RICOVERI,
        lon=LON_RICOVERI,
        raggio_m=RAGGIO_RICOVERI_M,
        elementi=len(con_tag),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    config = Config()
    with _client() as client:
        print("cattura AINEVA…")
        cattura_aineva(client, config)
        print("cattura SLF…")
        cattura_slf(client, config)
        print("cattura Overpass…")
        cattura_overpass(client, config)
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())

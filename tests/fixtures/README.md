# Fixture da risposte reali

JSON catturati da fonti ufficiali e **ridotti** (slice), versionati nel repo
perché i test di regressione del parsing restino **offline**.

## Fonti e licenze

| File | Fonte | Licenza |
|------|--------|---------|
| `caaml/aineva_latest_slice.json` | AINEVA / ALBINA CAAML v6 | open data bollettini ufficiali |
| `caaml/slf_latest_slice.json` | WSL-SLF CAAML v6 | CC BY 4.0 |
| `overpass/*.json` | OpenStreetMap via Overpass | ODbL |

## Perché slice e non il feed intero

Il `latest.json` AINEVA e il feed SLF contengono tutte le zone del giorno:
sono grandi e cambiano spesso. Qui teniamo 1–3 bulletin sufficienti a
esercitare `normalizza` / `leggi_bollettino`. Overpass `out geom` è limitato
a una relation corta.

I test assertano **invarianti di struttura** (zone, gradi, polilinea), non il
testo meteo del giorno.

## Ri-cattura

```bash
uv run python scripts/cattura_fixture.py
```

Lo script scrive anche `*.meta.json` (url, data, zone/id tenuti). Non va
eseguito in CI.

Fuori stagione, se `albina_files/latest` AINEVA è 404/vuoto, lo script usa un
CAAML v6 reale dal repo [albina-server](https://gitlab.com/albina-euregio/albina-server)
(stesso schema ALBINA). Per SLF usa `bulletin-list` quando `latest` è vuoto.

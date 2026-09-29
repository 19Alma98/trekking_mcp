# trekking-mcp

[![CI](https://github.com/19Alma98/trekking_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/19Alma98/trekking_mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/trekking-mcp.svg)](https://pypi.org/project/trekking-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-black)](https://registry.modelcontextprotocol.io/)

*[Italiano](README.md)*

![Demo: inspecting the MCP server](docs/demo.gif)

[MCP](https://modelcontextprotocol.io) server for hiking in Italy: numbered trails, mountain huts and bivouacs, avalanche bulletins and elevation weather, for use with an AI assistant.

> **Safety notice.** Avalanche bulletins are official safety documents. When it reports them, it does not interpret them and does not assess risk. It is not a substitute for the full bulletin, for proper training, or for judgement on the ground. Use it to prepare a trip, never to decide whether to go.

Code, docstrings and comments are in Italian on purpose (domain terms). This file and [DEVELOPMENT.md](DEVELOPMENT.md) are the way in if you don't read Italian; a short glossary is at the bottom.

## What you can ask

For example:

- trails near a village or a peak
- details and elevation profile of a route
- huts and bivouacs in the area
- elevation weather and avalanche bulletin for the day of the trip

## How to use it

You need [uv](https://docs.astral.sh/uv/). No API key.

```bash
uvx trekking-mcp
```

### Cursor / Claude Code

Add this block to your MCP config:

```json
{
  "mcpServers": {
    "trekking": {
      "command": "uvx",
      "args": ["trekking-mcp"]
    }
  }
}
```

Then ask something like: *«What trails are there toward Monte Rosso starting from Oropa?»*

## Tools

| Tool | What it is for |
|---|---|
| `cerca_localita` | Place name to coordinates |
| `cerca_sentieri` | Numbered trails around a point |
| `sentieri_verso_localita` | From a place name: nearby trails and huts (recommended entry point) |
| `dettaglio_sentiero` | Details of a trail |
| `profilo_altimetrico` | Length and elevation gain |
| `cerca_ricoveri` | Huts, bivouacs and shelters |
| `zona_valanghe_da_coordinate` | Avalanche bulletin zone from a point |
| `bollettino_valanghe` | Current bulletin for a zone |
| `meteo_quota` | Hourly forecast at elevation |
| `valuta_gita` | Summarises trail, weather and avalanches for a date |

## Sources

Data from [OpenStreetMap](https://www.openstreetmap.org), [AINEVA](https://bollettini.aineva.it), [WSL-SLF](https://www.slf.ch) (Switzerland), [Open-Meteo](https://open-meteo.com), [EAWS Regions](https://regions.avalanches.org) and [Nominatim](https://nominatim.openstreetmap.org).

Numbered CAI trails are those mapped by the OSM community: coverage is uneven, and a missing trail does not mean the trail does not exist.

## Licence

MIT.

To contribute or for development details: [DEVELOPMENT.md](DEVELOPMENT.md).

## Glossary of Italian identifiers

| Italian | English |
|---|---|
| `sentiero` | trail |
| `ricovero` / `rifugio` / `bivacco` | shelter / staffed hut / unstaffed bivouac |
| `gita` / `uscita` | trip / outing |
| `bollettino` | (avalanche) bulletin |
| `valanghe` | avalanches |
| `grado_pericolo` | danger level (EAWS 1–5) |
| `difficolta` | difficulty (CAI scale T/E/EE/EEA) |
| `zona` / `micro-regione` | avalanche zone / EAWS micro-region |
| `quota` / `dislivello` | elevation / elevation gain |
| `profilo altimetrico` | elevation profile |
| `meteo` / `zero termico` / `raffica` | weather / freezing level / gust |
| `localita` / `toponimo` | place / place name |
| `fonte` | (data) source |
| `cerca` / `leggi` / `esegui` | search / read / execute |

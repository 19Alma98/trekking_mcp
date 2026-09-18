# trekking-mcp

*[Italiano](README.md)*

A [Model Context Protocol](https://modelcontextprotocol.io) server (spec revision
`2026-07-28`, Python `mcp` SDK 2.x) for hiking in the Italian Alps and Apennines:
numbered trails, mountain huts and bivouacs, avalanche bulletins and
elevation-corrected weather, exposed to an AI assistant as tools, resources and
prompts.

> **Safety notice.** Avalanche bulletins are official safety documents. This
> project re-reads and normalises them; it does not interpret them and does not
> produce risk assessments. It is not a substitute for the full bulletin, for
> proper training, or for judgement on the ground. Use it to *prepare* a trip,
> never to decide whether to go.

**A note on language.** The code, docstrings and comments are in Italian, on
purpose: the domain is Italian and its terms (*rifugio*, *bivacco*, *EEA*, *grado
di pericolo*) have no clean English equivalents. Protocol terms (tool, resource,
elicitation) and OSM tags stay in English. This file and
[DEVELOPMENT.md](DEVELOPMENT.md) are the way in if you don't read Italian; the
glossary at the bottom covers the identifiers you will meet in the source.

## What this repo demonstrates

It is not a 1:1 wrapper over an API. It covers all three protocol primitives plus
a few mechanisms you rarely see implemented:

| | |
|---|---|
| **Tools** | 10 tools, two of which compose several sources into one result |
| **Resources** | Static reference documents + a resource template with a parameterised URI |
| **Prompts** | Reusable workflows that fix the *method*, not just the tone |
| **Elicitation** | The server asks the user for data *mid-call*, via dependency injection, with the choices as `enum` in the schema |
| **Completions** | Autocomplete for avalanche-zone IDs, narrowed by the provider already chosen |
| **Structured output** | Every tool has an `outputSchema` derived from Pydantic models |
| **Dual transport** | stdio and Streamable HTTP from the same `crea_server()` |
| **Observability** | p50/p95 latency, 429s and cache hit rate per source, exposed as a resource |
| **Cache hints** | Every response declares how long it is worth (`ttlMs`/`cacheScope`), resource by resource |
| **Request-state sealing** | Shared, rotatable keys so a two-round-trip elicitation survives a restart or a second replica |
| **Client included** | A minimal MCP client, to show both sides of the protocol |
| **Geometry** | Point-in-polygon and elevation profiles in pure Python, no binary dependencies |

## Install

```bash
git clone https://github.com/19Alma98/trekking_mcp
cd trekking_mcp
uv sync            # or: pip install -e ".[dev]"
```

No API keys: every default source is open data.

## Use with Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "trekking": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/trekking_mcp", "run", "trekking-mcp"]
    }
  }
}
```

Or as a remote server:

```bash
trekking-mcp --transport http --port 8000            # 127.0.0.1 only

# exposed to other machines: you must declare who may call
trekking-mcp --transport http --host 0.0.0.0 \
  --allow-host trekking.example.org:* \
  --allow-origin https://app.example.org

# with more than one replica: the keys that seal requestState must be shared,
# otherwise an elicitation started on one replica dies on the other
export TREKKING_MCP_STATE_KEYS="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

The second command **is refused** without `--allow-host`: the SDK enables DNS
rebinding protection only when the bind is on localhost — that is, precisely when
it isn't needed. See [DEVELOPMENT.md](DEVELOPMENT.md) §3.18.

## Tools

| Tool | What it does |
|---|---|
| `cerca_localita` | Place name to coordinates: huts, peaks, passes, villages |
| `cerca_sentieri` | Numbered trails within a radius, filterable by number, maintainer and maximum difficulty |
| `sentieri_verso_localita` | Geocoding + trails + huts in one call: the entry point when the destination is a name |
| `dettaglio_sentiero` | Full data for one OSM relation |
| `profilo_altimetrico` | Real length and elevation gain, sampling elevations along the track |
| `cerca_ricoveri` | Staffed huts, bivouacs and shelters within a radius |
| `zona_valanghe_da_coordinate` | From a point to the EAWS micro-region the bulletin is issued for |
| `bollettino_valanghe` | Current bulletin for a zone, from CAAML v6 |
| `meteo_quota` | Hourly forecast corrected for elevation, with freezing level and gusts |
| `valuta_gita` | Composes all of the above for one trail and one date |

`meteo_quota` does not return the first hours of the Open-Meteo series, which
starts at midnight: it starts from the current hour when the date is today, from
06:00 for a future day, or from `ora_inizio` when given. You don't plan a trip by
looking at the night. See [DEVELOPMENT.md](DEVELOPMENT.md) §3.27.

Resources are `scala://pericolo-valanghe`, `scala://difficolta-escursionistica`,
`metriche://fonti` (per-source latency, errors and hit rate) and the template
`bollettino://{provider}/{zona_id}`, whose two arguments autocomplete each other:
pick `slf` and `zona_id` only offers Swiss zones.

## Elicitation, briefly

`valuta_gita` needs to know what difficulty the group can handle and whether they
carry a transceiver, shovel and probe. That is information the model **cannot
infer** and must not invent. The parameter is annotated like this:

```python
profilo: Annotated[ProfiloUscita, Resolve(chiedi_profilo)]
```

The parameter does not appear in the tool's input schema, so the model does not
even know it exists. Before running the body, the framework runs the resolver,
which returns an `Elicit[ProfiloUscita]` marker: the question is forwarded to the
client, the user answers, the value is injected. If the user declines, the call
stops.

## Data sources and attribution

| Source | Provides | Licence |
|---|---|---|
| [OpenStreetMap](https://www.openstreetmap.org) via [Overpass](https://overpass-api.de) | Trails (`route=hiking`), huts, bivouacs | ODbL, attribution required |
| [AINEVA](https://bollettini.aineva.it) | Avalanche bulletins for the Italian Alps | Open data, CAAML v6 EAWS profile |
| [WSL-SLF](https://www.slf.ch) | Swiss avalanche bulletins | CC BY 4.0 |
| [Open-Meteo](https://open-meteo.com) | Hourly forecast and elevation model | CC BY 4.0 |
| [EAWS Regions](https://regions.avalanches.org) | Avalanche zone perimeters | Open data |
| [Nominatim](https://nominatim.openstreetmap.org) | Place-name geocoding | ODbL, usage policy |

Numbered CAI trails are mapped **by the OSM community**: this project accesses no
proprietary Club Alpino Italiano data, and the CAI exposes no public API.
Coverage is uneven, and a missing trail does not mean the trail does not exist.

## Development

```bash
uv run pytest              # tests
uv run ruff check .        # lint
uv run ruff format --check .
uv run mypy                # type check
uv run python client/ispeziona.py   # minimal MCP client: lists tools and resources
```

These are the same commands CI runs, against the same resolution: `uv.lock` is
committed and CI installs with `uv sync --frozen`, so tool versions are identical
to local ones.

Architecture, design decisions and roadmap: [DEVELOPMENT.md](DEVELOPMENT.md).

## Glossary of Italian identifiers

The words you need to read the source. Domain nouns keep their Italian form
because that is what they are called on the mountain and in the bulletins.

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
| `risorse` | shared resources (the DI container), not MCP resources |
| `crea_server` / `registra` | create server / register |
| `cerca` / `leggi` / `esegui` | search / read / execute |
| `segnale` / `avvertenza` | warning signal / safety notice |
| `freschezza` | freshness (`ttlMs`/`cacheScope`) |
| `metriche` / `latenza` / `chiamate` | metrics / latency / calls |
| `riquadro` / `raggio` | bounding box / radius |
| `errore previsto` | expected error (as opposed to a bug) |

## Licence

MIT.

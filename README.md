# trekking-mcp

[![CI](https://github.com/19Alma98/trekking_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/19Alma98/trekking_mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/trekking-mcp.svg)](https://pypi.org/project/trekking-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP-Registry-black)](https://registry.modelcontextprotocol.io/)

<!-- mcp-name: io.github.19Alma98/trekking-mcp -->

*[English](README.en.md)*

![Demo: ispezione del server MCP](docs/demo.gif)

Server [MCP](https://modelcontextprotocol.io) per l'escursionismo sul territorio italiano: sentieri numerati, rifugi e bivacchi, bollettini valanghe e meteo di quota, da usare con un assistente AI.

> **Avvertenza.** I bollettini valanghe sono documenti ufficiali di sicurezza. Questo progetto li riporta, non li interpreta e non valuta il rischio. Non sostituisce il bollettino integrale, la formazione specifica, ne' il giudizio sul terreno. Usalo per preparare una gita, mai per decidere se farla.

## Cosa puoi fare

Chiedere all'assistente, ad esempio:

- dove sono i sentieri vicino a un paese o a una cima
- dettagli e profilo altimetrico di un percorso
- rifugi e bivacchi nella zona
- meteo in quota e bollettino valanghe per la data della gita

## Come usarlo

Serve [uv](https://docs.astral.sh/uv/). Nessuna API key.

```bash
uvx trekking-mcp
```

### Cursor / Claude Code

Aggiungi questo blocco alla configurazione MCP:

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

Poi chiedi qualcosa come: *«Che sentieri ci sono verso il Monte Rosso partendo da Oropa?»*

## Tool

| Tool | A cosa serve |
|---|---|
| `cerca_localita` | Trova le coordinate di un toponimo |
| `cerca_sentieri` | Sentieri numerati intorno a un punto |
| `sentieri_verso_localita` | Da un nome di luogo: sentieri e rifugi vicini (il punto di partenza consigliato) |
| `dettaglio_sentiero` | Dettagli di un sentiero |
| `profilo_altimetrico` | Lunghezza e dislivello |
| `cerca_ricoveri` | Rifugi, bivacchi e ripari |
| `zona_valanghe_da_coordinate` | Zona del bollettino valanghe da un punto |
| `bollettino_valanghe` | Bollettino corrente di una zona |
| `meteo_quota` | Previsione oraria in quota |
| `valuta_gita` | Riassume sentiero, meteo e valanghe per una data |

## Fonti

Dati da [OpenStreetMap](https://www.openstreetmap.org), [AINEVA](https://bollettini.aineva.it), [WSL-SLF](https://www.slf.ch) (Svizzera), [Open-Meteo](https://open-meteo.com), [EAWS Regions](https://regions.avalanches.org) e [Nominatim](https://nominatim.openstreetmap.org).

I sentieri numerati CAI sono quelli mappati dalla community OSM: la copertura non e' uniforme e un sentiero assente dalla mappa non significa che non esista.

## Licenza

MIT.

Per contribuire o dettagli di sviluppo: [DEVELOPMENT.md](DEVELOPMENT.md).

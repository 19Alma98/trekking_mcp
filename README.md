# trekking-mcp

Server [Model Context Protocol](https://modelcontextprotocol.io) per l'escursionismo sulle Alpi e sugli Appennini italiani: sentieri numerati, rifugi e bivacchi, bollettini valanghe e meteo di quota, esposti a un assistente AI come tool, resource e prompt.

> **Avvertenza.** I bollettini valanghe sono documenti ufficiali di sicurezza. Questo progetto li rilegge e li normalizza, non li interpreta e non produce valutazioni del rischio. Non sostituisce il bollettino integrale, la formazione specifica, ne' il giudizio sul terreno. Usalo per preparare una gita, mai per decidere se farla.

## Cosa mostra questo repo

Non e' un wrapper 1:1 su una API. Copre i tre primitivi del protocollo e un paio di meccanismi che si vedono raramente:

| | |
|---|---|
| **Tools** | 9 tool, uno dei quali compone sei fonti diverse in un unico risultato |
| **Resources** | Documenti di riferimento statici + una resource template con URI parametrico |
| **Prompts** | Workflow riutilizzabili che fissano il metodo, non solo il tono |
| **Elicitation** | Il server chiede dati all'utente *a meta' chiamata*, via dependency injection |
| **Structured output** | Ogni tool ha un `outputSchema` derivato dai modelli Pydantic |
| **Dual transport** | stdio e Streamable HTTP dallo stesso `crea_server()` |
| **Client incluso** | Un client MCP minimale, per dimostrare di conoscere entrambi i lati |
| **Geometria** | Point-in-polygon e profili altimetrici in Python puro, senza dipendenze binarie |

## Installazione

```bash
git clone https://github.com/19Alma98/trekking_mcp
cd trekking_mcp
uv sync            # oppure: pip install -e ".[dev]"
```

Nessuna API key richiesta: tutte le fonti di default sono aperte.

## Uso con Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "trekking": {
      "command": "uv",
      "args": ["--directory", "/percorso/assoluto/trekking_mcp", "run", "trekking-mcp"]
    }
  }
}
```

In alternativa, come server remoto:

```bash
trekking-mcp --transport http --port 8000
```

## Tool disponibili

| Tool | Cosa fa |
|---|---|
| `cerca_localita` | Da un toponimo alle coordinate: rifugi, cime, valichi, paesi |
| `cerca_sentieri` | Sentieri numerati in un raggio, filtrabili per numero, ente e difficolta' massima |
| `dettaglio_sentiero` | Dati completi di una relation OSM |
| `profilo_altimetrico` | Lunghezza reale e dislivello, campionando le quote sul tracciato |
| `cerca_ricoveri` | Rifugi gestiti, bivacchi e ripari entro un raggio |
| `zona_valanghe_da_coordinate` | Da un punto alla micro-regione EAWS del bollettino |
| `bollettino_valanghe` | Bollettino corrente di una zona, da CAAML v6 |
| `meteo_quota` | Previsione oraria corretta per l'elevazione, con zero termico e raffiche |
| `valuta_gita` | Compone tutto quanto sopra per un sentiero e una data |

Il flusso tipico non richiede che l'utente conosca un solo codice: `cerca_localita`
per trovare il punto, `cerca_sentieri` per i percorsi attorno, `valuta_gita` per il
resto. La zona del bollettino viene dedotta dalle coordinate.

Le resource sono `scala://pericolo-valanghe`, `scala://difficolta-escursionistica` e la template `bollettino://{provider}/{zona_id}`.

## L'elicitation, in breve

`valuta_gita` ha bisogno di sapere che difficolta' regge il gruppo e se ha ARTVA, pala e sonda. Sono informazioni che il modello **non puo' dedurre** e che non deve inventare. Il parametro e' annotato cosi':

```python
profilo: Annotated[ProfiloUscita, Resolve(chiedi_profilo)]
```

Il parametro non compare nello schema di input del tool, quindi il modello non sa nemmeno che esiste. Prima di eseguire il corpo, il framework esegue il resolver, che restituisce un marker `Elicit[ProfiloUscita]`: la domanda viene inoltrata al client, l'utente risponde, il valore viene iniettato. Se l'utente rifiuta, la chiamata si interrompe.

## Fonti dati e attribuzioni

| Fonte | Cosa fornisce | Licenza |
|---|---|---|
| [OpenStreetMap](https://www.openstreetmap.org) via [Overpass](https://overpass-api.de) | Sentieri (`route=hiking`), rifugi, bivacchi | ODbL, attribuzione obbligatoria |
| [AINEVA](https://bollettini.aineva.it) | Bollettini valanghe dell'arco alpino italiano | Open data, CAAML v6 profilo EAWS |
| [WSL-SLF](https://www.slf.ch) | Bollettini valanghe svizzeri | CC BY 4.0 |
| [Open-Meteo](https://open-meteo.com) | Previsioni orarie e modello di elevazione | CC BY 4.0 |
| [EAWS Regions](https://regions.avalanches.org) | Perimetri delle zone valanghe | Open data |
| [Nominatim](https://nominatim.openstreetmap.org) | Geocoding dei toponimi | ODbL, usage policy |

I sentieri numerati CAI sono mappati **dalla community OSM**: questo progetto non accede ad alcun dato proprietario del Club Alpino Italiano, che non espone un'API pubblica. La copertura non e' uniforme e l'assenza di un sentiero non significa che non esista.

## Sviluppo

```bash
pytest              # test
ruff check .        # lint
mypy                # type check
python client/ispeziona.py     # client MCP minimale: elenca tool e resource
```

Architettura, decisioni di progetto e roadmap: [DEVELOPMENT.md](DEVELOPMENT.md).

## Licenza

MIT.

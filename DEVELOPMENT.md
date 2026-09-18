# DEVELOPMENT.md

Documento di sviluppo di `trekking-mcp`: architettura, decisioni prese e perche',
cosa manca e cosa non verra' fatto.

Chi legge un repo di portfolio guarda tre cose: se il codice funziona, se chi
l'ha scritto sa perche' l'ha scritto cosi', e se sa dove si ferma. Questo
documento copre la seconda e la terza.

---

## 1. Obiettivo e non-obiettivi

**Obiettivo.** Esporre a un assistente AI i dati aperti utili a preparare
un'escursione in montagna in Italia: sentieri numerati, ricoveri, bollettini
valanghe, meteo di quota. Dimostrare una copertura completa e non superficiale
del Model Context Protocol.

**Non-obiettivi**, dichiarati per evitare che il progetto si allarghi da solo:

- **Non e' un navigatore.** Niente calcolo di percorso, niente tracce GPX, niente
  routing. Serve un motore di routing e un modello di elevazione: e' un altro
  progetto.
- **Non valuta il rischio valanghe.** Rilegge un documento ufficiale e lo
  normalizza. La riga di confine e' netta e non va superata: vedi sezione 6.
- **Non e' un'integrazione CAI.** Il Club Alpino Italiano non espone un'API
  pubblica e il catasto sentieri non e' accessibile in quel modo. I sentieri
  numerati arrivano da OpenStreetMap, dove sono mappati dalla community.

---

## 2. Architettura

Tre livelli, con una dipendenza a senso unico: `tools` → `sources` → rete.

```
src/trekking_mcp/
├── server.py            # crea_server(): registra tutto, gestisce il lifespan
├── __main__.py          # CLI: scelta del transport
├── models.py            # Pydantic: il contratto dati verso il client
├── errors.py            # errori previsti vs. bug
├── config.py            # configurazione da env, frozen
├── risorse.py           # il contenitore delle dipendenze condivise
├── cache.py             # ttlMs/cacheScope: la freschezza dichiarata al client
├── geo.py               # point-in-polygon, senza dipendenze binarie
├── metriche.py          # contatori per fonte, in memoria
├── resources.py         # documenti di riferimento + resource template + metriche
├── prompts.py           # workflow riutilizzabili
├── completamenti.py     # autocompletamento degli argomenti
├── sources/             # un adapter per fonte esterna
│   ├── http.py          # client condiviso: retry, backoff, cache TTL
│   ├── overpass.py      # OpenStreetMap
│   ├── caaml.py         # bollettini CAAML v6 (AINEVA, SLF)
│   ├── eaws.py          # perimetri delle zone valanghe, cache su disco
│   ├── elevation.py     # quote e profili altimetrici
│   ├── nominatim.py     # geocoding, con rate limiter
│   ├── luoghi_simili.py # candidati simili nel raggio (Overpass + SequenceMatcher)
│   └── meteo.py         # Open-Meteo
└── tools/               # la superficie MCP
    ├── comuni.py        # extended_tool(): registrazione + errori; geometria
    ├── sentieri.py      # ricerca e dettaglio
    ├── condizioni.py    # bollettino, meteo
    ├── geocode_risolvi.py  # risolvi_localita + elicitation mid-call (SceltaGeocode)
    └── gita.py          # tool composito + elicitation
```

**Perche' questa separazione.** Gli adapter non sanno di essere dietro un server
MCP: restituiscono modelli, non risposte di protocollo. Questo rende il layer
`sources/` testabile senza alcuna infrastruttura MCP e riusabile se un giorno
serve una CLI o un'API REST sopra gli stessi dati.

**La registrazione e' esplicita.** Ogni modulo di tool espone
`registra(mcp, risorse)` e `crea_server()` li chiama in ordine. Niente
autodiscovery: si legge da un punto solo cosa espone il server, e l'ordine e'
deterministico.

**Le dipendenze scendono, non si cercano.** `Risorse` (config, client HTTP,
metriche, indice EAWS, i due limitatori) si costruisce una volta in
`crea_server()` e si passa a ogni `registra()`; da li' scende nelle funzioni
delle fonti come primo argomento. Nessun modulo va a prendersi da solo quello
che gli serve. Vedi §3.22.

---

## 3. Decisioni di progetto

### 3.1 SDK 2.x, non 1.x

Il codice usa `MCPServer` (`mcp>=2.0`). Nella 1.x la classe si chiamava
`FastMCP`; nella 2.x e' stata rinominata e l'import vecchio fallisce con un
messaggio che rimanda alla guida di migrazione.

Conseguenza pratica per chi legge: **gli esempi FastMCP che si trovano in giro
non compilano su questo repo**. Il vincolo `mcp>=2.0,<3.0` in `pyproject.toml`
e' volutamente stretto.

### 3.2 Elicitation via resolver, non sampling

Il **sampling e' deprecato dal 2026-07-28** (SEP-2577), insieme ai roots. Un
repo di portfolio che lo esibisce come feature avanzata ottiene l'effetto
opposto a quello voluto.

Al suo posto la 2.x offre la dependency injection dei resolver:

```python
profilo: Annotated[ProfiloUscita, Resolve(chiedi_profilo)]
```

Il parametro **non compare nello schema di input del tool**. Prima di eseguire
il corpo, il framework esegue il resolver; se questo restituisce un marker
`Elicit[T]`, la domanda va al client, l'utente risponde, il valore viene
iniettato. Se l'utente rifiuta, la chiamata si interrompe.

Perche' conta nel merito, non solo come vetrina: `valuta_gita` ha bisogno di
sapere se il gruppo ha ARTVA, pala e sonda. Se quel parametro fosse nello schema,
il modello lo riempirebbe **inventandoselo**. In un dominio di sicurezza
l'allucinazione di un dato sull'attrezzatura e' inaccettabile. Nasconderlo allo
schema e' una scelta di sicurezza prima che di stile.

Il test `test_parametro_elicitato_non_e_nello_schema` esiste per impedire che un
refactoring lo reintroduca per sbaglio.

Per la disambiguazione del geocoding (`cerca_localita`, `sentieri_verso_localita`
con contesto) si usa invece **`ctx.elicit` mid-call** con schema piatto
`SceltaGeocode`: la domanda dipende dai risultati di ricerca e non puo' essere
decisa prima del corpo del tool. `profilo` su `valuta_gita` resta un resolver
`Resolve` pre-corpo.

### 3.3 Un solo parser per tre provider

AINEVA, ALBINA e SLF pubblicano tutti in **CAAML v6, profilo EAWS**. Il parsing
in `sources/caaml.py` e' scritto una volta e i provider differiscono solo per
URL e attribuzione.

E' il pezzo di codice che dimostra piu' competenza di dominio: chi wrappa una
API scrive un parser per endpoint, chi capisce il dominio riconosce che esiste
uno standard e ci costruisce sopra.

Il parsing e' deliberatamente difensivo. `elevation` puo' essere un intero, una
stringa o `treeline`; i campi testuali sono a volte stringhe e a volte oggetti.
Ogni helper degrada a `None` invece di sollevare: un bollettino con un campo
strano deve arrivare comunque all'utente.

### 3.4 Il numero del sentiero sta in `ref`

Convenzione esplicita del wiki OSM italiano: `ref` e `operator` vanno sulla
*relation*, non sulle singole way, e il numero **non** va nel tag `name`.
Cercare "sentiero 103" per nome non trova nulla. Il test
`test_query_sentieri_filtra_su_ref_non_su_name` blocca la regressione.

### 3.5 Cache con TTL differenziati

| Dato | TTL | Perche' |
|---|---|---|
| Overpass | 24h | La geometria dei sentieri cambia di rado |
| Bollettino | 30 min | Emesso una o due volte al giorno |
| Meteo | 15 min | Aggiornamento continuo |

Non e' un'ottimizzazione prematura: Overpass impiega secondi e applica rate
limit aggressivi. Un agente che chiama tre tool di fila **viene bloccato**
senza cache. Il TTL lungo su Overpass e' anche una forma di rispetto verso
un'infrastruttura pubblica e gratuita.

### 3.6 Errori previsti contro bug

`ErroreSentieri` e sottoclassi = guasti previsti, tradotti in `ToolError` dal
decoratore `gestisci_errori`. Arrivano al client come messaggio leggibile e
azionabile ("zona inesistente, ecco quelle valide") e vengono loggati a INFO
senza traceback.

Tutto il resto e' un bug: passa, il client riceve un messaggio generico, il
server logga il traceback a ERROR.

La distinzione conta perche' un modello che riceve "zona non trovata, le zone
valide sono X, Y, Z" **corregge da solo**; uno che riceve `KeyError` no.

### 3.7 Degradazione parziale in `valuta_gita`

Se il bollettino non si recupera, il tool non fallisce: restituisce gli altri
dati e aggiunge un segnale di attenzione esplicito. Un'uscita preparata a meta'
e' meglio di un errore, **a patto che il buco sia dichiarato**. Un buco
silenzioso sarebbe peggio di un errore.

### 3.8 Segnali da regole scritte a mano

`_segnali()` applica soglie esplicite (grado ≥ 3, raffiche ≥ 60 km/h, neve
fresca ≥ 5 cm). Nessuna euristica opaca, nessun modello. Sono righe che si
leggono, si discutono e si testano. In un dominio di sicurezza e' l'unica scelta
difendibile: se una soglia e' sbagliata, si vede e si corregge.

### 3.9 Log su stderr, non verso il client

Su stdio **stdout e' il canale del protocollo**. Un singolo `print()` corrompe
la sessione. `logging.basicConfig(stream=sys.stderr)` in `__main__.py` non e'
una preferenza: e' l'errore piu' comune al primo server MCP ed e' il motivo per
cui il codice non contiene un solo `print`.

Il server non manda log nemmeno al client. La *logging capability* del
protocollo — `ctx.log()` e i suoi alias — e' deprecata dalla revisione
2026-07-28 (SEP-2577), insieme a sampling e roots. `ctx.report_progress` no:
il progresso server -> client resta, ed e' quello che usano
`profilo_altimetrico` e `valuta_gita`.

I cinque `ctx.log` che c'erano non hanno perso niente nel passaggio a stderr,
e il motivo dice qualcosa sul disegno:

- I tre `warning` di `valuta_gita` (profilo, zona, bollettino non recuperati)
  erano gia' accompagnati, ognuno, da un `SegnaleAttenzione` nell'output
  strutturato. Il modello li vedeva li', dove non puo' non vederli; la notifica
  di log era una copia peggiore. Il dettaglio dell'eccezione, che al modello
  non serve, ora va a chi opera il server.
- I due `info` (`cerca_sentieri`, `zona_valanghe_da_coordinate`) narravano
  un'operazione a un passo solo. Non c'era progresso da riportare: inventare
  un `report_progress` con un passo su uno sarebbe stato rumore.

La regola generale e' quella di §3.7: cio' che il modello deve sapere sta nel
risultato, non in un canale laterale che il client puo' ignorare.

**La deprecazione e' una build rotta, non una riga di warning.**
`filterwarnings = ["error::mcp.shared.exceptions.MCPDeprecationWarning"]` in
`pyproject.toml` fa fallire i test su qualunque API deprecata dell'SDK. Un
warning nell'output dei test non lo legge nessuno; e' cosi' che ci si accorge
di una revisione del protocollo quando il supporto viene rimosso, invece che
quando esce.

### 3.10 Nessuna API key

Tutte le fonti di default sono aperte. Chi clona il repo lo prova in trenta
secondi. Un progetto di portfolio che richiede una registrazione per essere
eseguito non verra' eseguito.

### 3.11 Point-in-polygon senza shapely

Servono due operazioni: bounding box e contenimento. Shapely porta con se' GEOS,
una dipendenza binaria che complica l'installazione su ogni piattaforma e pesa
decine di MB, per usarne l'1%.

`geo.py` implementa il ray casting in una settantina di righe, con un prefiltro
sul riquadro che scarta quasi tutti i candidati in quattro confronti prima di
toccare l'algoritmo O(vertici). Il modulo e' scritto per essere buttato: se un
giorno servissero intersezioni, buffer o unioni, shapely diventa la scelta
giusta e questo file sparisce.

### 3.12 Perimetri EAWS scaricati, non impacchettati

I poligoni delle micro-regioni sono decine di MB e vengono rivisti a ogni
stagione. Metterli nel repo significherebbe **distribuire dati di sicurezza
obsoleti**, che e' peggio che non distribuirli affatto.

Vengono scaricati al primo uso e tenuti in una cache su disco con TTL di 30
giorni. La scrittura e' atomica (file temporaneo piu' `replace`): un download
interrotto non deve lasciare in cache un JSON troncato che al riavvio verrebbe
letto come valido.

Un territorio che non si scarica non blocca gli altri: meglio un indice parziale,
con il buco loggato, che nessun indice.

### 3.13 Il dislivello ha bisogno di una soglia

Sommare ingenuamente le differenze di quota fra punti consecutivi **gonfia il
dislivello anche del 30%**: il modello di elevazione ha rumore di qualche metro,
e su mille punti il rumore si accumula tutto in salita.

`_dislivelli()` ignora le variazioni sotto i 5 m rispetto all'ultimo punto
significativo. E' l'errore piu' comune nel calcolo dei profili altimetrici, e il
test `test_dislivello_ignora_il_rumore` verifica che una traccia piatta e
rumorosa dia zero.

### 3.14 Campionamento per distanza, non per indice

La densita' dei vertici in OSM e' irregolare: i tornanti hanno molti punti, i
lunghi rettilinei pochi. Campionare un punto ogni N indici infittirebbe i
tornanti e diraderebbe i rettilinei, deformando il profilo.

Si campiona quindi ogni `passo_m` metri di percorso, conservando sempre primo e
ultimo punto perche' determinano quota di partenza e di arrivo. La lunghezza,
invece, si calcola sulla polilinea **completa**: il campionamento taglia gli
angoli e accorcerebbe il totale.

### 3.15 Le way di una relation vanno ricucite

Le way che compongono una relation escursionistica non sono garantite ne'
ordinate ne' orientate coerentemente: e' normale trovare un tratto memorizzato
al contrario. `polilinea()` le ricuce confrontando gli estremi e invertendo
quando serve. Senza questo passaggio il profilo altimetrico risulta un dente di
sega privo di senso, e il bug e' subdolo perche' il codice non fallisce: produce
solo numeri sbagliati.

### 3.16 Nominatim va rallentato di proposito

La usage policy impone al massimo una richiesta al secondo e un User-Agent
identificabile. Il servizio e' gratuito e mantenuto da donazioni; farsi bannare
l'IP e' facile e meritato.

`Limitatore` serializza le richieste con un lock e aspetta. Rallenta, ed e'
esattamente quello che deve fare. Il lock non e' decorativo: senza, due coroutine
concorrenti leggerebbero entrambe il timestamp precedente prima che l'altra lo
aggiorni, e passerebbero insieme.

### 3.17 Gli errori 4xx non si ritentano

Introdotto dopo aver visto la suite di test passare da 1,5 a 22 secondi: un 404
finiva nel ciclo di retry con backoff esponenziale, moltiplicato per otto
territori. Un 4xx diverso da 429 e' definitivo, e riprovare martella una fonte
che ha gia' risposto chiaramente.

### 3.17.1 `Retry-After` ha un tetto

Rispettare `Retry-After` e' corretto; rispettarlo senza limite no. Il semaforo
di Overpass e' globale al processo: una richiesta ferma in `sleep` per l'ora
che la fonte ha chiesto non aspetta da sola, tiene fuori ogni altra query del
server. E il valore arriva da fuori, quindi non e' un numero di cui fidarsi.

Oltre `RETRY_AFTER_MAX_S` (120s) non si aspetta e non si ritenta: si solleva
subito `FonteNonDisponibile` riportando quanto la fonte chiedeva. Chi legge
dall'altra parte sa che deve tornare piu' tardi, e intanto le altre chiamate
passano.

### 3.18 Il bind pubblico va dichiarato, non subito

L'SDK attiva la protezione da DNS rebinding (validazione di `Host` e `Origin`)
**solo** quando il bind e' su `127.0.0.1`, `localhost` o `::1`. Chi scrive
`--host 0.0.0.0` per esporre il server la perde senza accorgersene, ed e'
esattamente il caso in cui serve: un sito qualunque puo' far chiamare dal
browser della vittima un server che crede di essere privato.

`impostazioni_sicurezza()` rovescia il default: fuori da localhost il comando
**non parte** finche' non si dichiara almeno un `--allow-host`. Fallire
all'avvio e' l'unico momento in cui qualcuno legge il messaggio; un warning nel
log verrebbe ignorato.

Non sostituisce l'autenticazione, che resta in roadmap: `Host`/`Origin` dicono
da dove arriva la richiesta, non chi la manda.

### 3.19 Le metriche come resource, non come endpoint

Osservabilita' senza infrastruttura: un registro in memoria (`metriche.py`)
esposto come resource `metriche://fonti`. Niente Prometheus, niente sidecar,
niente scrittura su disco.

Perche' una resource e non un `/metrics` HTTP: su stdio un endpoint HTTP non
esiste, e stdio e' il modo in cui questo server viene usato il 90% delle volte.
Una resource funziona su entrambi i transport e la si legge dallo stesso client
con cui si usa il server.

Cosa si misura, e perche' proprio questo: chiamate, errori, retry, 429, 5xx,
latenza p50/p95 e hit rate della cache, **per fonte**. Sono le colonne che
rispondono alla domanda che ci si pone davvero quando una risposta tarda: quale
fonte sta frenando, e sta frenando o sta rifiutando?

Le latenze stanno in una finestra scorrevole di 256 campioni, i contatori no:
un p95 calcolato su tutta la vita del processo descrive soprattutto il passato,
e una lista che cresce all'infinito e' una perdita di memoria travestita da
metrica.

`hit_rate` e' `None`, non `0.0`, per le fonti che non usano la cache: zero
direbbe "cache inefficace", che e' un'altra cosa da "cache non prevista".

### 3.19.1 L'indice EAWS si carica sotto lock

`IndiceRegioni` e' pigro: il primo `cerca` scarica gli otto territori. Il
controllo «ho gia' questo territorio?» stava pero' prima di un `await`, e
l'insieme dei territori caricati veniva aggiornato solo dopo.

Sequenzialmente non si vede. Con due tool chiamati insieme — il caso normale,
non l'eccezione: un agente fa fan-out, e i TODO annotano una sessione in cui
Cursor ha lanciato tre tool Overpass in parallelo — entrambi passavano il
controllo, scaricavano lo stesso file e appendevano le stesse micro-regioni.
L'indice restava con i duplicati per tutta la vita del processo: `zona_da_coordinate`
se ne accorgeva poco, ma i completamenti proponevano lo stesso ID piu' volte.

Un `asyncio.Lock` attorno a `carica()`, con il controllo ripetuto dentro. Il
caso comune (indice gia' pronto) non paga il lock, perche' `cerca` controlla
prima di chiamare. I test stanno in `test_concorrenza.py`: senza lock falliscono
tre su quattro.

### 3.20 I completamenti non possono scaricare niente

`completion/complete` serve a completare `zona_id`: `IT-21-AO-01` non si
ricostruisce a mente. I valori vengono dall'indice EAWS **gia' in memoria**, e
se l'indice e' vuoto la risposta e' una lista vuota.

La tentazione e' caricarlo al volo. Ma un completamento parte a ogni carattere
digitato: innescare li' decine di MB di download significherebbe bloccare
l'editor di chi scrive. Meglio non completare che completare dopo quindici
secondi.

Il `context` della richiesta porta gli argomenti gia' risolti, e viene usato:
scelto `provider=slf`, `zona_id` propone solo `CH-*`. E' la differenza fra un
completamento utile e un elenco.

### 3.21 `valuta_gita` non scarica la geometria di sua iniziativa

`con_profilo` era `true` di default. In sessione reale la query `out geom`
andava in 504 su Overpass e si portava dietro tutto il tool. Ora e' `false`:
il dislivello si chiede, non si subisce.

Il corollario e' che i buchi vanno dichiarati. Una relation senza posizione
utilizzabile produceva tre liste vuote (rifugi, meteo, zona) che si leggono come
"non c'e' niente nei dintorni", cioe' il contrario di quello che era successo.
Ogni dato non raccolto e' ora un `SegnaleAttenzione` di categoria `dati`. E'
la regola di §3.7 applicata anche al caso banale: un campo vuoto, da solo,
mente.

### 3.22 Le dipendenze si passano, non si cercano

Il server aveva sei singleton costruiti all'import: `CONFIG`, `CLIENT`,
`METRICHE`, `INDICE`, il semaforo Overpass, il limitatore Nominatim. Funzionava.
Il sintomo era nei test: per cambiare un timeout si scriveva

```python
monkeypatch.setattr("trekking_mcp.sources.http.CONFIG", replace(CONFIG, max_retry=3))
```

cioe' si riscriveva una variabile di un altro modulo per il resto della
sessione. E siccome cache, metriche e indice EAWS erano condivisi da tutti,
servivano fixture `autouse` che li svuotassero prima e dopo ogni test: 17
chiamate a `svuota()`/`azzera()` sparse in sei file, tutte li' per rimediare a
un accoppiamento che non era necessario.

`Risorse` raccoglie le sei dipendenze e le passa per argomento. Il grafo e'
descritto in un posto solo (`Risorse.crea`), e i numeri dicono il resto: da 6
singleton a 0, da 17 pulizie di stato a 1. I `monkeypatch` rimasti sostituiscono
*funzioni* — quello e' il loro mestiere — non configurazione.

`crea_server(risorse=...)` accetta risorse gia' pronte: e' la giuntura che
permette a un test di consegnare al server un indice EAWS finto invece di
riscrivere `eaws.INDICE`.

**Closure, non solo `lifespan_context`.** L'SDK inietta il `Context` nei tool e
nelle resource template, ma **non** nelle resource statiche (rifiuta proprio la
registrazione) ne' nell'handler dei completamenti, che ha firma fissa. Visto che
`metriche://fonti` e' statica e i completamenti leggono l'indice EAWS, legare le
risorse alla registrazione e' l'unico meccanismo valido per tutti e cinque i
primitivi. Il `lifespan` resta padrone del ciclo di vita e le restituisce
comunque, cosi' chi preferisce la porta idiomatica ce l'ha: stesso oggetto, due
porte.

### 3.23 Un tool non si puo' registrare senza traduzione degli errori

Ogni tool portava due decoratori: `@mcp.tool(...)` e `@gestisci_errori`.
Ricordarsene due su dieci riesce; all'undicesimo, prima o poi, no — e il tool
dimenticato manda al modello un traceback invece di una frase utile.

`extended_tool()` compone i due in uno. Non e' zucchero sintattico: e' che la
versione sbagliata non si puo' piu' scrivere. Porta con se' anche le
annotazioni `read_only_hint`/`open_world_hint`, che erano copiate identiche
dieci volte.

La traduzione degli errori era anche il pezzo piu' importante non testato:
`test_registrazione.py` copre ora la traduzione in se', il fatto che un bug
vero **non** venga mascherato, cosa arriva davvero al client (`is_error` e un
messaggio azionabile, non un traceback) e la regola strutturale — nessun modulo
chiama `mcp.tool` per conto suo.

### 3.24 La freschezza si dichiara, non si tiene per se'

`Config` ha un TTL per fonte e `CacheTTL` lo usa per la cache HTTP interna. Quella
conoscenza pero' si fermava al processo: un client che rileggeva
`bollettino://aineva/IT-21-AO-01` tre volte in cinque minuti faceva tre
richieste, e il server rispondeva tre volte dalla propria cache. Lavoro inutile
su entrambi i lati, che nessuno dei due poteva evitare — la freschezza non era
scritta da nessuna parte.

`ttlMs` e `cacheScope` (SEP-2549, revisione 2026-07-28) la scrivono. Servono
due meccanismi, perche' l'SDK ne offre due:

- **Gli elenchi** prendono un hint per metodo, via `MCPServer(cache_hints=...)`.
  Qui sono statici: si registra tutto in `crea_server()` e non cambia piu'.
- **Le resource** hanno freschezze diverse fra loro — i documenti di riferimento
  valgono un giorno, un bollettino trenta minuti, i contatori di
  `metriche://fonti` zero — e l'hint per metodo e' uno solo. Le distingue un
  middleware, che e' l'unico punto a vedere insieme l'URI richiesto e il
  risultato che torna indietro: le funzioni `@mcp.resource` restituiscono una
  stringa e non hanno modo di parlare dei campi del risultato.

Il TTL del bollettino non e' un numero nuovo: e' `ttl_bollettino_s`, lo stesso
che governa la cache interna. Un bollettino non puo' valere trenta minuti per il
server e un'ora per il client.

`tools/call` non compare: `CallToolResult` non ha quei campi, ed e' giusto cosi'
— quanto valga il risultato di un tool dipende dagli argomenti, e non spetta al
protocollo deciderlo.

I test leggono i campi attraverso un `Client` vero, mai dalle funzioni interne.
Sul filo i nomi sono in camelCase (`ttlMs`, `cacheScope`) e il middleware li
scrive su un dict gia' serializzato: e' un dettaglio dell'SDK, quindi va
verificato dall'altro capo invece che assunto.

### 3.25 Icona e sito, per farsi riconoscere

`website_url` e `icons` sono quello che un client mostra quando qualcuno sceglie
fra piu' server. L'icona e' un SVG inline come data URI: nessun file binario nel
repo, nessun hosting da tenere in piedi, e funziona a un client offline. Usa
`currentColor`, quindi non servono le due varianti chiaro/scuro che `theme`
permetterebbe.

Il protocollo ammette icone anche per singoli tool, resource e prompt. Qui non
ce ne sono: dieci glifi inventati per mostrare che il campo esiste sarebbero
rumore, e un repo di riferimento dovrebbe insegnare anche quando *non* riempire
un campo.

### 3.26 Il `requestState` va sigillato con una chiave dichiarata

Un'elicitation non e' una richiesta sola: il server chiede, il client risponde,
e la seconda meta' deve ritrovare il contesto della prima. Sul wire 2026-07-28
quel contesto viaggia nel `requestState`, che il client rimanda indietro e che il
server considera **controllato dall'attaccante**: l'SDK lo sigilla in uscita e
verifica ogni ritorno.

Con quale chiave, e' una scelta di deploy. `MCPServer` senza
`request_state_security=` installa `RequestStateSecurity.ephemeral()`: una chiave
casuale, viva quanto il processo. Per stdio e' esattamente giusto. Su HTTP con
piu' repliche e' un bug latente: la replica B rifiuta lo stato emesso da A, e
l'elicitation muore a meta' senza che nessun test lo veda, perche' in test c'e'
un processo solo. `--stateless` peggiora la cosa mentre sembra migliorarla — la
flag serve proprio a mettere piu' repliche dietro un bilanciatore.

Da qui `Config.state_keys` (`TREKKING_MCP_STATE_KEYS`): `keys[0]` sigilla, tutte
verificano, quindi la rotazione e' nuova-in-testa e vecchia-in-coda per un TTL.
Il server logga un warning quando parte su HTTP senza chiavi: non e' un errore
(un worker solo funziona), ma va detto prima, non quando un utente vede una
domanda del server restare senza risposta.

Il contratto e' verificato in
`test_operabilita.py::test_lo_stato_sigillato_e_lo_stesso_fra_due_server`: due
policy con le stesse chiavi si capiscono, due effimere no.

### 3.27 La finestra del meteo non comincia a mezzanotte

Open-Meteo restituisce la giornata **dall'ora zero**, non "da adesso". Prendere
le prime `ore_max` ore della serie — che e' quello che faceva
`istanti[:ore_max]` — significa rispondere a chi prepara una gita con le ore fra
mezzanotte e mezzogiorno: meta' finestra sprecata sulla notte, e il pomeriggio,
quando arrivano i temporali, tagliato fuori.

`_finestra()` sceglie l'inizio con tre regole, in ordine:

1. `ora_inizio` esplicita vince: chi parte alle 4 lo sa meglio del server.
2. Per **oggi**, si parte dall'ora corrente: un'ora passata non e' una previsione.
3. Per un giorno **futuro**, dalle 6.

Restituisce l'indice insieme all'istante, perche' le altre serie (temperatura,
vento, zero termico) sono parallele a `time`: sfasare l'indice attribuirebbe il
vento delle 14 alle 8 del mattino, che e' peggio di non rispondere. Se la
finestra cade oltre la fine della serie, degrada alle ultime ore disponibili
invece di restituire una lista vuota.

### 3.28 Il provider del bollettino si deduce dalla zona

`PROVIDER` dice a quale URL chiedere il bollettino. Diceva solo quello, e il
legame inverso — questa zona di chi e'? — viveva in due copie: un default
`provider="aineva"` in `leggi_bollettino` e un dizionario `PREFISSI_PROVIDER` in
`completamenti.py`. Il risultato: `valuta_gita` chiedeva **ogni** zona ad
AINEVA, e una zona svizzera tornava "non trovata" con l'elenco delle zone
italiane allegato, cioe' un errore che manda fuori strada chi lo legge.

Ora il prefisso di zona sta dentro `PROVIDER`, accanto all'URL, e
`provider_per_zona()` e' l'unica funzione che fa la deduzione. Un terzo provider
si aggiunge in un posto solo.

La stessa tabella ha fatto emergere il gemello del bug: le zone `slf` non si
autocompletavano **mai**, perche' i completamenti non scaricano niente (§3.20) e
i perimetri svizzeri non erano fra i territori caricati. L'invariante che
mancava e' ora un test — ogni provider deve avere almeno un territorio in
`TERRITORI_DEFAULT` — e i territori sono passati in `Config`, perche' decidere
quali indicizzare decide anche quali zone il server sa risolvere.

### 3.29 Una resource sincrona gira in un altro thread

`metriche://fonti` era una funzione sincrona, e l'SDK esegue le funzioni
sincrone con `anyio.to_thread.run_sync`. `Metriche` e' un dizionario di contatori
che l'event loop muta a ogni risposta di una fonte: leggerlo da un altro thread
mentre una fonte nuova viene registrata puo' sollevare *dictionary changed size
during iteration*, raramente e solo sotto carico, cioe' nel modo peggiore.

La funzione e' `async` anche se non attende nulla. Non e' cerimonia: dichiararla
`async` la riporta sull'event loop, dove avvengono tutte le scritture, e la
corsa smette di esistere. Le due resource che leggono file restano sincrone, che
per un `read_text` bloccante e' la scelta giusta.

---

## 4. Testing

**179 test, nessuno tocca la rete.** Le chiamate HTTP sono intercettate con
`pytest-httpx2` (respx su httpcore2). Una suite che dipende da Overpass
fallisce a caso, e una CI che fallisce a caso viene ignorata dopo due settimane.

Tre famiglie:

- `test_modelli.py` — parsing dei tag OSM, conversione delle scale, casi
  degeneri (tag mancanti, `sac_scale` fuori standard, `ele` decimale).
- `test_fonti.py` — costruzione delle query, escaping, parsing CAAML, retry,
  efficacia della cache.
- `test_concorrenza.py` — cosa succede quando due tool partono insieme. Un
  agente non chiama in sequenza: le corse che contano si vedono solo qui.
- `test_registrazione.py` — il contratto d'errore verso il client, e la regola
  che nessun tool si registri scavalcando `extended_tool()`.
- `test_elicitation.py` — cosa arriva davvero al client quando il server fa una
  domanda: gli enum nello schema, e i due elenchi agganciati alla loro fonte.
- `test_freschezza.py` — `ttlMs`/`cacheScope`, riletti da un Client vero.
- `test_fase2.py` — geometria su poligoni costruiti a mano (dove il risultato
  atteso e' calcolabile a mente: su un poligono reale da 4000 vertici non si sa
  dire se una risposta e' giusta), lookup delle zone, campionamento, dislivelli,
  ricucitura delle polilinee, rate limiter.
- `test_server.py` — **test di contratto**: quali tool esistono, che tutti
  abbiano descrizione e `outputSchema`, che siano marcati `readOnly`, che il
  parametro elicitato resti fuori dallo schema, che i prompt contengano ancora i
  vincoli di sicurezza.
- `test_gita.py` — **end-to-end con un client MCP in-process**: il client
  risponde all'elicitation, il valore iniettato si ritrova nei segnali, il
  rifiuto ferma la chiamata prima di qualunque richiesta di rete.
- `test_operabilita.py` — sicurezza del transport, contatori delle metriche,
  completamenti, e il contratto sul sigillo del `requestState` (§3.26).
- `test_meteo_finestra.py` — quali ore risponde il meteo (§3.27): e' una
  funzione pura, quindi si prova senza rete e senza orologio, passando l'istante.
- `test_provider_zone.py` — zona → provider, e l'invariante che ogni provider
  abbia i suoi perimetri fra i territori indicizzati (§3.28).

I test di contratto sono quelli che valgono di piu' nel tempo: proteggono
l'interfaccia verso i client MCP, che e' la cosa che si rompe silenziosamente.

Cosa **non** e' coperto e andrebbe aggiunto: test su risposte CAAML reali
salvate come fixture (vedi roadmap).

---

## 5. Limiti noti

| Limite | Impatto | Mitigazione |
|---|---|---|
| Cache in memoria, per-processo | Su HTTP multi-worker ogni replica ha la sua cache | **Scelta, non dimenticanza**: vedi §5.1 |
| Rate limiter Nominatim per-processo | Con piu' repliche il budget di 1 req/s viene superato | Stesso motivo e stesso limite di sopra: un processo solo |
| Nessuna autenticazione sul transport HTTP | Il server non sa **chi** lo chiama | `Host`/`Origin` validati (§3.18), che e' un'altra cosa; OAuth in roadmap |
| Elicitation e piu' repliche | Senza `TREKKING_MCP_STATE_KEYS` lo stato di un giro a due round-trip vale solo dentro un processo | Chiavi condivise e ruotabili, piu' un warning all'avvio (§3.26) |
| `CACHE_MAX_ENTRY` conta le voci, non i byte | Una risposta `out geom` sta nell'ordine dei MB: 512 voci non sono 512 unita' di memoria | Nota in `leggi_geometria`; un tetto in byte e' lavoro aperto |
| Metriche per-processo, azzerate al riavvio | Nessuna serie storica | Bastano a dire quale fonte sta frenando adesso; l'export sta dietro `istantanea()` |
| Copertura OSM non uniforme | Un sentiero assente non significa inesistente | Dichiarato nelle `instructions` e nel README |
| `sac_scale` spesso mancante o datato | Difficolta' sconosciuta | Mai degradata a "facile": resta `SCONOSCIUTA` e genera un segnale |
| Ray casting sul bordo dei poligoni | Un punto esattamente sul confine puo' cadere di qua o di la' | Irrilevante: le micro-regioni confinanti hanno bollettini simili |
| Cache dei perimetri per-processo, su disco condiviso | Piu' repliche scrivono lo stesso file | La scrittura e' atomica, quindi al peggio si riscarica |
| Il profilo altimetrico costa una query Overpass pesante | `valuta_gita` e' piu' lento | Disattivabile con `con_profilo=false` |
| Solo previsione, nessun dato storico | Niente analisi retrospettive | Fuori scope |

### 5.1 Perche' la cache resta in memoria

Redis risolverebbe le prime due righe della tabella, e per un deploy
multi-replica sarebbe la scelta giusta. Non viene adottato lo stesso, e la
ragione e' esplicita: **il progetto deve restare clonabile e leggibile senza
montare infrastruttura.** `uv sync && trekking-mcp` e' tutto quello che serve
oggi; aggiungere Redis significherebbe un servizio da avviare, una connessione
da configurare e un percorso di errore in piu' per chiunque voglia solo leggere
il codice o provarlo.

Il costo di questa scelta e' dichiarato: **un processo solo.** Non e' una
configurazione da cui scalare orizzontalmente, ed e' una cosa da sapere prima
di metterci carico multi-utente, non dopo. L'interfaccia di `CacheTTL` e'
comunque piccola e sincrona per rimpiazzo: chi ne avesse bisogno sostituisce la
classe, non i chiamanti.

---

## 6. Sicurezza e responsabilita'

Questa sezione e' un vincolo di progetto, non un disclaimer legale.

I bollettini valanghe sono **documenti ufficiali di sicurezza**. Le regole che
il codice rispetta:

1. **Rileggere, non interpretare.** Nessun tool riassume o riformula il testo
   del previsore. La sintesi viene passata invariata.
2. **Nessun verdetto.** `valuta_gita` non emette e non deve mai emettere un
   giudizio vai/non-vai. Restituisce fatti e segnali; la decisione resta a chi
   va in montagna.
3. **Avvertenza nel payload, non solo nel README.** I modelli `Bollettino` e
   `ValutazioneGita` hanno un campo `avvertenza` con un default non vuoto, cosi'
   che arrivi al modello insieme ai dati. Un test verifica che non sia vuoto.
4. **I prompt vincolano il comportamento.** `prepara_gita` vieta esplicitamente
   il verdetto e impone la citazione delle fonti. Un test controlla che il
   vincolo sopravviva ai refactoring del testo.
5. **L'assenza di dato non e' un dato rassicurante.** Difficolta' non mappata →
   `SCONOSCIUTA` + segnale, mai "facile". Bollettino non recuperato → segnale
   esplicito, mai silenzio.

Chi rivede questo repo dovrebbe capire che il limite e' stato progettato, non
aggiunto alla fine.

---

## 7. Roadmap

### Fase 1 — completamento (fatto)
- [x] Tre primitivi: tool, resource (incluse template), prompt
- [x] Structured output da modelli Pydantic
- [x] Elicitation via resolver DI
- [x] Doppio transport da un solo `crea_server()`
- [x] Cache TTL, retry con backoff, errori tipizzati
- [x] Client MCP minimale
- [x] Test di contratto in CI
- [x] Completamento degli argomenti (`completion/complete`)
- [x] Test end-to-end del giro di elicitation, con client in-process

### Fase 2 — utilita' reale (fatto)
- [x] **Lookup zona valanghe da coordinate.** I poligoni delle micro-regioni
      EAWS sono pubblicati come GeoJSON. Togliere all'utente l'onere di
      conoscere l'ID e' il singolo miglioramento con piu' impatto.
- [x] **Dislivello reale.** Query Overpass `out geom` piu' un modello di
      elevazione, con caching aggressivo: il dislivello conta piu' della
      lunghezza per capire l'impegno di una gita.
- [ ] **Fixture da risposte reali.** Salvare risposte CAAML e Overpass vere
      (anonimizzate) come fixture, per testare il parsing contro la realta' e
      non contro quello che credo sia la realta'.
- [x] Ricerca per toponimo via Nominatim, con rispetto della usage policy.

### Fase 3 — deploy
- [x] Metriche: latenza per fonte, hit rate della cache, rate limit incontrati
- [x] Validazione di `Host`/`Origin` sul transport HTTP, obbligatoria fuori da
      localhost
- [ ] OAuth sul transport HTTP (supportato dall'SDK via `token_verifier`)
- [ ] Immagine Docker e healthcheck
- [ ] Mirror Overpass dedicato: `overpass-api.de` non e' un backend di produzione
- ~~Cache su Redis~~ — **non si fa**, per scelta: vedi §5.1

### Esplicitamente fuori scope
Routing e tracce GPX, dati storici, previsione autonoma del pericolo valanghe,
scraping di siti che non espongono dati aperti.

---

## 8. Convenzioni

- **Italiano** per nomi di dominio, docstring e commenti. Il dominio e' italiano
  e i termini tecnici (rifugio, bivacco, EEA, grado di pericolo) non hanno
  traducenti puliti. Restano in inglese i termini di protocollo (tool, resource,
  elicitation) e i tag OSM.
- **Commenti sul perche', non sul cosa.** Un commento che ripete il codice e'
  rumore. Il diff delle decisioni non ovvie sta nel codice, non solo qui.
- `ruff` per lint e ordinamento import, `mypy --strict`, `pytest`.
- Commit convenzionali (`feat:`, `fix:`, `docs:`, `test:`).

---

## 9. Da fare prima di pubblicare

- [x] URL del repo in `pyproject.toml`, `README.md` e `config.py`
      (l'User-Agent contiene l'URL del repo: e' richiesto dalla usage policy di
      Overpass, non e' decorativo)
- [x] Mettere il proprio nome in `authors`
- [x] Aggiungere il file `LICENSE` (MIT, coerente con `pyproject.toml`)
- [ ] Registrare una GIF o un asciinema di 20 secondi con un client che usa il
      server, e metterla in cima al README: vale piu' di tre paragrafi
- [ ] Verificare che la CI sia verde e aggiungere il badge
- [x] Controllare la revisione corrente della spec MCP e dichiararla nel README
      (2026-07-28, `LATEST_PROTOCOL_VERSION` dell'SDK 2.2)

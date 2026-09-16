# Difficolta' escursionistica: scala CAI e tag OSM

## Scala CAI (Italia)

| Sigla | Significato | Terreno |
|---|---|---|
| **T** | Turistico | Stradine, mulattiere, sentieri larghi e ben evidenti. Percorso breve, dislivelli modesti. |
| **E** | Escursionistico | Sentieri o tracce su terreno vario, a volte con brevi tratti esposti ma protetti. Richiede allenamento e calzature adeguate. |
| **EE** | Escursionisti Esperti | Tracce poco evidenti, terreno impervio, pendii ripidi, passaggi rocciosi con lievi difficolta' tecniche. Richiede passo sicuro e assenza di vertigini. |
| **EEA** | Escursionisti Esperti con Attrezzatura | Vie ferrate e sentieri attrezzati. Richiede imbragatura, casco e set da ferrata, oltre alla capacita' di usarli. |

A queste si aggiungono **EAI** (itinerari innevati, con ciaspole) e le sigle
alpinistiche (F, PD, AD...) che escono dall'ambito escursionistico.

## Tag OSM `sac_scale`

OpenStreetMap usa la scala svizzera CAS/SAC, a sei livelli:

| `sac_scale` | Livello | Corrispondenza CAI indicativa |
|---|---|---|
| `hiking` | T1 | T |
| `mountain_hiking` | T2 | E |
| `demanding_mountain_hiking` | T3 | EE |
| `alpine_hiking` | T4 | EE |
| `demanding_alpine_hiking` | T5 | EEA |
| `difficult_alpine_hiking` | T6 | EEA |

## Perche' la corrispondenza e' solo indicativa

Le due scale misurano cose leggermente diverse: la SAC pesa molto il terreno e
l'esposizione, la CAI include anche impegno fisico e attrezzatura richiesta. La
conversione applicata da questo server **arrotonda verso l'alto** in caso di
ambiguita'.

Va inoltre ricordato che `sac_scale` in OSM e' inserito da volontari e puo'
mancare, essere datato o riferirsi a condizioni estive. Un sentiero senza
difficolta' mappata non e' un sentiero facile: e' un sentiero su cui non
sappiamo nulla.

## Il tag `trail_visibility`

Spesso piu' utile della difficolta' stessa: descrive quanto la traccia sia
riconoscibile sul terreno (`excellent`, `good`, `intermediate`, `bad`,
`horrible`, `no`). Con `bad` o peggio servono carta, bussola e capacita' di
orientamento, indipendentemente dal grado.

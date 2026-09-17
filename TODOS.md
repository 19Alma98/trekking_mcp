# TODO — integrazione MCP online

Esiti dalla sessione reale «trekking da Torino» (2026-09-17).
Obiettivo: server performante e funzionante per uso multi-utente / transport HTTP.

Report dettagliato: canvas `report-mcp-sessione-torino` nel progetto Cursor.

---

## P0 — bloccanti per andare online

- [ ] **Cache condivisa (Redis o equivalente) per Overpass / meteo / bollettino**
  - TTL già definiti in config; store attuale solo in-memory per processo
  - Su HTTP multi-worker / serverless ogni replica ripaga Overpass

---

## P1 — affidabilità e latenza percepita

- [ ] **`valuta_gita`: default `con_profilo=false`; segnali espliciti se manca geometria/centro**
  - Relation senza way → `centro=null` → meteo / zona / ricoveri vuoti in silenzio
  - `out geom` su Overpass è lento (504) e fragile; profilo on-demand, non di default

- [ ] **Mirror Overpass self-hosted o istanza dedicata**
  - `overpass-api.de` non è un backend di produzione

- [ ] **OAuth + rate limit per client sul transport HTTP**
  - Già in roadmap `DEVELOPMENT.md` Fase 3; necessario online

---

## P2 — operabilità e uso agentico

- [ ] **Metriche: latenza per fonte, hit rate cache, conteggio 429/504**
  - Altrimenti si naviga a sensazione

- [ ] **Guidance agent: evitare fan-out parallelo su tool Overpass**
  - Le instructions del server aiutano; in sessione Cursor ha comunque chiamato 3 tool Overpass insieme
  - Rafforzare instructions / prompt e, lato server, serializzare comunque le query Overpass
  - Nota: serializzazione server-side già in P0; resta il pezzo instructions

- [ ] **UX dati OSM incompleti**
  - `difficolta_cai=sconosciuta` e `lunghezza_km` spesso null non sono bug di codice
  - Messaging chiaro + eventuali fallback (non solo campi vuoti)

---

## Futuro — dati OSM senza Overpass a runtime

- [ ] **Estratto OSM (Geofabrik) → PostGIS (o SQLite+SpatiaLite)**
  - Sync periodico di relation `route=hiking` e ricoveri per IT/Alpi
  - Ricerche bbox/ref/operator in locale; Overpass solo come fallback o per geometrie rare
  - Riduce dipendenza da istanze pubbliche e latenza sotto carico multi-utente

---

## Cosa già funziona (non TODO, riferimento)

- Errori `FonteNonDisponibile` leggibili e azionabili
- Nominatim stabile (con `Limitatore`)
- Tool compositi (`sentieri_verso_localita`, `valuta_gita`) nella direzione giusta
- Con raggio piccolo, `cerca_sentieri` restituisce ref OSM utili
- Backpressure Overpass (semaforo + Retry-After + jitter)

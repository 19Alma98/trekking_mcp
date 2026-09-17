# TODO — integrazione MCP online

Esiti dalla sessione reale «trekking da Torino» (2026-09-17).
Obiettivo: server performante e funzionante per uso multi-utente / transport HTTP.

Report dettagliato: canvas `report-mcp-sessione-torino` nel progetto Cursor.

---

## P0 — bloccanti per andare online

- [ ] **Backpressure su Overpass: coda / semaforo + `Retry-After` + jitter**
  - Sessione: 429 e 504 con chiamate parallele tipiche di un agente
  - Oggi: retry 1s/2s senza jitter né rispetto di `Retry-After`; nessun limite globale (a differenza di Nominatim)
  - Senza questo, un deploy pubblico collassa al primo fan-out di tool

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

- [ ] **UX dati OSM incompleti**
  - `difficolta_cai=sconosciuta` e `lunghezza_km` spesso null non sono bug di codice
  - Messaging chiaro + eventuali fallback (non solo campi vuoti)

---

## Cosa già funziona (non TODO, riferimento)

- Errori `FonteNonDisponibile` leggibili e azionabili
- Nominatim stabile (con `Limitatore`)
- Tool compositi (`sentieri_verso_localita`, `valuta_gita`) nella direzione giusta
- Con raggio piccolo, `cerca_sentieri` restituisce ref OSM utili

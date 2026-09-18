# TODO — integrazione MCP online

Esiti dalla sessione reale «trekking da Torino» (2026-09-17).
Obiettivo: server performante e funzionante per uso multi-utente / transport HTTP.

Report dettagliato: canvas `report-mcp-sessione-torino` nel progetto Cursor.

---

## P1 — affidabilità e latenza percepita

- [ ] **Mirror Overpass self-hosted o istanza dedicata**
  - `overpass-api.de` non è un backend di produzione

- [ ] **OAuth + rate limit per client sul transport HTTP**
  - Parziale: `Host`/`Origin` sono validati e il bind pubblico senza
    `--allow-host` viene rifiutato (`DEVELOPMENT.md` §3.18)
  - Resta da fare l'autenticazione vera: sapere *chi* chiama, non solo da dove

---

## P2 — operabilità e uso agentico

- [ ] **Guidance agent: evitare fan-out parallelo su tool Overpass**
  - Le instructions del server aiutano; in sessione Cursor ha comunque chiamato 3 tool Overpass insieme
  - Serializzazione server-side già presente (semaforo); resta il pezzo instructions

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
- Completamento degli ID di zona valanghe, ristretto dal provider già scelto

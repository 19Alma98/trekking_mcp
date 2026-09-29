# TODO — integrazione MCP online

Obiettivo: server performante e funzionante per uso multi-utente / transport HTTP.

---

## P1 — affidabilità e latenza percepita

- [ ] **OAuth o API key per client noti (opzionale)**
  - Fatto: rate-limit inbound per IP (anche `X-Forwarded-For` con
    `HTTP_TRUST_PROXY`), accesso HTTP aperto di default
    (`DEVELOPMENT.md` §3.35)
  - Resta: sapere *chi* chiama e quote differenziate, senza chiudere
    l'anonimo finche' non serve

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
- Backpressure Overpass (semaforo + Retry-After numerico/HTTP-date + jitter)
- Completamento degli ID di zona valanghe, ristretto dal provider già scelto
- Rate-limit inbound per IP su HTTP (rilascio aperto senza client_id; tetto LRU sui bucket)
- Coalescing HTTP atomico + `Config` con clamp su timeout/retry
- Prompt `spiega_bollettino` e tool usano `provider_per_zona` (ALBINA non e' un provider MCP)

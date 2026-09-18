from __future__ import annotations

from typing import Literal

from trekking_mcp import __version__

SITO = "https://github.com/19Alma98/trekking_mcp"

UA_DEFAULT = f"trekking-mcp/{__version__} (+{SITO})"

TERRITORI_DEFAULT = (
    "IT-21",
    "IT-23",
    "IT-25",
    "IT-32-BZ",
    "IT-32-TN",
    "IT-34",
    "IT-36",
    "IT-57",
    "CH",
)

PROVIDER_DEFAULT: Literal["aineva"] = "aineva"

LINGUA_DEFAULT: Literal["it"] = "it"

HOST_LOCALI = frozenset({"127.0.0.1", "localhost", "::1"})

ATTRIBUZIONE_OVERPASS = "Dati sentieri e ricoveri: (c) contributori OpenStreetMap, ODbL"
ATTRIBUZIONE_NOMINATIM = "Geocoding: Nominatim / (c) contributori OpenStreetMap, ODbL"
ATTRIBUZIONE_METEO = "Dati meteo: Open-Meteo.com, CC BY 4.0"
ATTRIBUZIONE_ELEVAZIONE = "Modello di elevazione: Open-Meteo / Copernicus DEM"
ATTRIBUZIONE_EAWS = "Perimetri delle zone valanghe: progetto EAWS Regions (regions.avalanches.org)"

PUNTI_PER_RICHIESTA = 100
MAX_PUNTI_QUOTE = 300
MAX_PUNTI_RESTITUITI = 100
PASSO_M_DEFAULT = 100.0

ORA_INIZIO_GIORNATA = 6

RETRY_AFTER_MAX_S = 120.0

OVERPASS_MARGINE_TIMEOUT_S = 5

OVERPASS_TESTO_MAX_LEN = 64

RIQUADRO_ITALIA = (6.6, 35.4, 18.6, 47.1)

SOGLIA_SIMILARITA = 0.55
MAX_CANDIDATI_SIMILI = 3
MAX_ESPANSIONI = 2
MAX_ELEMENTI_OVERPASS_SIMILI = 500

TIPI_UTILI_NOMINATIM = {
    "peak",
    "saddle",
    "alpine_hut",
    "wilderness_hut",
    "village",
    "hamlet",
    "town",
    "locality",
    "isolated_dwelling",
    "viewpoint",
    "valley",
}

TIPI_LUOGO: dict[str, frozenset[str]] = {
    "natural": frozenset({"peak", "saddle"}),
    "tourism": frozenset({"alpine_hut", "wilderness_hut"}),
    "place": frozenset({"village", "hamlet", "town", "locality", "isolated_dwelling"}),
}

PREFISSI_TOPONIMO = frozenset(
    {
        "monte",
        "mont",
        "monti",
        "cima",
        "pizzo",
        "col",
        "colle",
        "passo",
        "rifugio",
        "bivacco",
    }
)

URI_BOLLETTINO = "bollettino://{provider}/{zona_id}"
MAX_VALORI_COMPLETAMENTO = 100
CAMPIONI_LATENZA = 256

MS = 1000

TTL_ELENCHI_MS = 3600 * MS

TTL_SCALE_MS = 24 * 3600 * MS

RAGGIO_TERRA_KM = 6371.0

KM_PER_GRADO = 111.0

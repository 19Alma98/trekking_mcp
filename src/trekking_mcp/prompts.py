from __future__ import annotations

from mcp.server.mcpserver import MCPServer


def registra(mcp: MCPServer) -> None:
    @mcp.prompt(
        name="prepara_gita",
        title="Prepara una gita",
        description="Struttura la raccolta dati per un'uscita su un sentiero e una data.",
    )
    def prepara_gita(sentiero: str, data: str, zona_valanghe: str = "") -> str:
        zona = (
            f"Zona valanghe di riferimento: {zona_valanghe}."
            if zona_valanghe
            else "Zona valanghe non indicata: individuala dalla posizione del sentiero prima di procedere."
        )
        return f"""Prepara l'uscita sul sentiero "{sentiero}" per il {data}.

{zona}

Procedi in quest'ordine:
1. Individua il sentiero con `cerca_sentieri` e conferma di aver preso quello giusto
   (numero, punto di partenza e arrivo). Se ci sono piu' candidati, chiedi conferma.
2. Leggi la resource `scala://difficolta-escursionistica` prima di commentare la
   difficolta', per non confondere la scala CAI con il tag OSM.
3. Usa `valuta_gita` per raccogliere ricoveri, bollettino e meteo.
4. Presenta i dati separando nettamente i FATTI (cosa dicono le fonti) dai
   SEGNALI DI ATTENZIONE.

Vincoli sulla risposta:
- Non esprimere un verdetto "si puo' andare" / "non si puo' andare".
- Cita sempre le fonti riportate nel campo `fonti`.
- Se il bollettino segnala grado 3 o superiore, rimanda esplicitamente alla
  lettura del bollettino ufficiale integrale.
"""

    @mcp.prompt(
        name="spiega_bollettino",
        title="Spiega un bollettino valanghe",
        description="Rilegge un bollettino per chi non ha dimestichezza con la terminologia EAWS.",
    )
    def spiega_bollettino(zona_id: str) -> str:
        return f"""Leggi la resource `bollettino://aineva/{zona_id}` e la resource
`scala://pericolo-valanghe`, poi spiega il bollettino a una persona che sa
camminare in montagna ma non conosce la terminologia valanghiva.

Copri, in quest'ordine: grado di pericolo e come varia con la quota; i problemi
tipici presenti e cosa significano concretamente sul terreno; le esposizioni e
le quote coinvolte.

Chiudi sempre ricordando che si tratta di una rilettura di un documento
ufficiale e che il bollettino integrale va consultato alla fonte.
"""

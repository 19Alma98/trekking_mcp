from __future__ import annotations

import argparse
import asyncio
import json

from mcp import Client
from mcp.client.session import ClientRequestContext
from mcp.types import ElicitRequestParams, ElicitResult

RISPOSTE_ELICITATION = {
    "difficolta_max": "EE",
    "attrezzatura_artva": True,
    "persone": 3,
}


async def rispondi_elicitation(context: ClientRequestContext, params: ElicitRequestParams) -> ElicitResult:
    """Callback invocato quando il server chiede qualcosa all'utente.

    Il server manda uno schema JSON piatto; si restituisce un dizionario che lo
    soddisfa. Le altre risposte possibili sono "decline" e "cancel": un client
    serio deve gestirle, perche' il rifiuto e' un esito legittimo.
    """
    richiesti = list(getattr(params, "requested_schema", {}).get("properties", {}))
    print(f"\n  [elicitation] il server chiede: {params.message}")
    print(f"  [elicitation] campi richiesti: {', '.join(richiesti) or '(nessuno)'}")

    contenuto = {k: v for k, v in RISPOSTE_ELICITATION.items() if k in richiesti}
    print(f"  [elicitation] rispondo: {contenuto}")
    return ElicitResult(action="accept", content=contenuto)


async def ispeziona(client: Client) -> None:
    print(f"Server: {client.server_info.name} v{client.server_info.version}")
    if client.instructions:
        prima_riga = client.instructions.strip().splitlines()[0]
        print(f"Istruzioni: {prima_riga}")

    print("\n--- TOOL ---")
    for t in (await client.list_tools()).tools:
        argomenti = ", ".join((t.input_schema or {}).get("properties", {}))
        strutturato = "si" if t.output_schema else "no"
        print(f"  {t.name}({argomenti})")
        print(f"      output strutturato: {strutturato}")

    print("\n--- RESOURCE ---")
    for r in (await client.list_resources()).resources:
        print(f"  {r.uri}  ({r.mime_type})")
    for t in (await client.list_resource_templates()).resource_templates:
        print(f"  {t.uri_template}  [template]")

    print("\n--- PROMPT ---")
    for p in (await client.list_prompts()).prompts:
        argomenti = ", ".join(a.name for a in (p.arguments or []))
        print(f"  /{p.name}({argomenti})")


async def prova_lettura(client: Client) -> None:
    """Legge una resource statica: non tocca la rete, quindi funziona sempre."""
    print("\n--- LETTURA RESOURCE ---")
    esito = await client.read_resource("scala://difficolta-escursionistica")
    testo = esito.contents[0].text or ""
    print(f"  scala://difficolta-escursionistica -> {len(testo)} caratteri")
    print("  " + testo.strip().splitlines()[0])


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ispeziona un server MCP")
    parser.add_argument("--url", help="URL Streamable HTTP; se assente gira in-process")
    parser.add_argument("--json", action="store_true", help="Stampa l'elenco dei tool come JSON")
    args = parser.parse_args(argv)

    if args.url:
        bersaglio: object = args.url
    else:
        from trekking_mcp.server import crea_server

        bersaglio = crea_server()

    async with Client(bersaglio, elicitation_callback=rispondi_elicitation) as client:
        if args.json:
            tool = (await client.list_tools()).tools
            print(json.dumps([t.model_dump(mode="json", exclude_none=True) for t in tool], indent=2))
            return 0

        await ispeziona(client)
        await prova_lettura(client)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

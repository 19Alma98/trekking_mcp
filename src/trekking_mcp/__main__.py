"""Entry point CLI.

    python -m trekking_mcp                      # stdio (uso locale, default)
    python -m trekking_mcp --transport http     # Streamable HTTP (deploy remoto)

Lo stesso `crea_server()` serve entrambi i casi: cambia solo come i byte
viaggiano. Se il codice dei tool dovesse sapere quale transport e' attivo,
vorrebbe dire che l'astrazione e' sbagliata.
"""

from __future__ import annotations

import argparse
import logging
import sys

from mcp.server.transport_security import TransportSecuritySettings

from trekking_mcp.server import crea_server

HOST_LOCALI = frozenset({"127.0.0.1", "localhost", "::1"})


def impostazioni_sicurezza(
    host: str,
    allow_host: list[str],
    allow_origin: list[str],
) -> TransportSecuritySettings | None:
    """Protezione da DNS rebinding per il transport HTTP.

    Restituisce `None` su localhost senza flag, per lasciare il default dell'SDK.
    """
    if not allow_host and not allow_origin:
        if host in HOST_LOCALI:
            return None
        raise ValueError(
            f"bind su {host} senza --allow-host: il server sarebbe raggiungibile da altre "
            "macchine senza validazione di Host/Origin (DNS rebinding). Indica almeno "
            "--allow-host <nome:porta>, oppure resta su --host 127.0.0.1."
        )

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allow_host,
        allowed_origins=allow_origin,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trekking-mcp", description="Server MCP per l'escursionismo alpino")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--stateless",
        action="store_true",
        help="HTTP senza sessione: adatto a deploy serverless o multi-replica.",
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help="Valore ammesso dell'header Host, es. 'trekking.example.org:*'. Ripetibile. "
        "Obbligatorio se --host non e' localhost.",
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="ORIGIN",
        help="Valore ammesso dell'header Origin, es. 'https://app.example.org'. Ripetibile.",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.transport == "stdio":
        crea_server().run(transport="stdio")
        return 0

    try:
        sicurezza = impostazioni_sicurezza(args.host, args.allow_host, args.allow_origin)
    except ValueError as exc:
        parser.error(str(exc))

    crea_server().run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=args.stateless,
        transport_security=sicurezza,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

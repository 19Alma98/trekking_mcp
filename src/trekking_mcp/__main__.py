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

from trekking_mcp.server import crea_server


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
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    mcp = crea_server()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=args.stateless,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

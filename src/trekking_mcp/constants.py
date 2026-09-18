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

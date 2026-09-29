from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_NAME = "io.github.19Alma98/trekking-mcp"


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _server() -> dict:
    return json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_server_json_esiste_e_versioni_allineate() -> None:
    py = _pyproject()
    server = _server()
    versione = py["project"]["version"]
    assert versione == "1.0.0"
    assert server["version"] == versione
    assert server["packages"][0]["version"] == versione


def test_server_json_identita_e_transport() -> None:
    server = _server()
    assert server["$schema"] == ("https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json")
    assert server["name"] == MCP_NAME
    assert server["title"] == "Sentieri e condizioni di montagna"
    assert 1 <= len(server["description"]) <= 100
    assert server["repository"] == {
        "url": "https://github.com/19Alma98/trekking_mcp",
        "source": "github",
    }
    assert server["websiteUrl"] == "https://github.com/19Alma98/trekking_mcp"
    assert "remotes" not in server
    pkg = server["packages"][0]
    assert pkg["registryType"] == "pypi"
    assert pkg["identifier"] == "trekking-mcp"
    assert pkg["runtimeHint"] == "uvx"
    assert pkg["transport"] == {"type": "stdio"}
    assert "environmentVariables" not in pkg


def test_wheel_include_i_markdown_in_data(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path)],
        cwd=ROOT,
        check=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, wheels
    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
    assert any(n.endswith("trekking_mcp/data/scala_pericolo.md") for n in names)
    assert any(n.endswith("trekking_mcp/data/scala_difficolta.md") for n in names)

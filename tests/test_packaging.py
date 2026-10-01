"""Publishing metadata must agree across pyproject, server.json, the Claude plugin files and the README."""
import json
import re
from pathlib import Path

import pytest

import mcp_server

ROOT = Path(__file__).resolve().parent.parent


def _json(relpath):
    return json.loads((ROOT / relpath).read_text())


def _pyproject():
    tomllib = pytest.importorskip("tomllib")  # stdlib on Python 3.11+
    return tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_versions_agree_everywhere():
    version = _pyproject()["project"]["version"]
    server = _json("server.json")
    assert server["version"] == version
    assert [p["version"] for p in server["packages"]] == [version]
    assert _json(".claude-plugin/plugin.json")["version"] == version


def test_server_json_package_matches_pypi_name_and_stdio_transport():
    project = _pyproject()["project"]
    package = _json("server.json")["packages"][0]
    assert package["registryType"] == "pypi"
    assert package["identifier"] == project["name"]
    assert package["transport"] == {"type": "stdio"}


def test_registry_description_fits_the_100_char_limit():
    assert 1 <= len(_json("server.json")["description"]) <= 100


def test_readme_carries_the_registry_ownership_marker():
    name = _json("server.json")["name"]
    readme = (ROOT / "README.md").read_text()
    assert re.search(rf"<!--\s*mcp-name:\s*{re.escape(name)}\s*-->", readme)


def test_console_script_target_exists():
    scripts = _pyproject()["project"]["scripts"]
    module, _, func = scripts["evalforge-lite"].partition(":")
    assert module == "evalforge_lite.mcp_server" and func == "main"
    assert callable(mcp_server.main)


def test_plugin_marketplace_and_mcp_config_are_consistent():
    plugin = _json(".claude-plugin/plugin.json")
    marketplace = _json(".claude-plugin/marketplace.json")
    assert [p["name"] for p in marketplace["plugins"]] == [plugin["name"]]
    server = _json(".mcp.json")["mcpServers"]["evalforge-lite"]
    assert server["command"] == "uvx"
    assert server["args"] == [_pyproject()["project"]["name"]]


def test_wheel_data_files_are_all_covered_by_the_package_data_glob():
    package_data = _pyproject()["tool"]["setuptools"]["package-data"]["evalforge_lite"]
    assert package_data == ["data/*.json"]
    assert list((ROOT / "data").glob("*.json"))

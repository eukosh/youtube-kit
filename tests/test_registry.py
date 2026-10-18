"""server.json is what the release job publishes to the MCP Registry."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]
SERVER = json.loads((ROOT / "server.json").read_text())


def test_readme_proves_ownership_of_the_registry_name():
    # The registry rejects a publish unless the version's PyPI README contains this marker.
    assert f"<!-- mcp-name: {SERVER['name']} -->" in (ROOT / "README.md").read_text()


def test_versions_match_the_package():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    package = SERVER["packages"][0]
    assert SERVER["version"] == package["version"] == project["version"]
    assert package["identifier"] in project["scripts"]  # uvx runs the script named after the package
    assert len(SERVER["description"]) <= 100

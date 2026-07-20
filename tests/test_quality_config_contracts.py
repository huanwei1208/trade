from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from trade_py.devtools.quality.config import load_config
from trade_py.devtools.quality.toml_compat import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_repository_quality_config_classifies_ownership_and_suppressions() -> None:
    config = load_config(REPO_ROOT)
    with (REPO_ROOT / "quality.toml").open("rb") as handle:
        raw = tomllib.load(handle)

    assert config.version == 1
    assert "engine/vendor/**" in config.excludes
    assert "**/target/**" in config.excludes
    assert "data/**" in config.protected
    assert "tests/fixtures/**" in config.fixtures
    assert raw["suppressions"]["required_fields"] == [
        "rule",
        "scope",
        "reason",
        "owner",
        "expires",
    ]
    assert raw["suppressions"]["entries"] == []


def test_python_and_frontend_dependencies_are_locked() -> None:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        pyproject = tomllib.load(handle)
    with (REPO_ROOT / "uv.lock").open("rb") as handle:
        uv_lock = tomllib.load(handle)
    package = json.loads(
        (REPO_ROOT / "trade_web/frontend/package.json").read_text(encoding="utf-8")
    )
    package_lock = json.loads(
        (REPO_ROOT / "trade_web/frontend/package-lock.json").read_text(encoding="utf-8")
    )

    dev = " ".join(pyproject["project"]["optional-dependencies"]["dev"])
    locked_python = {item["name"] for item in uv_lock["package"]}
    assert "ruff" in dev and "basedpyright" in dev
    assert {"ruff", "basedpyright"} <= locked_python
    assert {"eslint", "prettier", "typescript-eslint"} <= package["devDependencies"].keys()
    assert "@biomejs/biome" not in package["devDependencies"]
    assert package_lock["packages"][""]["devDependencies"] == package["devDependencies"]


def test_maven_formatter_is_pinned_to_java8_compatible_line() -> None:
    root = ET.parse(REPO_ROOT / "engine/tradedb-driver/pom.xml").getroot()
    namespace = {"m": "http://maven.apache.org/POM/4.0.0"}
    properties = root.find("m:properties", namespace)

    assert properties is not None
    assert properties.findtext("m:spotless.maven.version", namespaces=namespace) == "2.30.0"
    assert properties.findtext("m:google.java.format.version", namespaces=namespace) == "1.7"


def test_setup_python_installs_dev_extra() -> None:
    shell = (REPO_ROOT / "trade").read_text(encoding="utf-8")

    assert "uv sync --extra dev" in shell

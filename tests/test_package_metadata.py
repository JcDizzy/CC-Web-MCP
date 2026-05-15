from __future__ import annotations

import email
import subprocess
import zipfile
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def wheel_metadata(tmp_path_factory) -> email.message.Message:
    outdir = tmp_path_factory.mktemp("wheelhouse")
    result = subprocess.run(
        ["uv", "build", "--wheel", "--no-sources", "--out-dir", str(outdir)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = sorted(outdir.glob("cc_web_mcp-*.whl"))
    assert wheels, result.stdout + result.stderr
    with zipfile.ZipFile(wheels[-1]) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        return email.message_from_bytes(archive.read(metadata_name))


def test_wheel_metadata_keeps_runtime_dependencies_slim(wheel_metadata):
    metadata = wheel_metadata
    requirements = metadata.get_all("Requires-Dist") or []
    runtime_requirements = [item for item in requirements if "extra ==" not in item]
    runtime_text = "\n".join(runtime_requirements).lower()

    assert "mcp" in runtime_text
    assert "httpx" in runtime_text
    assert "beautifulsoup4" in runtime_text
    assert "markdownify" in runtime_text
    assert "lxml" not in runtime_text
    assert "pypdf" not in runtime_text
    assert "pytest" not in runtime_text
    assert "twine" not in runtime_text
    assert "build" not in runtime_text


def test_wheel_metadata_declares_pdf_and_dev_extras(wheel_metadata):
    metadata = wheel_metadata

    assert set(metadata.get_all("Provides-Extra") or []) >= {"pdf", "dev"}
    requirements = "\n".join(metadata.get_all("Requires-Dist") or [])
    assert 'pypdf; extra == "pdf"' in requirements
    assert 'pytest; extra == "dev"' in requirements
    assert 'twine; extra == "dev"' in requirements
    assert 'build; extra == "dev"' in requirements


def test_wheel_metadata_has_pypi_project_details(wheel_metadata):
    metadata = wheel_metadata
    urls = metadata.get_all("Project-URL") or []
    classifiers = metadata.get_all("Classifier") or []

    assert metadata["License-Expression"] == "MIT"
    assert metadata["License-File"] == "LICENSE"
    assert metadata["Author"] == "JcDizzy"
    assert metadata["Keywords"] == "claude-code,mcp,web-search,web-fetch,deepseek"
    assert "Programming Language :: Python :: 3.11" in classifiers
    assert "Programming Language :: Python :: 3.12" in classifiers
    assert "Programming Language :: Python :: 3.13" in classifiers
    assert "Homepage, https://github.com/JcDizzy/CC-Web-MCP" in urls
    assert "Repository, https://github.com/JcDizzy/CC-Web-MCP" in urls
    assert "Issues, https://github.com/JcDizzy/CC-Web-MCP/issues" in urls

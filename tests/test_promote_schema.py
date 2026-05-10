from __future__ import annotations

"""Schema-conformance tests for promoted manifests.

These tests vendor matrix-hub's exact JSON schemas
(``tests/fixtures/matrixhub_schemas/*.json``) and assert that every
manifest produced by ``promote_to_tool`` / ``promote_to_agent`` validates
against the corresponding schema.

Why this is a separate test module:
- Schema drift in matrix-hub immediately surfaces here, with a clear
  failure pointing at the offending field.
- The fixtures are byte-for-byte copies of the real schemas, so passing
  these tests is a contract that matrix-hub's ingest will accept what
  we produce.

If you update a schema in matrix-hub, refresh the vendored copy:

    cp <matrix-hub>/schemas/*.json \
       <mcp_ingest>/tests/fixtures/matrixhub_schemas/
"""

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
from jsonschema import Draft202012Validator  # noqa: E402

from mcp_ingest.registry.promote import (  # noqa: E402
    promote_to_agent,
    promote_to_tool,
)


SCHEMAS_DIR = Path(__file__).parent / "fixtures" / "matrixhub_schemas"


def _load_schema(filename: str) -> dict:
    return json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tool_validator() -> Draft202012Validator:
    return Draft202012Validator(_load_schema("tool.manifest.schema.json"))


@pytest.fixture(scope="module")
def agent_validator() -> Draft202012Validator:
    return Draft202012Validator(_load_schema("agent.manifest.schema.json"))


# ---------- helpers ----------


def _server(
    *,
    name: str = "io.github.foo/weather",
    description: str = (
        "Fetch current weather, forecasts, and alerts for any location worldwide."
    ),
    transport: str = "STDIO",
    tags: list[str] | None = None,
    license_: str | None = "MIT",
    version: str = "1.0.0",
    package_type: str = "npm",
    package_id: str = "weather-mcp",
    package_version: str = "1.0.0",
    remote_url: str | None = None,
) -> dict:
    server: dict = {
        "type": "mcp_server",
        "id": f"mcp.{name.replace('/', '-').replace('.', '-')}.{transport.lower()}.cafef00d01",
        "name": name,
        "description": description,
        "version": version,
        "lifecycle": {"status": "active"},
        "tags": tags or [],
        "license": license_,
        "links": {"repository": "https://github.com/foo/weather-mcp"},
        "packages": [],
        "remotes": [],
        "mcp_registration": {"server": {}},
        "provenance": {"identity_key": "cafef00d01"},
    }

    if package_type:
        server["packages"].append(
            {
                "registryType": package_type,
                "identifier": package_id,
                "version": package_version,
            }
        )

    if transport == "STDIO":
        server["mcp_registration"]["server"] = {
            "transport": "STDIO",
            "exec": {"cmd": ["npx", f"{package_id}@{package_version}"], "env": {}},
        }
    else:
        url = remote_url or "https://example.com/mcp"
        server["remotes"].append({"transport": transport, "url": url})
        server["mcp_registration"]["server"] = {"transport": transport, "url": url}

    return server


def _format_errors(errors) -> str:
    lines = []
    for err in errors:
        loc = ".".join(str(p) for p in err.absolute_path) or "<root>"
        lines.append(f"  - {loc}: {err.message}")
    return "\n".join(lines) or "(none)"


# ---------- tool conformance ----------


@pytest.mark.parametrize(
    "kwargs",
    [
        # The watsonx case from the live registry — npm package, STDIO.
        dict(
            name="io.github.expertvagabond/watsonx",
            description="IBM watsonx.ai MCP server for Claude integration.",
            package_type="npm",
            package_id="watsonx-mcp-server",
            package_version="1.0.1",
            transport="STDIO",
        ),
        # PyPI / uvx style server.
        dict(
            name="io.github.foo/pdf-tools",
            description="Extract, convert, and summarise PDFs from local files or URLs.",
            package_type="pypi",
            package_id="pdf-tools-mcp",
            package_version="0.5.2",
            transport="STDIO",
        ),
        # Remote SSE server.
        dict(
            name="ai.cueapi/mcp",
            description="CueAPI's hosted MCP endpoint for orchestration.",
            package_type="",
            package_id="",
            package_version="",
            transport="SSE",
            remote_url="https://api.cueapi.io/mcp/sse",
        ),
        # OCI / docker server.
        dict(
            name="io.github.foo/oci-server",
            description="Containerised MCP server distributed via OCI registry.",
            package_type="oci",
            package_id="ghcr.io/foo/oci-server",
            package_version="2.1.0",
            transport="STDIO",
        ),
        # Server missing license — promote.py must default it.
        dict(
            name="io.github.foo/no-license",
            description="A useful MCP server with sketchy provenance and no license metadata yet.",
            package_type="npm",
            package_id="no-license-mcp",
            package_version="0.1.0",
            transport="STDIO",
            license_=None,
        ),
        # Server with non-SemVer version — promote.py must normalise it.
        dict(
            name="io.github.foo/latest-version",
            description="Server that ships ``latest`` instead of a real version. Annoying but real.",
            package_type="npm",
            package_id="latest-mcp",
            package_version="latest",
            transport="STDIO",
            version="latest",
        ),
    ],
    ids=[
        "watsonx_npm_stdio",
        "pypi_stdio",
        "remote_sse",
        "oci_stdio",
        "missing_license",
        "non_semver_version",
    ],
)
def test_promoted_tool_validates_against_matrixhub_tool_schema(
    tool_validator: Draft202012Validator, kwargs: dict
) -> None:
    parent = _server(**kwargs)
    tool = promote_to_tool(parent)
    assert tool is not None, "tool promotion returned None"
    errors = list(tool_validator.iter_errors(tool))
    assert not errors, (
        "Promoted tool failed matrix-hub schema validation:\n"
        + _format_errors(errors)
    )


# ---------- agent conformance ----------


@pytest.mark.parametrize(
    "kwargs",
    [
        # Name-suffix agent over an npm STDIO transport.
        dict(
            name="io.github.foo/research-agent",
            description="An autonomous agent that browses the web, summarises findings, and cites sources.",
            package_type="npm",
            package_id="research-agent",
            package_version="1.0.0",
            transport="STDIO",
        ),
        # Description-signal agent over an SSE remote — schema requires
        # transport mapping (SSE -> HTTP).
        dict(
            name="io.github.foo/planner",
            description="An autonomous agent for task planning and tool-use orchestration.",
            package_type="",
            package_id="",
            package_version="",
            transport="SSE",
            remote_url="https://planner.example.com/mcp/sse",
        ),
        # Tag-signal agent.
        dict(
            name="io.github.foo/calendar",
            description="Manage calendars: create, list, and reschedule events from natural language.",
            package_type="npm",
            package_id="calendar-agent",
            package_version="1.0.0",
            transport="STDIO",
            tags=["agent"],
        ),
    ],
    ids=["name_suffix_stdio", "description_signal_sse", "tag_signal_npm"],
)
def test_promoted_agent_validates_against_matrixhub_agent_schema(
    agent_validator: Draft202012Validator, kwargs: dict
) -> None:
    parent = _server(**kwargs)
    agent = promote_to_agent(parent)
    assert agent is not None, "agent promotion returned None"
    errors = list(agent_validator.iter_errors(agent))
    assert not errors, (
        "Promoted agent failed matrix-hub schema validation:\n"
        + _format_errors(errors)
    )


# ---------- spot-checks ----------


def test_promoted_tool_id_matches_schema_id_pattern(
    tool_validator: Draft202012Validator,
) -> None:
    parent = _server()
    tool = promote_to_tool(parent)
    # Pattern: ^[a-z0-9][a-z0-9._-]*$
    import re

    assert re.match(r"^[a-z0-9][a-z0-9._-]*$", tool["id"]), tool["id"]


def test_promoted_tool_version_matches_schema_pattern() -> None:
    parent = _server(version="1.2.3-beta.4")
    tool = promote_to_tool(parent)
    import re

    assert re.match(r"^[0-9]+(\.[0-9]+)*([-.][0-9A-Za-z.]+)?$", tool["version"])


def test_promoted_tool_omits_optional_uri_fields_when_missing(
    tool_validator: Draft202012Validator,
) -> None:
    """Regression: when the parent has no repo / homepage, optional URI
    fields must be OMITTED, not emitted as ``null`` (which violates the
    ``type: string`` constraint and used to fail ~30% of real entries)."""
    parent = _server()
    parent["links"] = {}  # strip homepage / repository
    tool = promote_to_tool(parent)
    assert "homepage" not in tool
    assert "source_url" not in tool
    errors = list(tool_validator.iter_errors(tool))
    assert not errors, _format_errors(errors)


def test_promoted_agent_omits_optional_uri_fields_when_missing(
    agent_validator: Draft202012Validator,
) -> None:
    parent = _server(name="io.github.foo/research-agent")
    parent["links"] = {}
    agent = promote_to_agent(parent)
    assert "homepage" not in agent
    assert "source_url" not in agent
    errors = list(agent_validator.iter_errors(agent))
    assert not errors, _format_errors(errors)

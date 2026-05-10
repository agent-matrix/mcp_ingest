from __future__ import annotations

"""Unit tests for mcp_ingest.registry.normalize.

Offline, deterministic tests covering the runtimeHint inference and
version-separator behaviour. Regression-protects the watsonx fix where
the normalizer used to disable npm packages whose registry payload
omitted the optional `runtimeHint` field.
"""

import pytest

from mcp_ingest.registry.normalize import (
    normalize_registry_server,
    to_stdio_exec,
)


# ---------- to_stdio_exec ----------


def test_to_stdio_exec_npm_without_runtime_hint_infers_npx() -> None:
    pkg = {"registryType": "npm", "identifier": "watsonx-mcp-server", "version": "1.0.1"}
    assert to_stdio_exec(pkg) == {
        "cmd": ["npx", "watsonx-mcp-server@1.0.1"],
        "env": {},
    }


def test_to_stdio_exec_pypi_without_runtime_hint_infers_uvx() -> None:
    pkg = {"registryType": "pypi", "identifier": "some-mcp", "version": "0.2.0"}
    assert to_stdio_exec(pkg) == {
        "cmd": ["uvx", "some-mcp==0.2.0"],
        "env": {},
    }


def test_to_stdio_exec_oci_without_runtime_hint_infers_docker_with_tag() -> None:
    pkg = {"registryType": "oci", "identifier": "ghcr.io/org/img", "version": "1.2.3"}
    assert to_stdio_exec(pkg) == {
        "cmd": ["docker", "ghcr.io/org/img:1.2.3"],
        "env": {},
    }


def test_to_stdio_exec_explicit_runtime_hint_wins_with_correct_separator() -> None:
    pkg = {
        "registryType": "npm",
        "identifier": "weather-mcp",
        "version": "0.1.0",
        "runtimeHint": "npx",
    }
    assert to_stdio_exec(pkg) == {"cmd": ["npx", "weather-mcp@0.1.0"], "env": {}}


def test_to_stdio_exec_runtime_arguments_are_preserved_before_identifier() -> None:
    pkg = {
        "registryType": "pypi",
        "identifier": "mcp-tool",
        "version": "9.9.9",
        "runtimeHint": "uvx",
        "runtimeArguments": ["--from", "git+https://example/x"],
    }
    assert to_stdio_exec(pkg) == {
        "cmd": ["uvx", "--from", "git+https://example/x", "mcp-tool==9.9.9"],
        "env": {},
    }


def test_to_stdio_exec_no_version_falls_back_to_unpinned_command() -> None:
    pkg = {"registryType": "npm", "identifier": "weather-mcp"}
    assert to_stdio_exec(pkg) == {"cmd": ["npx", "weather-mcp"], "env": {}}


def test_to_stdio_exec_missing_identifier_returns_none() -> None:
    pkg = {"registryType": "npm", "version": "1.0.0"}
    assert to_stdio_exec(pkg) is None


def test_to_stdio_exec_unknown_registry_type_without_hint_returns_none() -> None:
    pkg = {"registryType": "rubygems", "identifier": "foo", "version": "1.0.0"}
    assert to_stdio_exec(pkg) is None


def test_to_stdio_exec_registry_type_is_case_insensitive() -> None:
    pkg = {"registryType": "NPM", "identifier": "weather-mcp", "version": "0.1.0"}
    assert to_stdio_exec(pkg) == {"cmd": ["npx", "weather-mcp@0.1.0"], "env": {}}


# ---------- normalize_registry_server: end-to-end manifest shape ----------


def _watsonx_payload() -> dict:
    """The exact registry payload shape that produced the watsonx bug.

    Reproduced from
    raw.githubusercontent.com/agent-matrix/catalog/main/servers/
    io-github-expertvagabond/.../manifest.json
    """
    return {
        "server": {
            "name": "io.github.ExpertVagabond/watsonx",
            "description": "IBM watsonx.ai MCP server for Claude integration",
            "version": "1.0.1",
            "repository": "https://github.com/ExpertVagabond/watsonx-mcp-server.git",
            "packages": [
                {
                    "registryType": "npm",
                    "identifier": "watsonx-mcp-server",
                    "version": "1.0.1",
                }
            ],
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "status": "active",
                "publishedAt": "2026-02-14T17:16:26.586490Z",
                "updatedAt": "2026-02-14T17:16:26.586490Z",
            }
        },
    }


def test_normalize_watsonx_is_active_after_fix() -> None:
    """Regression: watsonx must come out active, not disabled."""
    manifests = normalize_registry_server(_watsonx_payload(), "https://registry.modelcontextprotocol.io")
    assert len(manifests) == 1
    m = manifests[0]
    assert m["lifecycle"]["status"] == "active"
    assert "reason" not in m["lifecycle"]
    exec_block = m["mcp_registration"]["server"]["exec"]
    assert exec_block["cmd"] == ["npx", "watsonx-mcp-server@1.0.1"]


def test_normalize_disabled_when_identifier_missing() -> None:
    payload = {
        "server": {
            "name": "io.github.test/broken",
            "version": "0.1.0",
            "packages": [{"registryType": "npm", "version": "0.1.0"}],
        }
    }
    [m] = normalize_registry_server(payload, "https://x")
    assert m["lifecycle"]["status"] == "disabled"
    assert "identifier" in m["lifecycle"]["reason"]


def test_normalize_disabled_when_registry_type_unknown_and_no_hint() -> None:
    payload = {
        "server": {
            "name": "io.github.test/exotic",
            "version": "0.1.0",
            "packages": [
                {"registryType": "rubygems", "identifier": "foo", "version": "0.1.0"}
            ],
        }
    }
    [m] = normalize_registry_server(payload, "https://x")
    assert m["lifecycle"]["status"] == "disabled"
    assert "rubygems" in m["lifecycle"]["reason"]


def test_normalize_remote_sse_manifest_is_active() -> None:
    payload = {
        "server": {
            "name": "io.github.test/remote",
            "version": "1.0.0",
            "remotes": [
                {"transport": "SSE", "url": "https://example.com/mcp/sse"}
            ],
        }
    }
    [m] = normalize_registry_server(payload, "https://x")
    assert m["mcp_registration"]["server"]["transport"] == "SSE"
    assert m["mcp_registration"]["server"]["url"] == "https://example.com/mcp/sse"
    assert m["lifecycle"]["status"] == "active"

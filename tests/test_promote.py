from __future__ import annotations

"""Unit tests for mcp_ingest.registry.promote.

The promotion layer turns each high-quality `mcp_server` manifest into
sibling `tool` and (when warranted) `agent` catalog entries so the
MatrixHub homepage tabs aren't empty. Tests are offline, deterministic,
and protect three properties:

1. Quality gates filter junk before it reaches the catalog.
2. One-click install survives promotion (parent's mcp_registration is
   preserved under ``mcp_registration_source``).
3. IDs are stable across runs (idempotency, no PR churn).

Schema-level validation (matrix-hub's tool/agent JSON schemas) lives in
``test_promote_schema.py`` so failures are easy to localise.
"""

import pytest

from mcp_ingest.registry.promote import (
    derive_tags,
    has_agent_signal,
    promote_to_agent,
    promote_to_tool,
)


# ---------- fixtures ----------


def _server_manifest(
    name: str = "io.github.foo/calendar",
    description: str = "Create, list, and update Google Calendar events from natural language requests.",
    status: str = "active",
    transport: str = "STDIO",
    tags: list[str] | None = None,
    title: str | None = None,
    version: str = "1.0.0",
    license_: str = "MIT",
) -> dict:
    return {
        "type": "mcp_server",
        "id": f"mcp.{name.replace('/', '-').replace('.', '-')}.{transport.lower()}.deadbeef01",
        "name": name,
        "title": title,
        "description": description,
        "version": version,
        "lifecycle": {"status": status},
        "tags": tags or [],
        "license": license_,
        "links": {"repository": "https://github.com/foo/calendar"},
        "packages": [
            {"registryType": "npm", "identifier": "calendar-mcp", "version": "1.0.0"}
        ] if transport == "STDIO" else [],
        "remotes": [
            {"transport": transport, "url": "https://example.com/mcp"}
        ] if transport != "STDIO" else [],
        "mcp_registration": {
            "server": (
                {"transport": "STDIO", "exec": {"cmd": ["npx", "calendar-mcp@1.0.0"], "env": {}}}
                if transport == "STDIO"
                else {"transport": transport, "url": "https://example.com/mcp"}
            )
        },
        "provenance": {"source": "mcp-registry", "identity_key": "deadbeef01"},
    }


# ---------- promote_to_tool ----------


def test_tool_promotion_preserves_parent_registration_under_source_key() -> None:
    """The install button must work on a promoted tool. The parent's
    full mcp_registration block is round-tripped under
    ``mcp_registration_source`` so STDIO exec commands aren't lost."""
    parent = _server_manifest()
    tool = promote_to_tool(parent)
    assert tool is not None
    assert tool["type"] == "tool"
    assert tool["mcp_registration_source"] == parent["mcp_registration"]


def test_tool_promotion_emits_schema_required_fields() -> None:
    parent = _server_manifest()
    tool = promote_to_tool(parent)
    for field in (
        "schema_version", "type", "id", "name", "version",
        "description", "artifacts", "license", "mcp_registration",
    ):
        assert field in tool, f"missing required field: {field}"
    assert tool["schema_version"] == 1
    assert tool["mcp_registration"]["tool"]["integration_type"] == "MCP"
    assert tool["mcp_registration"]["tool"]["request_type"] == "POST"


def test_tool_promotion_artifacts_are_non_empty() -> None:
    parent = _server_manifest()
    tool = promote_to_tool(parent)
    assert isinstance(tool["artifacts"], list)
    assert len(tool["artifacts"]) >= 1
    for art in tool["artifacts"]:
        assert "kind" in art and "spec" in art
        assert art["kind"] in {"pypi", "oci", "git", "zip", "other"}
        assert isinstance(art["spec"], dict) and len(art["spec"]) >= 1


def test_tool_promotion_license_defaults_when_missing() -> None:
    parent = _server_manifest(license_="")
    parent["license"] = None
    tool = promote_to_tool(parent)
    assert tool["license"] == "Unknown"


def test_tool_promotion_links_back_to_parent() -> None:
    parent = _server_manifest()
    tool = promote_to_tool(parent)
    assert tool["provided_by"]["kind"] == "mcp_server"
    assert tool["provided_by"]["id"] == parent["id"]
    assert tool["provided_by"]["transport"] == "STDIO"


def test_tool_promotion_id_is_stable_across_runs() -> None:
    """Re-running the promotion on the same parent must yield the same
    ID, otherwise every sync produces churny PRs."""
    parent = _server_manifest()
    a = promote_to_tool(parent)
    b = promote_to_tool(parent)
    assert a["id"] == b["id"]
    assert a["id"].startswith("tool.")


def test_tool_promotion_skips_disabled_parent() -> None:
    parent = _server_manifest(status="disabled")
    assert promote_to_tool(parent) is None


def test_tool_promotion_skips_deprecated_parent() -> None:
    parent = _server_manifest(status="deprecated")
    assert promote_to_tool(parent) is None


def test_tool_promotion_skips_short_description() -> None:
    """Quality gate: don't pollute the Tools tab with low-signal entries."""
    parent = _server_manifest(description="A tool.")
    assert promote_to_tool(parent) is None


def test_tool_promotion_skips_missing_description() -> None:
    parent = _server_manifest(description="")
    assert promote_to_tool(parent) is None


def test_tool_promotion_inherits_lifecycle_active() -> None:
    parent = _server_manifest()
    tool = promote_to_tool(parent)
    assert tool["lifecycle"]["status"] == "active"


def test_tool_promotion_records_promotion_provenance() -> None:
    parent = _server_manifest()
    tool = promote_to_tool(parent)
    assert tool["provenance"]["source"] == "promotion:tool-from-mcp"
    assert tool["provenance"]["promoted_from"] == parent["id"]


def test_tool_promotion_works_for_remote_sse_server() -> None:
    parent = _server_manifest(transport="SSE")
    tool = promote_to_tool(parent)
    assert tool is not None
    assert tool["mcp_registration_source"]["server"]["transport"] == "SSE"
    assert tool["provided_by"]["transport"] == "SSE"
    # SSE servers expose a real URL — install_url should pick it up
    assert tool["mcp_registration"]["tool"]["url"] == "https://example.com/mcp"


def test_tool_promotion_install_url_falls_back_for_stdio() -> None:
    """STDIO has no real URL; we must still satisfy the schema."""
    parent = _server_manifest(transport="STDIO")
    parent["links"] = {}  # remove homepage / repo too
    tool = promote_to_tool(parent)
    url = tool["mcp_registration"]["tool"]["url"]
    # Should be a synthetic mcp+stdio URI built from the package data
    assert url.startswith("mcp+stdio://")


def test_tool_promotion_normalises_unsupported_version_string() -> None:
    parent = _server_manifest(version="latest")
    tool = promote_to_tool(parent)
    assert tool["version"] == "0.0.0"


def test_tool_promotion_derives_title_from_name_when_missing() -> None:
    """Easy/simple: humans read titles, not slugs."""
    parent = _server_manifest(name="io.github.foo/calendar", title=None)
    tool = promote_to_tool(parent)
    assert tool["title"] == "Calendar"


def test_tool_promotion_keeps_explicit_title() -> None:
    parent = _server_manifest(name="io.github.foo/calendar", title="Google Calendar Pro")
    tool = promote_to_tool(parent)
    assert tool["title"] == "Google Calendar Pro"


# ---------- promote_to_agent ----------


def test_agent_promotion_requires_signal() -> None:
    """A regular calendar tool isn't an agent."""
    parent = _server_manifest(name="io.github.foo/calendar")
    assert promote_to_agent(parent) is None


def test_agent_promotion_triggers_on_name_suffix() -> None:
    parent = _server_manifest(name="io.github.foo/research-agent")
    agent = promote_to_agent(parent)
    assert agent is not None
    assert agent["type"] == "agent"


def test_agent_promotion_triggers_on_description_keywords() -> None:
    parent = _server_manifest(
        description="An autonomous agent that researches topics and writes summaries.",
    )
    agent = promote_to_agent(parent)
    assert agent is not None


def test_agent_promotion_triggers_on_explicit_tag() -> None:
    parent = _server_manifest(tags=["agent"])
    agent = promote_to_agent(parent)
    assert agent is not None


def test_agent_promotion_emits_schema_required_fields() -> None:
    parent = _server_manifest(name="io.github.foo/research-agent")
    agent = promote_to_agent(parent)
    for field in (
        "schema_version", "type", "id", "name", "version",
        "description", "artifacts", "license",
    ):
        assert field in agent, f"missing required field: {field}"


def test_agent_promotion_carries_install_metadata() -> None:
    parent = _server_manifest(name="io.github.foo/research-agent")
    agent = promote_to_agent(parent)
    assert agent["mcp_registration_source"] == parent["mcp_registration"]
    assert agent["bundle"]["mcp_servers"] == [parent["id"]]


def test_agent_promotion_remaps_sse_to_http_in_schema_transport() -> None:
    """The agent schema accepts only WEBSOCKET/HTTP/STDIO; SSE must be folded into HTTP."""
    parent = _server_manifest(name="io.github.foo/research-agent", transport="SSE")
    agent = promote_to_agent(parent)
    assert agent["mcp_registration"]["server"]["transport"] == "HTTP"
    # ...but the original transport is still discoverable for installers
    assert agent["mcp_registration_source"]["server"]["transport"] == "SSE"


def test_agent_promotion_id_is_stable() -> None:
    parent = _server_manifest(name="io.github.foo/research-agent")
    a = promote_to_agent(parent)
    b = promote_to_agent(parent)
    assert a["id"] == b["id"]
    assert a["id"].startswith("agent.")


def test_agent_promotion_skips_disabled() -> None:
    parent = _server_manifest(name="io.github.foo/research-agent", status="disabled")
    assert promote_to_agent(parent) is None


# ---------- derive_tags ----------


def test_derive_tags_from_namespaced_server_name() -> None:
    tags = derive_tags("io.github.foo/calendar", "Manage calendar events.", existing=[])
    assert "calendar" in tags


def test_derive_tags_dedupes_with_existing() -> None:
    tags = derive_tags(
        "io.github.foo/calendar",
        "Manage calendar events.",
        existing=["calendar", "google"],
    )
    assert tags.count("calendar") == 1
    assert "google" in tags


def test_derive_tags_falls_back_to_description_when_leaf_is_stopword() -> None:
    """If the leaf is just `mcp` (a stopword), tags must still be useful
    by mining the description. Without this, search filters break for
    the many `<vendor>/mcp`-named servers."""
    tags = derive_tags(
        "ac.inference.sh/mcp",
        "Inference engine for image generation, video, audio.",
        existing=[],
    )
    # The leaf 'mcp' is filtered, but description keywords come through.
    assert any(k in tags for k in ("inference", "image", "video", "audio", "generation"))


def test_derive_tags_returns_lowercase_unique_sorted() -> None:
    tags = derive_tags(
        "io.github.foo/Browser-Use",
        "Browser automation: navigate, click, extract DOM.",
        existing=["Browser"],
    )
    assert tags == sorted(set(tag.lower() for tag in tags))


# ---------- has_agent_signal ----------


@pytest.mark.parametrize(
    "name,description,tags,expected",
    [
        ("io.github.foo/calendar", "Just a calendar tool.", [], False),
        ("io.github.foo/research-agent", "anything", [], True),
        ("io.github.foo/agent-x", "anything", [], True),
        ("io.github.foo/researchagent", "anything", [], False),  # needs separator
        ("io.github.foo/foo", "An autonomous agent for X.", [], True),
        ("io.github.foo/foo", "anything", ["agent"], True),
        ("io.github.foo/foo", "anything", ["agentic"], True),
        ("io.github.foo/foo", "Use this agent in production.", [], False),  # bare 'agent' alone is not enough
    ],
)
def test_has_agent_signal(name, description, tags, expected) -> None:
    assert has_agent_signal(name, description, tags) is expected

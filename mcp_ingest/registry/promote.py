"""Promote MCP server manifests into sibling `tool` and `agent` catalog entries.

Why this exists
---------------
The MCP Registry only emits `mcp_server` items. MatrixHub's homepage has
three tabs (Agents / Tools / MCP), so without promotion the Agents and
Tools tabs render empty.

What this module does
---------------------
For each high-quality `mcp_server` manifest produced by
``normalize_registry_server``:

- ``promote_to_tool`` always emits a sibling ``tool`` manifest that
  preserves the parent's ``mcp_registration`` block byte-for-byte (under
  ``mcp_registration_source``) so the one-click install button can use
  the actual transport. The schema-required ``mcp_registration.tool``
  block is synthesised in the HTTP/REST/MCP shape that
  matrix-hub's tool schema demands.
- ``promote_to_agent`` only fires when the parent shows agent signal
  (name suffix, description keywords, or an explicit ``agent`` tag).
  This keeps the Agents tab high-signal.

Schema compliance
-----------------
matrix-hub validates every manifest against a strict JSON schema at
ingest time. To make sure promoted entries actually land in the database
(and therefore in MatrixHub search), the manifests we emit conform to:

- agent.manifest.schema.json
- tool.manifest.schema.json

Specifically each promoted manifest carries:

- ``schema_version: 1``
- ``id`` matching ``^[a-z0-9][a-z0-9._-]*$``
- ``version`` matching the SemVer-ish pattern (with a safe ``"0.0.0"`` fallback)
- ``description`` (>= 1 char) and ``license`` (defaulted to ``"Unknown"``)
- ``artifacts`` with at least one ``{kind, spec}`` entry, synthesised
  from the parent's ``packages[]`` or ``remotes[]``
- ``mcp_registration.tool`` (for tool manifests) with the required
  ``name`` / ``integration_type`` / ``request_type`` / ``url`` /
  ``input_schema`` fields

Quality gates
-------------
- Parent must be ``active``. Disabled / deprecated servers are skipped.
- Description must be present and at least ``MIN_DESCRIPTION_CHARS``
  characters long. Below that the entry would be useless to a browsing
  user and search would surface noise.

Idempotency
-----------
Promoted IDs are deterministic functions of the parent's identity_key
and the promotion target, so re-running the harvester does not produce
churny PRs against the catalog repo.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "MIN_DESCRIPTION_CHARS",
    "derive_tags",
    "has_agent_signal",
    "promote_to_agent",
    "promote_to_tool",
]


# ----- tunables ---------------------------------------------------------------

# Below this length, a description tells a browsing user nothing useful
# and search will return noise. Tune in PRs, not at call sites.
MIN_DESCRIPTION_CHARS: int = 30

# Cap on description-derived tags. Keeps the search surface tight when a
# server ships a long marketing description.
_MAX_DESC_TAGS: int = 6

# Regex for detecting agent-suffixed names (e.g. `research-agent`,
# `code_agent`, `foo/agent-x`). Anchored at word boundaries so that
# `agentkit` and `researchagent` do NOT match.
_AGENT_NAME_RE = re.compile(r"(?:^|[/_\-])agent(?:[/_\-]|$)", re.IGNORECASE)

# Description-level signal: requires both the literal token "agent" AND a
# corroborating word so that "use this agent in production" alone does not
# falsely promote.
_AGENT_DESC_RE = re.compile(
    r"\bagent\b.*\b(autonomous|task|workflow|reason|plan|tool[- ]?use)\b"
    r"|\b(autonomous|task)\b.*\bagent\b",
    re.IGNORECASE | re.DOTALL,
)

# Stop-words for tag derivation (these add no search value)
_TAG_STOPWORDS: frozenset[str] = frozenset(
    {
        # grammar
        "the", "a", "an", "and", "or", "of", "for", "with", "to", "in", "on",
        "is", "as", "from", "by", "via", "are", "be", "it", "that", "this",
        "any", "all", "your", "you", "our", "us", "we", "they", "them",
        # marketing fluff
        "use", "using", "easy", "simple", "fast", "quick", "powerful",
        "best", "great", "new", "free", "open", "official", "powered",
        # protocol/category names that are redundant given the type tab
        "mcp", "server", "tool", "agent", "io", "github", "com", "ai", "app",
    }
)

_WORD_RE = re.compile(r"[a-z0-9]+")

# Schema-required fallbacks
_DEFAULT_LICENSE: str = "Unknown"
_DEFAULT_VERSION: str = "0.0.0"
_VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+)*([-.][0-9A-Za-z.]+)?$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# matrix-hub's agent.manifest schema accepts only these transports for
# the embedded mcpServer; SSE is intentionally absent. We map our
# registry-flavoured transports into that vocabulary.
_AGENT_TRANSPORT_MAP: dict[str, str] = {
    "STDIO": "STDIO",
    "SSE": "HTTP",
    "WS": "WEBSOCKET",
    "WEBSOCKET": "WEBSOCKET",
    "HTTP": "HTTP",
    "STREAMABLE_HTTP": "HTTP",
}


# ----- helpers ----------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _short_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:10]


def _safe_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-") or "unknown"


def _humanize(name: str) -> str:
    """``io.github.foo/research-agent`` -> ``Research Agent``."""
    leaf = name.rsplit("/", 1)[-1] if name else "Untitled"
    parts = re.split(r"[-_.]+", leaf)
    return " ".join(p.capitalize() for p in parts if p) or "Untitled"


def _is_active(parent: dict[str, Any]) -> bool:
    return (parent.get("lifecycle") or {}).get("status") == "active"


def _description_long_enough(parent: dict[str, Any]) -> bool:
    desc = (parent.get("description") or "").strip()
    return len(desc) >= MIN_DESCRIPTION_CHARS


def _safe_version(raw: str | None) -> str:
    """Return a value matching the schema's version pattern.

    The MCP Registry sometimes ships versions like ``"latest"`` or empty
    strings that do not match SemVer. matrix-hub's schema rejects those,
    so we fall back to ``_DEFAULT_VERSION`` to keep the manifest valid.
    """
    candidate = (raw or "").strip()
    if candidate and _VERSION_RE.match(candidate):
        return candidate
    return _DEFAULT_VERSION


def _safe_id(prefix: str, slug: str, hashbit: str) -> str:
    """Produce a schema-conforming id (``^[a-z0-9][a-z0-9._-]*$``).

    Inputs are already lowercased and slugged, but defensive validation
    here means an unexpected upstream value can't silently break the
    catalog.
    """
    candidate = f"{prefix}.{slug}.{hashbit}"
    if _ID_RE.match(candidate):
        return candidate
    # Fallback path: rebuild from a hash of the original to guarantee
    # the regex passes.
    fallback = f"{prefix}.{_short_hash(candidate)}"
    return fallback


def _synthesize_artifacts(parent: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a non-empty list of catalog-compliant ``{kind, spec}`` entries.

    The matrix-hub schema requires ``minItems: 1`` for ``artifacts``.
    We map registry-native package shapes onto the schema's ``kind`` enum
    (``pypi`` / ``oci`` / ``git`` / ``zip`` / ``other``):

    - ``registryType: pypi``  -> ``kind: pypi``
    - ``registryType: oci|docker`` -> ``kind: oci``
    - everything else (npm, github, etc.)  -> ``kind: other``
    - SSE/HTTP remotes        -> ``kind: other`` with ``{url, transport}``

    If the parent has neither packages nor remotes, we emit a single
    ``{kind: "other", spec: {note: "no installable artifact"}}`` row so
    the manifest still satisfies ``minItems: 1``.
    """
    artifacts: list[dict[str, Any]] = []

    for pkg in parent.get("packages") or []:
        reg_type = (pkg.get("registryType") or "").strip().lower()
        identifier = pkg.get("identifier")
        version = pkg.get("version")

        if reg_type == "pypi":
            spec: dict[str, Any] = {"package": identifier or "unknown"}
            if version:
                spec["version"] = version
            artifacts.append({"kind": "pypi", "spec": spec})
        elif reg_type in ("oci", "docker"):
            spec = {"image": identifier or "unknown"}
            if version:
                spec["tag"] = version
            artifacts.append({"kind": "oci", "spec": spec})
        else:
            spec = {"registry": reg_type or "unknown"}
            if identifier:
                spec["package"] = identifier
            if version:
                spec["version"] = version
            artifacts.append({"kind": "other", "spec": spec})

    for remote in parent.get("remotes") or []:
        url = remote.get("url")
        transport = (remote.get("transport") or remote.get("type") or "SSE").upper()
        spec = {"transport": transport}
        if url:
            spec["url"] = url
        artifacts.append({"kind": "other", "spec": spec})

    if not artifacts:
        artifacts.append(
            {
                "kind": "other",
                "spec": {"note": "no installable artifact in source manifest"},
            }
        )

    return artifacts


def _synthesize_install_url(parent: dict[str, Any]) -> str:
    """Best-effort URI for ``mcp_registration.tool.url``.

    matrix-hub's tool schema requires this field. We prefer (in order):

    1. The first remote ``url`` (for SSE / HTTP / WS servers).
    2. The parent's homepage / repository link.
    3. A synthetic ``mcp+stdio://...`` URI built from the package metadata.
    4. A final placeholder ``mcp+stdio://unknown`` so the manifest stays valid.
    """
    for remote in parent.get("remotes") or []:
        url = remote.get("url")
        if isinstance(url, str) and url.strip():
            return url.strip()

    links = parent.get("links") or {}
    for key in ("homepage", "repository", "documentation"):
        url = links.get(key)
        if isinstance(url, str) and url.strip():
            return url.strip()

    for pkg in parent.get("packages") or []:
        reg_type = (pkg.get("registryType") or "unknown").lower()
        ident = pkg.get("identifier") or "unknown"
        ver = pkg.get("version")
        suffix = f"@{ver}" if ver else ""
        return f"mcp+stdio://{reg_type}/{ident}{suffix}"

    return "mcp+stdio://unknown"


# ----- public API -------------------------------------------------------------


def derive_tags(name: str, description: str, existing: list[str]) -> list[str]:
    """Return a deterministic, deduped, lowercase tag list.

    Combines:
    - tags already on the parent (preserves curated tags from upstream)
    - leaf segment of the namespaced server name
    - non-stopword tokens from the description that are >= 4 chars

    Only the description fallback is capped (top ``_MAX_DESC_TAGS``) so
    that long help-style descriptions don't bury the curated tags.
    """
    tags: set[str] = {t.strip().lower() for t in (existing or []) if t and t.strip()}

    leaf = name.rsplit("/", 1)[-1] if name else ""
    for token in _WORD_RE.findall(leaf.lower()):
        if len(token) >= 3 and token not in _TAG_STOPWORDS:
            tags.add(token)

    desc_tags: list[str] = []
    for token in _WORD_RE.findall((description or "").lower()):
        if len(token) >= 4 and token not in _TAG_STOPWORDS and token not in tags:
            desc_tags.append(token)
            if len(desc_tags) >= _MAX_DESC_TAGS:
                break
    tags.update(desc_tags)

    return sorted(tags)


def has_agent_signal(name: str, description: str, tags: list[str]) -> bool:
    """Return True iff the server should also be surfaced as an agent.

    Conservative on purpose: false positives would inflate the Agents
    tab with non-agents and erode user trust.
    """
    name = name or ""
    description = description or ""
    tags = [t.lower() for t in (tags or [])]

    if "agent" in tags or "agentic" in tags:
        return True
    if _AGENT_NAME_RE.search(name):
        return True
    if _AGENT_DESC_RE.search(description):
        return True
    return False


def _build_provenance(parent: dict[str, Any], kind: str) -> dict[str, Any]:
    parent_prov = parent.get("provenance") or {}
    return {
        "source": f"promotion:{kind}-from-mcp",
        "promoted_from": parent.get("id"),
        "registry_base_url": parent_prov.get("registry_base_url"),
        "server_name": parent.get("name"),
        "identity_key": parent_prov.get("identity_key"),
    }


def _drop_nones(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose value is ``None`` or empty string.

    JSON Schema's ``type: string`` rejects ``null`` even on optional
    fields, so we must omit empty values rather than emit them.
    """
    return {k: v for k, v in d.items() if v not in (None, "")}


def promote_to_tool(parent: dict[str, Any]) -> dict[str, Any] | None:
    """Mint a `tool` manifest for an mcp_server, or None if quality gates fail.

    The output conforms to matrix-hub's ``tool.manifest.schema.json``:
    schema_version, artifacts (>= 1), license, and an
    HTTP/REST/MCP-shaped ``mcp_registration.tool`` block are always
    present. The parent's original ``mcp_registration`` is preserved
    under ``mcp_registration_source`` so downstream installers can still
    reach the actual transport (e.g. STDIO exec command).
    """
    if not _is_active(parent):
        return None
    if not _description_long_enough(parent):
        return None

    name = parent.get("name") or "unknown"
    parent_prov = parent.get("provenance") or {}
    variant_key = f"tool|{name}|{parent.get('id')}|{parent_prov.get('identity_key')}"
    tool_id = _safe_id("tool", _safe_slug(name), _short_hash(variant_key))

    title = parent.get("title") or _humanize(name)
    parent_registration = parent.get("mcp_registration") or {}
    parent_server = (parent_registration.get("server") or {})
    transport = parent_server.get("transport")

    install_url = _synthesize_install_url(parent)
    links = parent.get("links") or {}
    homepage = links.get("homepage") or links.get("repository")
    source_url = links.get("repository")

    manifest = {
        "schema_version": 1,
        "type": "tool",
        "id": tool_id,
        "name": name,
        "title": title,
        "summary": (parent.get("description") or "")[:280],
        "description": parent.get("description"),
        "version": _safe_version(parent.get("version")),
        "license": parent.get("license") or _DEFAULT_LICENSE,
        # Optional URI fields — only set when present so we never emit
        # ``null`` against ``type: string`` schemas.
        "homepage": homepage,
        "source_url": source_url,
        "tags": derive_tags(name, parent.get("description") or "", parent.get("tags") or []),
        "links": links,
        "artifacts": _synthesize_artifacts(parent),
        "mcp_registration": {
            "tool": {
                "name": name,
                "integration_type": "MCP",
                "request_type": "POST",
                "url": install_url,
                "input_schema": {},
                "description": (parent.get("description") or title or name)[:1024],
            }
        },
        # Round-trip the parent's original registration so the install
        # path can use the actual transport (e.g. exec for STDIO).
        "mcp_registration_source": parent_registration,
        "provided_by": {
            "kind": "mcp_server",
            "id": parent.get("id"),
            "transport": transport,
        },
        "lifecycle": {"status": "active"},
        "provenance": _build_provenance(parent, "tool"),
        "harvest": {"seen_in_latest_run": True, "last_seen_at": _utc_now_iso()},
    }
    return _drop_nones(manifest)


def promote_to_agent(parent: dict[str, Any]) -> dict[str, Any] | None:
    """Mint an `agent` manifest, or None if no agent signal / quality gate fails.

    Output conforms to matrix-hub's ``agent.manifest.schema.json``:
    schema_version, artifacts (>= 1), license. The optional
    ``mcp_registration.server`` block uses the schema's transport
    vocabulary (``WEBSOCKET`` / ``HTTP`` / ``STDIO``); SSE is mapped to
    ``HTTP`` since the schema does not list it.
    """
    if not _is_active(parent):
        return None
    if not _description_long_enough(parent):
        return None
    if not has_agent_signal(
        parent.get("name") or "",
        parent.get("description") or "",
        parent.get("tags") or [],
    ):
        return None

    name = parent.get("name") or "unknown"
    parent_prov = parent.get("provenance") or {}
    variant_key = f"agent|{name}|{parent.get('id')}|{parent_prov.get('identity_key')}"
    agent_id = _safe_id("agent", _safe_slug(name), _short_hash(variant_key))

    title = parent.get("title") or _humanize(name)
    parent_registration = parent.get("mcp_registration") or {}
    parent_server = (parent_registration.get("server") or {})
    raw_transport = (parent_server.get("transport") or "STDIO").upper()
    schema_transport = _AGENT_TRANSPORT_MAP.get(raw_transport, "HTTP")

    install_url = _synthesize_install_url(parent)
    links = parent.get("links") or {}
    homepage = links.get("homepage") or links.get("repository")
    source_url = links.get("repository")

    manifest = {
        "schema_version": 1,
        "type": "agent",
        "id": agent_id,
        "name": name,
        "title": title,
        "summary": (parent.get("description") or "")[:280],
        "description": parent.get("description"),
        "version": _safe_version(parent.get("version")),
        "license": parent.get("license") or _DEFAULT_LICENSE,
        # Optional URI fields — only set when present so we never emit
        # ``null`` against ``type: string`` schemas.
        "homepage": homepage,
        "source_url": source_url,
        "tags": sorted(
            {"agent", *derive_tags(name, parent.get("description") or "", parent.get("tags") or [])}
        ),
        "links": links,
        "artifacts": _synthesize_artifacts(parent),
        "mcp_registration": {
            "server": {
                "name": name,
                "transport": schema_transport,
                "url": install_url,
                "description": (parent.get("description") or title or name)[:1024],
            }
        },
        "mcp_registration_source": parent_registration,
        "bundle": {"mcp_servers": [parent.get("id")]},
        "lifecycle": {"status": "active"},
        "provenance": _build_provenance(parent, "agent"),
        "harvest": {"seen_in_latest_run": True, "last_seen_at": _utc_now_iso()},
    }
    return _drop_nones(manifest)

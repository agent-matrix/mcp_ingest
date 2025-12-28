# MCP Ingest

*A tiny SDK + CLI to **discover, describe, validate, and register** MCP servers, agents, and tools into MatrixHub at planet scale.*

- **SDK for authors** → `describe(...)` emits `manifest.json`/`index.json`; optional `autoinstall(...)` posts to MatrixHub.
- **CLI for operators** → `mcp-ingest harvest-repo <source>` and `pack <source>` for end‑to‑end ingest.
- **Harvester service** → internet‑scale discovery, scoring, and deferred install; keeps the catalog fresh.

> Requires **Python 3.11**. Works without MatrixHub, but integrates best with `/catalog/install`.

## Install

```bash
pip install mcp-ingest
# docs site (optional)
pip install mkdocs mkdocs-material
```

## Why MCP Ingest?

* **Mass ingest**: Catalog millions of MCP endpoints offline, install on demand.
* **Idempotent**: Safe re-runs; HTTP 409 is success; exponential backoff everywhere.
* **Standards-aware**: Normalizes SSE endpoints; supports STDIO & WS transports.
* **Production-ready**: Relative link resolution, HTTP ETag caching, stable slugging, and rich provenance metadata.
* **Automated catalogs**: Complete GitHub Actions workflows for daily catalog maintenance with validation.

## At a glance

```mermaid
flowchart LR
  A[Source: dir|git|zip] --> B[Detect]
  B --> C[Describe → manifest.json/index.json]
  C --> D{Build?}
  D -- docker --> E[Validate in container]
  E --> F{Publish?}
  F -->|S3/Pages| G[CDN index]
  C --> H{Register?}
  H -->|/catalog/install| I[MatrixHub]
```

## Production Features

### 🔗 Relative Link Resolution
Automatically resolves relative markdown links like `./src/server` from READMEs into absolute GitHub URLs. Critical for harvesting from curated repositories like `modelcontextprotocol/servers` — captures **5% more servers** that would otherwise be missed.

### 📦 Provenance Metadata
Every harvested manifest includes rich provenance tracking:
- Source repository, ref, and path
- Detector used and confidence score
- GitHub stars and forks for quality ranking
- Harvest timestamp and tool version

Perfect for deduplication, trust scoring, and understanding where servers came from.

### ⚡ HTTP ETag Caching
Intelligent HTTP caching with ETag support reduces bandwidth and API calls by **90%+**. Automatic exponential backoff for rate limiting ensures reliable harvesting at scale.

### 🏷️ Stable Slugging
Deterministic folder name generation with collision detection. Same input always produces the same slug, preventing catalog churn between sync runs.

### 🤖 Catalog Automation
Complete GitHub Actions workflows for automated catalog maintenance:
- Daily harvesting from upstream sources
- Automatic deduplication and validation
- Pull request-based workflow with comprehensive checks
- Simple `make sync` command for manual operations

See the **[Catalog Automation Guide](catalog-automation.md)** for complete setup instructions.
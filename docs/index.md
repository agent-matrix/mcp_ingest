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
````

## Why MCP Ingest?

* **Mass ingest**: Catalog millions of MCP endpoints offline, install on demand.
* **Idempotent**: Safe re-runs; HTTP 409 is success; exponential backoff everywhere.
* **Standards-aware**: Normalizes SSE endpoints; supports STDIO & WS transports.

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
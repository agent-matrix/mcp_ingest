# 🦾 MCP Ingest

*Discover, describe, and register AI agents with ease.*

<p align="center">
  <a href="https://pypi.org/project/mcp-ingest/"><img src="https://img.shields.io/pypi/v/mcp-ingest?color=blue" alt="PyPI"></a>
  <a href="https://pypi.org/project/mcp-ingest/"><img src="https://img.shields.io/pypi/pyversions/mcp-ingest.svg?logo=python" alt="Python Versions"></a>
  <a href="https://github.com/agent-matrix/mcp_ingest/actions/workflows/ci.yml">
    <img src="https://github.com/agent-matrix/mcp_ingest/actions/workflows/ci.yml/badge.svg?branch=master" alt="CI">
  </a>
  <a href="https://agent-matrix.github.io/matrix-hub/"><img src="https://img.shields.io/static/v1?label=docs&message=mkdocs&color=blue&logo=mkdocs" alt="Docs"></a>
  <a href="https://github.com/agent-matrix/mcp_ingest/blob/master/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue" alt="License: Apache-2.0"></a>
  <a href="https://github.com/ruslanmv/agent-generator"><img src="https://img.shields.io/badge/Powered%20by-agent--generator-brightgreen" alt="Powered by agent-generator"></a>
</p>


---

**`mcp-ingest`** is a tiny SDK + CLI that turns *any* MCP server/agent/tool into a **MatrixHub‑ready** artifact. It lets you:

* **Discover** servers from a folder, Git repo, or ZIP — even whole registries (harvester).
* **Describe** them offline → emit `manifest.json` + `index.json` (SSE normalized).
* **Validate** in a sandbox or container (handshake, `ListTools`, one `CallTool`).
* **Publish** to S3/GitHub Pages and **Register** to MatrixHub (`/catalog/install`).

Built for **Python 3.11**, packaged for **PyPI**, with strict lint/type/test gates.

> You can catalog **millions** of MCP candidates offline and install on demand per tenant/workspace — the fastest path to building **the Matrix** of interoperable agents and tools.

---


## Install

```bash
pip install mcp-ingest
```

For contributors:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,harvester]"
```

---

## Quickstart

### SDK (authors)

```python
from mcp_ingest import describe, autoinstall

# Generate manifest.json and index.json without running your server
paths = describe(
    name="watsonx-mcp",
    url="http://127.0.0.1:6288/sse",
    tools=["chat"],
    resources=[{"uri":"file://server.py","name":"source"}],
    description="Watsonx SSE server",
    version="0.1.0",
)
print(paths)  # {"manifest_path": "./manifest.json", "index_path": "./index.json"}

# Optionally register into MatrixHub (idempotent)
autoinstall(matrixhub_url="http://127.0.0.1:7300")
```

### CLI (operators)

```bash
# Detect → describe (offline)
mcp-ingest pack ./examples/watsonx --out dist/

# Register later (POST /catalog/install)
mcp-ingest register \
  --matrixhub http://127.0.0.1:7300 \
  --manifest dist/manifest.json
```

### Harvest a whole repo

Harvest a multi-server repository (e.g., the official MCP servers collection):

```bash
mcp-ingest harvest-repo \
  https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip \
  --out dist/servers
```

Outputs one `manifest.json` per detected server and a **repo-level `index.json`** that lists them all. Optionally `--publish s3://…` and/or `--register`.

---

## MatrixHub integration

* Preferred path: **`POST /catalog/install`** with the **inline manifest** (what `autoinstall()` and `mcp-ingest register` do). And when is installed and running the mcp server can be later imported in MCP Gateway for future use.
* **Idempotent** by design: HTTP **409** is treated as success; safe to re-run.
* **SSE normalization**: we auto-fix URLs to end in `/sse` unless the manifest explicitly requests `/messages` or a different transport.

**Deferred install**: You can *describe* millions of candidates offline, then install only when a tenant wants them.

---

## Transports

MCP Ingest supports three server transports when building manifests:

* **SSE** (default): URL is normalized to `/sse` if needed.
* **STDIO**: provide an `exec` block with `cmd` (e.g. Node servers via `npx`).
* **WS**: WebSocket endpoints are preserved as provided.

Example STDIO snippet:

```json
{
  "mcp_registration": {
    "server": {
      "name": "filesystem",
      "transport": "STDIO",
      "exec": { "cmd": ["npx","-y","@modelcontextprotocol/server-filesystem"] }
    }
  }
}
```

---

## Project layout

```
mcp_ingest/
  __init__.py              # exports: describe(), autoinstall()
  sdk.py                   # orchestrates describe/register
  cli.py                   # detect/describe/register/pack/harvest-repo
  emit/                    # manifest/index + optional MatrixHub adapters
  register/                # MatrixHub /catalog/install + gateway fallback
  utils/                   # sse/io/idempotency/jsonschema/ast_parse/fetch/git/temp
  detect/                  # fastmcp, langchain, llamaindex, autogen, crewai, semantic_kernel, raw
  validate/                # mcp_probe + sandbox (proc/container)
services/harvester/
  app.py + routers + workers + discovery + store + clients
examples/watsonx/
  server.py, manifest.json, index.json
```

MkDocs documentation lives under `docs/` (Material theme). CI builds lint/type/tests and wheels.

---

## Development

Use the Makefile helpers:

```bash
make help
make setup      # create .venv (Python 3.11)
make install    # install package + dev extras
make format     # black
make lint       # ruff
make typecheck  # mypy
make test       # pytest
make ci         # full gate (ruff+black+mypy+pytest)
make build      # sdist/wheel → dist/
```

Local harvester API:

```bash
uvicorn services.harvester.app:app --reload
# POST /jobs {"mode":"harvest_repo","source":"<git|zip|dir>","options":{}}
```

---

## CI & Quality

* **Ruff** (lint), **Black** (format), **Mypy** (types), **Pytest** (coverage)
* GitHub Actions workflow in `.github/workflows/ci.yml`
* Package is built and uploaded as CI artifact; PyPI publishing via Twine is supported.

---

## Security & Safety

* Idempotent HTTP and retries with exponential backoff (409 → success).
* Sandboxes (process & container) with timeouts and memory caps.
* No secrets stored at rest; inject via environment only.
* Logs are structured; per-job trace IDs in the harvester path.

---

## Roadmap

* More detectors (framework coverage), stronger schema inference.
* Richer validation (multiple tool calls, golden tests), SBOM/provenance by default.
* Global public index shards (CDN) fed by the harvester.

---

## License

`mcp-ingest` is licensed under the Apache License 2.0. See the `LICENSE` file for more details.


---

### Acknowledgements

This project is part of the **Agent‑Matrix** ecosystem and is inspired by the Model Context Protocol community work.

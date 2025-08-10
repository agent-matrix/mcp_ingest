# Harvest the Model Context Protocol Servers Repo and Register into MatrixHub

This tutorial shows how to **fetch, describe, and (optionally) register *all* servers** from the public monorepo:

> [https://github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)

We’ll use the `mcp-ingest` SDK/CLI you just installed. The same flow works for **ZIP URLs**, **git URLs**, and **local folders**.

---

## Prerequisites

* **Python 3.11** (required)
* **Virtualenv** (recommended)
* **MatrixHub** running locally (default): `http://127.0.0.1:7300`
* Optional for container validation: **Docker** (if you plan to use `--build docker` and container validation later)

> If you don’t have MatrixHub running yet, you can still build manifests and indexes offline and register them later.

---

## 1) Install `mcp-ingest`

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,harvester]"
```

Check your tools:

```bash
make tools
```

---

## 2) Quick Start — Harvest the MCP Servers Monorepo (ZIP URL)

Harvesting means: **download → scan → detect → emit manifest(s) → write a repo-level index.json → (optional) register**.

```bash
# Create an output folder for artifacts
mkdir -p dist/servers

First extract 
mcp-ingest extract  https://github.com/modelcontextprotocol/servers 
Found N possible servers
server1 https://github.com/viragtripathi/cockroachdb-mcp-server

server2
..
serevern  https://github.com/yuna0x0/hackmd-mcp


and then ask if we want to proceed with all found servers 


and begins the loop 


# Harvest directly from the ZIP of the default branch
mcp-ingest harvest-repo \
  server 1 \
  --out dist/servers
```

**What you get** in `dist/servers/`:

* One **`manifest.json`** per detected server (nested per-folder as needed)
* A **repo-level `index.json`** listing all manifests
* Harvest **logs** in your terminal (errors per subfolder are collected and reported without stopping the entire run)

You can also use the included Make target:

```bash
make harvest-mcp-servers
```

---

## 3) (Optional) Register into MatrixHub Now

Registration is **idempotent** (HTTP 409 is treated as success). You can register all harvested manifests like this:

```bash
# Example: register a single manifest
mcp-ingest register \
  --matrixhub http://127.0.0.1:7300 \
  --manifest dist/servers/<some-server>/manifest.json
```

To register **as part of harvest**, add `--register --matrixhub URL`:

```bash
mcp-ingest harvest-repo \
  https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip \
  --out dist/servers \
  --register \
  --matrixhub http://127.0.0.1:7300
```

> Tip: For multi-tenant environments, keep registration **deferred** and let each tenant install from the published catalog instead.

---

## 4) Alternative Source Types

**Git URL (clones shallow by default):**

```bash
mcp-ingest harvest-repo \
  https://github.com/modelcontextprotocol/servers.git \
  --out dist/servers
```

**Local folder:**

```bash
mcp-ingest harvest-repo ./path/to/servers --out dist/servers
```

`mcp-ingest` auto-detects the source type (dir | git | zip) and prepares a safe local working copy.

---

## 5) Inspect the Output

Peek at the repo-level index:

```bash
jq . dist/servers/index.json | head -n 40
```

List manifests discovered:

```bash
jq -r '.manifests[]' dist/servers/index.json | sed -e 's#^# • #' | sort | uniq | head -n 50
```

Open a specific manifest:

```bash
jq . dist/servers/<some-server>/manifest.json
```

> SSE transports are normalized to `/sse`. STDIO servers include an `exec` block.

---

## 6) (Optional) Publish Your Catalog (S3 or GitHub Pages)

You can publish the generated `manifest.json` + `index.json` to a static host and serve them via CDN:

```bash
python - <<'PY'
from pathlib import Path
from mcp_ingest.publishers.static_index import publish

paths = {
  "index": Path("dist/servers/index.json"),
}
res = publish(paths, dest="s3://my-bucket/mcp-catalog/servers/", provider="s3")
print(res.to_dict())
PY
```

> Later, MatrixHub operators can ingest directly from your published `index.json`.

---

## 7) Running the Harvester Service (API)

Start the API locally:

```bash
make run-harvester
# Serves at http://127.0.0.1:8088
```

Submit a **harvest job** via REST:

```bash
curl -s http://127.0.0.1:8088/harvest/repo \
  -H 'Content-Type: application/json' \
  -d '{
        "source": "https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip",
        "options": {"register": false}
      }'
```

Check status:

```bash
curl -s http://127.0.0.1:8088/jobs/<job_id>
```

Artifacts (manifests, index, logs) are stored via the harvester’s `store/repo.py` adapter (local or S3-compatible, depending on your configuration).

---

## 8) Troubleshooting

**Git not installed / private repos**

* For public GitHub repos, we fall back to GitHub zip archives when `git` is missing.
* Private repos require git credentials or a pre-downloaded zip.

**Large ZIPs or slow networks**

* The fetcher uses timeouts and size guards. You can retry; harvest is idempotent.

**MatrixHub returns 409**

* That’s OK for registration; it means the entity already exists. We treat 409 as success.

**SSE vs /messages**

* We force `/sse` by default. If a server explicitly uses `/messages`, the detector preserves it.

**STDIO servers**

* Manifests include an `exec` block for Node-based servers. Actual runtime will be launched by your orchestrator or MatrixHub integration.

---

## 9) How It Works (Short Version)

1. **Fetch/Prepare** — ZIP download (safe extraction), shallow `git clone`, or local path.
2. **Detect** — Try **FastMCP**, **LangChain**, **LlamaIndex**, **AutoGen**, **CrewAI**; fallback to generic MCP.
3. **Describe** — Emit `manifest.json` per server; normalize SSE; include STDIO exec if needed.
4. **Index** — Merge manifests into repo-level `index.json`.
5. **(Optional) Publish** — S3 / GitHub Pages.
6. **(Optional) Register** — POST manifest inline to MatrixHub `/catalog/install`.

---

## 10) Next Steps

* Point the harvester at your own org or monorepo of MCP servers.
* Enable `--register` when you’re ready to populate MatrixHub automatically.
* Add CI to periodically re-harvest the upstream repo and keep your catalog fresh.

> You now have an end‑to‑end path to **discover → describe → (optionally) register** all MCP servers from a large upstream repository—safely, reproducibly, and compatible with MatrixHub.

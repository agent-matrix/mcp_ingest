# Harvest MCP Servers in a Repo **and** All Servers Linked in its README

This tutorial shows how to extract links from a repo’s README, harvest/describe every server found (both in the repo and linked externally), and optionally register the results to MatrixHub.

> Example target: https://github.com/modelcontextprotocol/servers

---

## Prerequisites

- **Python 3.11**
- **Virtualenv** (recommended)
- *(Optional)* **MatrixHub** at `http://127.0.0.1:7300`
- *(Optional)* **Docker** (only if you plan to validate in containers)
- *(Recommended)* `GITHUB_TOKEN` to avoid GitHub rate limits

---

## 1) Install `mcp-ingest`

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,harvester]"
make tools
```

---

## 2) One command: Extract README → Harvest/Describe → (Optional) Register

```bash
mcp-ingest harvest-source \
  https://github.com/modelcontextprotocol/servers \
  --out dist/servers \
  --yes \
  --max-parallel 4 \
  --register \
  --matrixhub http://127.0.0.1:7300
```

### What this does

1. **Reads the README** on the default branch (with fallbacks).
2. **Identifies GitHub candidates**, including `/tree/<ref>/<subdir>` links.
3. **Plans** each candidate (repo vs. subdir-of-ref).
4. **Detects & describes** with existing detectors (FastMCP, LangChain, LlamaIndex, AutoGen, CrewAI, Semantic Kernel; fallback to raw).
5. **Emits** one `manifest.json` per server and **merges** all into a single `index.json`.
6. **(Optional)** Registers each manifest to MatrixHub (`/catalog/install`, 409 is OK).

**Useful flags**

* `--yes` / `-y` Skip the confirmation prompt.
* `--max-parallel N` Process multiple candidates concurrently.
* `--register --matrixhub URL` Register results to MatrixHub.
* `--only-github` Ignore non-GitHub links in the README.
* `--log-file FILE` Write structured logs to disk.

---

## 3) Inspect results

All artifacts are written to `dist/servers/`:

* Per-server **`manifest.json`**
* A single **`index.json`** listing them all

Quick checks:

```bash
jq . dist/servers/index.json | head -n 40
jq -r '.manifests[]' dist/servers/index.json | sort | uniq | sed 's/^/ • /'
```

Open a manifest:

```bash
jq . dist/servers/<some-server>/manifest.json
```

---

## 4) Register later (optional)

```bash
mcp-ingest register \
  --matrixhub http://127.0.0.1:7300 \
  --manifest dist/servers/<some-server>/manifest.json
```

> Registration is **idempotent**; HTTP 409 counts as success.

---

## Tips & Troubleshooting

* **Performance:** `--max-parallel` speeds things up when harvesting many candidates.
* **Rate limits:** set `GITHUB_TOKEN` to avoid anonymous throttling.
* **Safety:** the fetcher uses size/time limits and safe extraction (ZipSlip guards).
* **Transports:** SSE is normalized unless `/messages` is explicitly used.
* **STDIO:** Manifests include an `exec` block where applicable (Node MCP servers).
* **Compare:** `harvest-repo` handles a single source; `harvest-source` expands to README-linked repos too.

---

## Why this matters

Curated READMEs often link to dozens of independent MCP servers. `harvest-source` turns a single entrypoint into a wide crawl, scaling your MatrixHub catalog with one command.
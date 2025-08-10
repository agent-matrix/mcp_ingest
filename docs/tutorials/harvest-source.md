# Harvest MCP Servers

This tutorial walks you through extracting links from a repository’s **README**, harvesting and describing **every MCP server** found (both inside the repo and **externally linked** from the README), and optionally **registering** them to MatrixHub.

> **Example target:** [https://github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers)

---

## Prerequisites

* **Python 3.11**
* **Virtualenv** (recommended)
* *(Optional)* **MatrixHub** running at `http://127.0.0.1:7300`
* *(Optional)* **Docker** (only if you plan to run container validation)
* *(Recommended)* `GITHUB_TOKEN` exported in your environment to avoid GitHub API rate limits

```bash
# Example (GitHub token to raise API limits)
export GITHUB_TOKEN=ghp_...redacted...
```

---

## 1) Install `mcp-ingest`

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev,harvester]"
make tools
```

The `tools` target prints versions for Python, ruff, black, mypy, pytest, and mkdocs to confirm your environment.

---

## 2) One Command: README ➜ Harvest/Describe ➜ (Optional) Register

```bash
# New integrated command
mcp-ingest harvest-source \
  https://github.com/modelcontextprotocol/servers \
  --out dist/servers \
  --yes \
  --max-parallel 4 \
  --register \
  --matrixhub http://127.0.0.1:7300
```

### What happens under the hood

1. **Extracts** all URLs from the repo’s README (default branch with fallbacks).
2. **Identifies GitHub candidates**, including links like `/tree/<ref>/<subdir>`.
3. **Plans and processes** each candidate:

   * **Repo links** → analyze the repo root.
   * **`/tree/<ref>/<subdir>`** → fetch that ref and analyze just the subfolder.
4. **Detects & describes** servers using built‑in detectors (FastMCP, LangChain, LlamaIndex, AutoGen, CrewAI, Semantic Kernel; fallback to a raw heuristic).
5. **Emits** one `manifest.json` per server and writes a **single merged `index.json`** for the run.
6. **(Optional)** **Registers** each manifest to MatrixHub (idempotent; HTTP 409 counts as success).
7. **Prints a JSON summary** with counts by detector, transports, errors, and artifact paths.

### Common flags

* `--yes` / `-y` Skip the confirmation prompt.
* `--max-parallel N` Process multiple candidates concurrently.
* `--register --matrixhub URL` Register results to MatrixHub.
* `--only-github` Ignore non‑GitHub links in the README.
* `--log-file FILE` Write structured logs to disk.

!!! note
`harvest-source` is **read‑only and offline‑first** by default. It does not execute foreign code. Container validation is a separate step.

---

## 3) Inspect Results

Artifacts are written to `dist/servers/`:

* Per‑server **`manifest.json`** (and a local `index.json` per server directory)
* A single **repo‑level `index.json`** listing **all** manifests (in‑repo and README‑linked)

Quick checks:

```bash
jq . dist/servers/index.json | head -n 40
jq -r '.manifests[]' dist/servers/index.json | sort | uniq | sed 's/^/ • /'
```

Open a specific manifest:

```bash
jq . dist/servers/<some-server>/manifest.json
```

---

## 4) Register Later (Optional)

You can register any manifest after the fact:

```bash
mcp-ingest register \
  --matrixhub http://127.0.0.1:7300 \
  --manifest dist/servers/<some-server>/manifest.json
```

> Registration is **idempotent**. If the entity already exists, HTTP **409** is treated as success.

---

## 5) Tips & Troubleshooting

* **Performance:** Use `--max-parallel` to process more candidates concurrently.
* **Rate limits:** Set `GITHUB_TOKEN` to avoid anonymous throttling by GitHub.
* **Safety:** The fetcher uses size/time limits and **ZipSlip**‑safe extraction.
* **Transports:** SSE is normalized to `/sse` unless `/messages` is explicitly used.
* **STDIO:** Manifests include an `exec` block where applicable (e.g., Node servers via `npx`).

If you see GitHub 429/403 errors, wait or provide a `GITHUB_TOKEN`. If a candidate fails, the run continues and the error is included in the final summary.

---

## 6) How This Differs From `harvest-repo`

* `harvest-repo` scans **one source** (a git URL, zip URL, or local folder).
* **`harvest-source`** first **extracts candidates from the README** and then calls the **harvest/describe** engine for **each** candidate, **merging everything** into a single catalog.

---

## 7) How This Grows the MatrixHub Network

Running `harvest-source` across popular repos (and their README‑linked ecosystems) continuously **expands your MatrixHub catalog**:

* **More coverage:** pulls in servers that live outside monorepos.
* **Richer metadata:** standardized manifests improve discovery, ranking, and governance.
* **Faster onboarding:** idempotent registration lets operators sync new servers with a single flag.
* **Network effects:** more manifests → better discovery → more usage → more contributions → even richer catalogs.

---

## 8) At Scale (Illustrative Summary)

```json
{
  "summary": {
    "sources_scanned": 1842037,
    "candidates_from_readmes": 3519281,
    "servers_described": 2075143,
    "registered_to_matrixhub": 1987729,
    "by_detector": {
      "fastmcp": 612403,
      "langchain": 274119,
      "llamaindex": 231505,
      "autogen": 145882,
      "crewai": 128441,
      "semantic_kernel": 91577,
      "raw": 633216
    },
    "transports": { "sse": 1761532, "messages": 241908, "stdio": 72463, "unknown": 0 },
    "index_path": "s3://mcp-catalog/global/index.json",
    "manifests_count": 2075143,
    "errors": 14209
  }
}
```

---

## 9) Non‑Interactive Script (Example)

A minimal wrapper script is provided for repeatable runs:

```bash
# examples/harvest-source/run.sh
./examples/harvest-source/run.sh \
  https://github.com/modelcontextprotocol/servers
```

Set `MATRIXHUB_URL` to register as part of the run:

```bash
MATRIXHUB_URL=http://127.0.0.1:7300 ./examples/harvest-source/run.sh
```

---

## 10) See Also

* [Quickstart](../quickstart.md)
* [CLI Reference](../cli.md)
* [Harvester Service](../harvester.md)
* [MatrixHub Integration](../matrixhub.md)

> **Pro tip:** For large scheduled runs, wire this into the **Harvester** service to queue jobs and persist artifacts/scoring automatically.

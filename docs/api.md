# API Reference

## CLI Commands

```text
mcp-ingest detect          <source>
mcp-ingest describe        <name> <url> [--tools ...] [--resource ...] [--out dir]
mcp-ingest register        --matrixhub URL [--manifest path] [--entity-uid ...] [--target ./]
mcp-ingest pack            <source> [--out dir] [--register] [--matrixhub URL]
mcp-ingest harvest-repo    <source> --out DIR [--publish DEST] [--register] [--matrixhub URL]
mcp-ingest harvest-source  <github-repo-url> --out DIR [--yes] [--max-parallel N]
                           [--only-github] [--register] [--matrixhub URL] [-v|--verbose] [--log-file PATH]
```

---

## Python SDK

### `describe(...)`

Builds `manifest.json` and `index.json` without running the server. SSE URLs are normalized to `/sse` unless the transport indicates otherwise.

```python
from mcp_ingest import describe
paths = describe(name="my-mcp", url="http://127.0.0.1:6288/sse")
```

### `autoinstall(...)`

Registers a manifest by POSTing inline JSON to MatrixHub `/catalog/install`.

```python
from mcp_ingest import autoinstall
res = autoinstall(matrixhub_url="http://127.0.0.1:7300")
```

---

## Harvest Orchestrators

### `mcp_ingest.harvest.repo.harvest_repo(source, *, out_dir, publish=None, register=False, matrixhub_url=None) -> HarvestResult`

Harvests a single repository (local dir | git URL | zip URL), finds subservers, emits per-server manifests, and writes a repo-level `index.json`.

**Return:** `HarvestResult { manifests: list[Path], index_path: Path, errors: list[str], summary: dict }`

### `mcp_ingest.harvest.source.harvest_source(repo_url, out_dir, *, yes=False, max_parallel=4, only_github=True, register=False, matrixhub=None, log_file=None) -> dict`

Reads a GitHub repo’s README, extracts all GitHub candidates (including `/tree/<ref>/<subdir>`), harvests each, merges into one `index.json`, and optionally registers all manifests.

**Return (dict):** `{"index_path": str, "manifests": [...], "manifests_count": int, "errors": [...], "by_detector": {...}, "transports": {...}}`

---

## Extractor Utilities

### `mcp_ingest.utils.extractor.fetch_readme_markdown(repo_url: str) -> str | None`

Fetch the README (default branch with fallbacks) for a GitHub repo URL.

### `mcp_ingest.utils.extractor.extract_urls_from_markdown(md: str) -> list[str]`

Extract and dedupe all HTTP/HTTPS URLs from a README’s markdown.

### `mcp_ingest.utils.extractor.extract_github_repo_links_from_readme(repo_url: str) -> list[RepoTarget]`

Return GitHub repo candidates (including `/tree/<ref>/<subdir>`) as `RepoTarget` items.

```python
@dataclass(frozen=True)
class RepoTarget:
    owner: str
    repo: str
    ref: str | None = None
    subpath: str | None = None

    @property
    def pretty(self) -> str: ...
```

## Testing extraction
```bash
 python -m mcp_ingest.utils.extractor https://github.com/modelcontextprotocol/servers
```

```bash
.
.
https://github.com/zueai/mcp-manager
https://github.com/zzaebok/mcp-wikidata

Would you like to proceed to analyze each of them? [y/N]: y
Great! Analysis will run in the next phase (not implemented in this test mode).

```
Good happy coding..
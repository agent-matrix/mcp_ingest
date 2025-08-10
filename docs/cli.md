# CLI

## Commands

```text
mcp-ingest detect   <source>   # offline detectors (FastMCP, heuristics)
mcp-ingest describe <name> <url> [--tools ...] [--resource ...] [--out dir]
mcp-ingest register --matrixhub URL [--manifest path] [--entity-uid ...] [--target ./]
mcp-ingest pack     <source> [--out dir] [--register] [--matrixhub URL]
mcp-ingest harvest-repo <source> --out DIR [--publish DEST] [--register] [--matrixhub URL]
```

### Examples

```bash
# Fast local test
mcp-ingest detect ./examples/watsonx

# Describe + write artifacts
mcp-ingest describe watsonx-mcp http://127.0.0.1:6288/sse \
  --tools chat \
  --resource uri=file://server.py,name=source \
  --out dist/

# Harvest a zip repo (multi-server)
mcp-ingest harvest-repo \
  https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip \
  --out dist/mcps
```
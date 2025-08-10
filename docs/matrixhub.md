# MatrixHub Integration

MCP Ingest integrates primarily via **`POST /catalog/install`** with an inline manifest. This is idempotent: HTTP 409 is treated as success.

## SSE normalization

- If transport is `SSE`, manifests enforce the endpoint ends with `/sse`.
- If a server uses `/messages`, keep it explicitly.

## STDIO & WS

- `STDIO` servers must provide an `exec.cmd` array (e.g., Node MCP servers via `npx`).
- `WS` URLs are preserved.

## Registration flow

1. Detect → Describe → (optional) Validate/Publish.
2. **Register** when a tenant wants the tool (runtime costs happen on demand).



 Ensure Matrix Hub is running and reachable at HUB_URL in your .env (or pass as arg)
If protected, set API_TOKEN in .env.

# 1) Harvest
mcp-ingest harvest-repo https://github.com/zazencodes/random-number-mcp --out dist/servers-first

# 2) Register
chmod +x tests/test_register.sh
tests/test_register.sh dist/servers-first/index.json  
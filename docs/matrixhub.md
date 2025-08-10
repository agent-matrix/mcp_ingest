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
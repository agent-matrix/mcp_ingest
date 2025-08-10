# SDK

## `describe(...)`

Builds `manifest.json` and `index.json` without running the server. SSE URLs are normalized to `/sse` unless the transport indicates otherwise.

```python
from mcp_ingest import describe
paths = describe(name="my-mcp", url="http://127.0.0.1:6288/sse")
```

## `autoinstall(...)`

Registers a manifest by POSTing inline JSON to MatrixHub `/catalog/install`.

```python
from mcp_ingest import autoinstall
res = autoinstall(matrixhub_url="http://127.0.0.1:7300")
```

### Manifest transports

* `SSE` → URL auto-normalized to `/sse`.
* `STDIO` → requires `exec: { cmd: [...] }` block.
* `WS` → keep URL as provided.

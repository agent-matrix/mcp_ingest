# Quickstart

## Install
```bash
pip install mcp-ingest
```

## SDK (author) in 60 seconds

```python
from mcp_ingest import describe, autoinstall

describe(
  name="my-mcp", url="[http://127.0.0.1:6288/sse](http://127.0.0.1:6288/sse)",
  tools=["hello"], resources=[{"uri":"file://server.py","name":"source"}],
)
# later: autoinstall(matrixhub_url="[http://127.0.0.1:7300](http://127.0.0.1:7300)")
```

## CLI (operator)

```bash
# detect+describe (offline)
mcp-ingest pack [https://github.com/org/repo.git](https://github.com/org/repo.git) --out dist/

# register when ready
mcp-ingest register --matrixhub [http://127.0.0.1:7300](http://127.0.0.1:7300) --manifest dist/manifest.json
```

## MatrixHub

Preferred path: POST /catalog/install with inline manifest (idempotent). SSE normalized to `/sse`.

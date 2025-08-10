# Harvester Service

The harvester discovers sources, queues jobs, runs ingest in sandboxes, scores results, and (optionally) registers high‑quality servers into MatrixHub.

## API

- `POST /jobs` `{mode, source, options}` → `{id}`
- `GET /jobs/{id}` → status + artifacts
- `POST /harvest/repo` `{source, options}` → shortcut for `mode=harvest_repo`

## Job payload

```json
{
  "mode": "harvest_repo",
  "source": "https://github.com/modelcontextprotocol/servers/archive/refs/heads/main.zip",
  "options": { "timeout": 1200 }
}
```

## Running locally

```bash
uvicorn services.harvester.app:app --reload
```

See also: `services/harvester/workers/runner.py` and `store/*` modules.

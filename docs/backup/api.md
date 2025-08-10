# API Reference

## CLI
- `mcp-ingest detect <source>` → `DetectReport`
- `mcp-ingest describe <name> <url> [--tools ...] [--resource ...] [--out dir]`
- `mcp-ingest register --matrixhub URL [--manifest path] [--entity-uid ...] [--target ./]`
- `mcp-ingest pack <source> [--out dir] [--register] [--matrixhub URL]`

## SDK
- `describe(name, url, tools=None, resources=None, description="", version="0.1.0", out_dir=".") -> {paths}`
- `autoinstall(matrixhub_url, manifest=None, manifest_path=None, entity_uid=None, target="./", token=None)`

## Harvester (service)
- `POST /jobs` `{source, options}` → `{id}`
- `GET  /jobs/{id}` → status, artifacts
- `GET  /catalogs` → list entries (filters)

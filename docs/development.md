# Development

## Prereqs
- Python 3.11
- Docker (for container validation)
- Make (optional)

## Setup
```bash
make setup
make install
```

## Useful targets

```bash
make format   # black
make lint     # ruff
make typecheck# mypy
make test     # pytest
make ci       # all gates
```

## Tests

* Unit tests for emit/detect/utils.
* E2E tests for CLI `pack` and `harvest-repo` (with small fixtures).

## Versioning

* SemVer; stamp artifacts with tool versions and git SHA.

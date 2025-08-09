# MCP Ingest: Discover, Describe, and Register AI Agents

**`mcp-ingest`** is a powerful SDK and command-line tool designed to streamline the integration of AI agents, servers, and tools with **MatrixHub**. It provides a comprehensive toolkit for discovering, describing, validating, and registering components at scale, making it an essential utility for developers and operators in the AI ecosystem.

- **SDK for Authors**: Effortlessly generate `manifest.json` and `index.json` files for your projects.
- **CLI for Operators**: A versatile command-line interface to pack, validate, and register your AI components.
- **Harvester Service**: A scalable service for internet-wide discovery and automated cataloging of AI agents.

Built for **Python 3.11+**, `mcp-ingest` is packaged for PyPI and maintained with high-quality standards, including linting, type-checking, and comprehensive testing.

---

## Key Features

- **Automated Discovery**: Find MCP-compatible servers and agents across the internet.
- **Standardized Descriptions**: Create consistent and compliant `manifest.json` files.
- **Robust Validation**: Ensure your components are reliable and ready for production.
- **Seamless Registration**: Easily integrate your tools with MatrixHub.
- **Scalable Architecture**: Designed for planet-scale operations with a modular and extensible framework.

---

## Installation

You can install `mcp-ingest` directly from PyPI:

```bash
pip install mcp-ingest
```

For developers contributing to the project, an editable installation is recommended:

```bash
# Set up a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install in editable mode with development dependencies
pip install -e ".[dev,harvester]"
```

---

## Getting Started

### For SDK Users

As an author, you can use the `describe` function to generate the necessary metadata for your project:

```python
from mcp_ingest import describe, autoinstall

# Generate manifest.json and index.json
describe(
    name="my-agent",
    url="[http://127.0.0.1:8080/sse](http://127.0.0.1:8080/sse)",
    tools=["chat", "file-reader"],
    resources=[{"uri": "file://agent.py", "name": "source_code"}],
    description="A simple yet powerful AI agent.",
    version="1.0.0",
)

# Optionally, register with your local MatrixHub instance
autoinstall(matrixhub_url="[http://127.0.0.1:7300](http://127.0.0.1:7300)")
```

### For CLI Users

Operators can use the `mcp-ingest` command to manage their AI components:

```bash
# Detect, describe, and package a project
mcp-ingest pack ./my-agent --out ./dist

# Register the packaged project with MatrixHub
mcp-ingest register \
  --matrixhub [http://127.0.0.1:7300](http://127.0.0.1:7300) \
  --manifest ./dist/manifest.json
```

---

## Development and Contribution

We welcome contributions from the community! To get started, please refer to the development guidelines in the `Makefile`.

```bash
# Display available development commands
make help

# Run the full CI pipeline (lint, type-check, test)
make ci
```

---

## License

`mcp-ingest` is licensed under the Apache License 2.0. See the `LICENSE` file for more details.

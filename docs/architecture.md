
# Architecture

Core modules:

- **detect/** — AST/regex detectors for FastMCP, LangChain, LlamaIndex, AutoGen, CrewAI, Semantic Kernel.
- **emit/** — manifest & index emitters; MatrixHub adapters (optional).
- **register/** — MatrixHub `/catalog/install` (preferred) and gateway fallback.
- **validate/** — local & container sandboxes; MCP probe.
- **publishers/** — S3/GH Pages static publishing + global index shards.
- **services/harvester/** — internet‑scale discovery, workers, and persistence.

## Dataflow

```mermaid
sequenceDiagram
  participant U as User/Harvester
  participant D as Detect
  participant E as Emit
  participant V as Validate
  participant P as Publish
  participant H as MatrixHub

  U->>D: source (dir|git|zip)
  D-->>U: DetectReport
  U->>E: build manifest/index
  U->>V: (optional) validate in container
  U->>P: (optional) publish to CDN
  U->>H: (optional) /catalog/install
```
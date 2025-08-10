# FAQ

**Do I have to run servers to generate manifests?**  
No. `describe(...)` and `harvest-repo` generate manifests offline.

**Can I validate tools automatically?**  
Yes. Use container validation to handshake, list tools, and call one tool.

**What about Node MCP servers?**  
Use `transport=STDIO` with an `exec.cmd` like `npx -y @modelcontextprotocol/server-filesystem`.
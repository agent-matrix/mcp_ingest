from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Watsonx Chat Agent", port=6288)


@mcp.tool(description="Echo tool")
def chat(query: str) -> str:
    return f"echo: {query}"


if __name__ == "__main__":
    mcp.run(transport="sse")

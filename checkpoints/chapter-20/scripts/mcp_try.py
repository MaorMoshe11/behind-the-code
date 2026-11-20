"""Connect to the notes MCP server the way a host application does, without one.

    uv run python scripts/mcp_try.py                          # list the tools
    uv run python scripts/mcp_try.py list_notes search=milk    # call one: name key=value ...
    uv run python scripts/mcp_try.py --conversation ID list_notes    # another conversation
    uv run python scripts/mcp_try.py read notes://conversation      # read a resource

It starts `python -m agent.mcp_server` as a child process and speaks MCP with it over its
stdin and stdout, using the client half of the official `mcp` SDK.
"""

import sys
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters
from mcp.types import TextContent, TextResourceContents

PROJECT = Path(__file__).resolve().parent.parent


async def main(argv: list[str]) -> None:
    server_args = ["-m", "agent.mcp_server"]
    if argv[:1] == ["--conversation"]:  # passed on to the server
        server_args, argv = server_args + argv[:2], argv[2:]
    server = StdioServerParameters(
        command=sys.executable,  # the Python of this project's .venv
        args=server_args,
        cwd=PROJECT,  # the server reads .env from here, like the chat does
    )
    async with Client(server) as client:
        info = client.server_info
        print(f"connected to {info.name} {info.version}" if info else "connected")
        listing = await client.list_tools()
        for tool in listing.tools:
            hints = tool.annotations
            kind = "read-only" if hints and hints.read_only_hint else "writes"
            print(f"  {tool.name} ({kind}): {sorted(tool.input_schema.get('properties', {}))}")
        resources = await client.list_resources()
        for resource in resources.resources:
            print(f"  resource {resource.uri}: {resource.description}")
        if not argv:
            return
        if argv[0] == "read":  # read <uri>
            read = await client.read_resource(argv[1])
            for part in read.contents:
                if isinstance(part, TextResourceContents):
                    print(f"{argv[1]} ->\n{part.text}")
            return
        name, pairs = argv[0], argv[1:]
        arguments = dict(pair.split("=", 1) for pair in pairs)  # key=value, all strings
        result = await client.call_tool(name, arguments)
        text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
        print(f"{name} -> {'ERROR ' if result.is_error else ''}{text}")


if __name__ == "__main__":
    anyio.run(main, sys.argv[1:])

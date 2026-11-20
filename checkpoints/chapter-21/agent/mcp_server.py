"""The notes tools as an MCP server: any MCP host can use them, not only our chat.

    uv run python -m agent.mcp_server [--conversation ID]

It speaks MCP over stdio: the host starts this process and talks to it through its stdin
and stdout. So nothing else may be printed to stdout: the log goes to mcp.log.

The tools are the same registry the agent loop uses (agent/notes_tools.py), with the same
validation, errors and limits. The notes are those of one conversation, chosen when the
server starts (default: the newest), and the writing tools only with CHAT_WRITE_TOOLS=1.
"""

import argparse
import logging
import sys

import anyio
import mcp.types as types
from dotenv import load_dotenv
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from mcp_types.jsonrpc import INVALID_PARAMS
from sqlalchemy.orm import sessionmaker

from agent import logs, project_version
from agent.approvals import Request
from agent.config import load_settings
from agent.conversations import latest_conversation
from agent.db import make_engine
from agent.notes import make_notes
from agent.notes_tools import TOOLS
from agent.tools import Toolbox, ToolContext

log = logging.getLogger(__name__)
NOTES_URI = "notes://conversation"  # a resource: the notes, for the host to read (exercise 5)


def build_server(toolbox: Toolbox) -> Server:
    """An MCP server whose tools are the toolbox's: listed, and run, through the registry."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.schema(),
                    # Hints for the host (for example, to ask the user before a write).
                    annotations=types.ToolAnnotations(
                        read_only_hint=not tool.writes, destructive_hint=tool.name == "delete_note"
                    ),
                )
                for tool in toolbox.tools.values()
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        # Toolbox.call is ordinary blocking code (HTTP to the notes service): run it in a
        # thread, so the server keeps answering while it waits.
        outcome = await anyio.to_thread.run_sync(toolbox.call, params.name, params.arguments or {})
        return types.CallToolResult(
            content=[types.TextContent(text=outcome.content)], is_error=outcome.is_error
        )

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        notes = types.Resource(
            uri=NOTES_URI,
            name="notes",
            description="Every note of this conversation, one per line (at most 20, oldest first).",
            mime_type="text/plain",
        )
        return types.ListResourcesResult(resources=[notes])

    async def read_resource(
        ctx: ServerRequestContext, params: types.ReadResourceRequestParams
    ) -> types.ReadResourceResult:
        if params.uri != NOTES_URI:
            raise MCPError(INVALID_PARAMS, f"No resource {params.uri!r}. There is {NOTES_URI}.")
        # The same code as the tool: one way to read notes, with its limits and its errors.
        outcome = await anyio.to_thread.run_sync(toolbox.call, "list_notes", {})
        text = types.TextResourceContents(
            uri=NOTES_URI, mime_type="text/plain", text=outcome.content
        )
        return types.ReadResourceResult(contents=[text])

    return Server(
        "my-agent-notes",
        version=project_version(),
        instructions="The user's notes from my-agent: list, search, add and delete them.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
        on_list_resources=list_resources,
        on_read_resource=read_resource,
    )


async def serve(server: Server) -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the notes tools over MCP (stdio).")
    parser.add_argument("--conversation", help="whose notes (default: the newest conversation)")
    args = parser.parse_args()
    load_dotenv()
    settings = load_settings()
    # stdout belongs to the protocol. The log goes to a file, problems to stderr.
    logs.setup_logging(settings.log_level, "notes-mcp", filename="mcp.log")
    notes = make_notes(settings)
    if notes is None:
        print("NOTES_URL is not set: there are no notes to serve.", file=sys.stderr)
        sys.exit(1)
    sessions = sessionmaker(make_engine(settings.database_url))
    conversation_id = args.conversation or latest_conversation(sessions)
    if conversation_id is None:
        print("There is no conversation yet. Start one first.", file=sys.stderr)
        sys.exit(1)
    toolbox = TOOLS.toolbox(
        ToolContext(notes, conversation_id), settings.write_tools, host_approves, False
    )
    log.info(
        "serving %d tools over stdio",
        len(toolbox.tools),
        extra={"conversation_id": conversation_id, "tools": list(toolbox.tools)},
    )
    anyio.run(serve, build_server(toolbox))


def host_approves(request: Request) -> bool:
    """Over MCP the approval belongs to the host: it shows its user every call of a tool that
    is not read-only (annotations above) before sending it. This server only records it."""
    log.info("write approved by the MCP host", extra={"tool": request.tool})
    return True


if __name__ == "__main__":
    main()

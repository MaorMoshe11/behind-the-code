"""Tests for the tool registry and the notes tools, with a fake notes service."""

import json

import anyio
import httpx2
import pytest
from mcp import Client

from agent.mcp_server import build_server
from agent.notes import NotesClient
from agent.notes_tools import PAGE, TOOLS, note_key
from agent.tools import Tool, ToolContext, ToolInput, ToolRegistry


def service(notes_by_conversation):
    """A fake notes service over a dict {conversation_id: [note, ...]}, and its requests."""
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            mine = notes_by_conversation.get(request.url.params["conversation_id"], [])
            q = request.url.params.get("q", "").lower()
            found = [note for note in mine if q in note["text"].lower()]
            return httpx2.Response(200, json=found[: int(request.url.params.get("limit", 50))])
        if request.method == "POST":
            body = json.loads(request.content)
            note = {"id": request.headers["Idempotency-Key"][-32:].rjust(32, "0"), **body}
            return httpx2.Response(201, json=note)
        if request.method == "DELETE":
            return httpx2.Response(204)
        return httpx2.Response(405)

    client = NotesClient("http://notes", "k", backoff=0, transport=httpx2.MockTransport(handler))
    return client, requests


def note(n, text, conversation="c1"):
    return {"id": f"{n:08x}" + "0" * 24, "conversation_id": conversation, "text": text}


def test_writing_tools_are_offered_only_when_allowed():
    notes, _ = service({})
    context = ToolContext(notes, "c1")
    assert list(TOOLS.toolbox(context).tools) == ["list_notes", "current_time"]
    assert list(TOOLS.toolbox(context, writes=True).tools) == [
        "list_notes",
        "add_note",
        "delete_note",
        "current_time",
    ]


def test_a_tool_name_is_registered_once():
    registry = ToolRegistry()
    tool = Tool("x", "A tool.", ToolInput, lambda context, args: "ok")
    registry.register(tool)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)


def test_every_schema_is_closed_and_has_no_titles():
    for tool in TOOLS:
        schema = tool.param()["input_schema"]
        assert schema["additionalProperties"] is False
        assert '"title"' not in json.dumps(schema)  # Pydantic's titles are gone, everywhere


def test_a_long_list_is_cut_to_a_page_and_says_how_to_find_more():
    notes, requests = service({"c1": [note(n, f"note {n}") for n in range(PAGE + 5)]})
    result = TOOLS.toolbox(ToolContext(notes, "c1")).call("list_notes", {})
    lines = result.content.splitlines()
    assert len(lines) == PAGE + 1
    assert lines[-1] == "(Only the first 20 notes are shown. Use search to find others.)"
    assert requests[0].url.params["limit"] == str(PAGE + 1)


def test_a_long_note_is_cut_in_the_result():
    notes, _ = service({"c1": [note(1, "x" * 1000)]})
    result = TOOLS.toolbox(ToolContext(notes, "c1")).call("list_notes", {})
    assert result.content == "- [00000001] " + "x" * 300 + "..."


def test_a_search_that_finds_nothing_says_what_to_try():
    notes, _ = service({"c1": [note(1, "buy oat milk")]})
    result = TOOLS.toolbox(ToolContext(notes, "c1")).call("list_notes", {"search": "milk!"})
    assert result.content == "No notes contain 'milk!'. Try one shorter word, or no search."


def test_the_same_note_twice_sends_the_same_idempotency_key():
    notes, requests = service({})
    tools = TOOLS.toolbox(ToolContext(notes, "c1"), writes=True)
    tools.call("add_note", {"text": "buy  oat milk"})
    tools.call("add_note", {"text": "buy oat milk"})  # a repeated step, the same note
    keys = [r.headers["Idempotency-Key"] for r in requests]
    assert keys[0] == keys[1] == note_key("c1", "buy oat milk")
    assert note_key("c2", "buy oat milk") != keys[0]  # another conversation: another note


def test_delete_works_only_on_this_conversations_notes():
    notes, requests = service({"c1": [note(1, "mine")], "c2": [note(2, "someone else's")]})
    tools = TOOLS.toolbox(ToolContext(notes, "c1"), writes=True)

    result = tools.call("delete_note", {"note": "00000002"})  # c2's note, ref copied somehow

    assert result.is_error
    assert result.content == (
        "No note [00000002] in this conversation. Call list_notes to see the notes and their refs."
    )
    assert [r.method for r in requests] == ["GET"]  # it looked; it never sent a DELETE

    result = tools.call("delete_note", {"note": "00000001"})
    assert result.content == "Deleted: [00000001] mine"
    assert requests[-1].method == "DELETE"
    assert requests[-1].url.path == "/v1/notes/00000001" + "0" * 24


def test_an_invented_id_is_refused_by_the_schema():
    notes, requests = service({})
    tools = TOOLS.toolbox(ToolContext(notes, "c1"), writes=True)
    result = tools.call("delete_note", {"note": "the milk one"})
    assert result.is_error and "String should match pattern" in result.content
    assert requests == []


def test_the_mcp_server_lists_and_runs_the_same_tools():
    notes, _ = service({"c1": [note(1, "buy oat milk")]})
    server = build_server(TOOLS.toolbox(ToolContext(notes, "c1")))

    async def session():
        async with Client(server) as client:  # in-process: no subprocess, no stdio
            listing = await client.list_tools()
            found = await client.call_tool("list_notes", {"search": "milk"})
            bad = await client.call_tool("list_notes", {"search": 42})
            read = await client.read_resource("notes://conversation")
            return listing, found, bad, read

    listing, found, bad, read = anyio.run(session)
    assert read.contents[0].text == "- [00000001] buy oat milk"
    assert [tool.name for tool in listing.tools] == ["list_notes", "current_time"]
    assert listing.tools[0].annotations.read_only_hint is True
    assert found.content[0].text == "- [00000001] buy oat milk" and not found.is_error
    assert bad.is_error

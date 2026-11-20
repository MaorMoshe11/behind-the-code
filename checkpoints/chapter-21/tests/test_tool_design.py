"""A badly designed notes tool next to ours: the same service, very different for a model.

The bad one is what you get by wrapping each endpoint as it is: the model must send the
conversation id, it gets the service's raw JSON back, and an error is a status code.
"""

import httpx2
from pydantic import Field

from agent.llm import mock_tokens
from agent.notes import NotesClient, NotesUnavailable
from agent.notes_tools import TOOLS
from agent.tools import Tool, ToolContext, ToolError, ToolInput, ToolRegistry

SAVED = {
    "c1": [
        {
            "id": f"{n:08x}" + "5e" * 12,
            "conversation_id": "c1",
            "text": text,
            "created_at": f"2026-11-19T10:0{n}:00.123456",
        }
        for n, text in enumerate(["buy oat milk", "call the dentist on Monday", "milk for Dana"])
    ],
    "c2": [{"id": "9" * 32, "conversation_id": "c2", "text": "my PIN is 4921", "created_at": "x"}],
}


def notes_service():
    def handler(request):
        if request.method == "GET":
            mine = SAVED.get(request.url.params["conversation_id"], [])
            q = request.url.params.get("q", "").lower()
            return httpx2.Response(200, json=[n for n in mine if q in n["text"].lower()])
        return httpx2.Response(404, json={"detail": "No note with this id."})

    return NotesClient("http://notes", "k", backoff=0, transport=httpx2.MockTransport(handler))


class GetNotesInput(ToolInput):
    conversation_id: str  # the model must supply it: from where?
    q: str | None = None
    limit: int = Field(50, ge=1, le=100)


class DeleteByIdInput(ToolInput):
    id: str  # 32 characters the model must copy perfectly, or invent


def get_notes(context: ToolContext, args: GetNotesInput) -> str:
    params = {"conversation_id": args.conversation_id, "limit": args.limit}
    if args.q:
        params["q"] = args.q
    return context.notes.http.get("/v1/notes", params=params).text  # the raw JSON


def delete_by_id(context: ToolContext, args: DeleteByIdInput) -> str:
    try:
        context.notes.delete(args.id)
    except NotesUnavailable as error:
        raise ToolError(str(error)) from None  # "DELETE /v1/notes/...: 404"
    return "OK"


BAD = ToolRegistry()
BAD.register(Tool("get_notes", "Gets notes.", GetNotesInput, get_notes))
BAD.register(Tool("delete_notes_id", "DELETE /v1/notes/{id}", DeleteByIdInput, delete_by_id))


def toolboxes():
    context = ToolContext(notes_service(), "c1")
    return BAD.toolbox(context), TOOLS.toolbox(context, writes=True)


def test_the_good_definition_tells_the_model_when_and_what():
    bad, good = toolboxes()
    bad_tool, good_tool = bad.params()[0], good.params()[0]
    assert len(bad_tool["description"]) < 15  # "Gets notes.": when? which? what comes back?
    assert "Call it when" in good_tool["description"]
    assert "conversation_id" in bad_tool["input_schema"]["required"]
    assert "conversation_id" not in str(good_tool["input_schema"])


def test_the_good_result_is_a_fraction_of_the_bad_one():
    bad, good = toolboxes()
    raw = bad.call("get_notes", {"conversation_id": "c1", "q": "milk"}).content
    marked = good.call("list_notes", {"search": "milk"}).content
    short = "\n".join(marked.splitlines()[1:-1])  # the result inside its <untrusted> tags
    assert short == "- [00000000] buy oat milk\n- [00000002] milk for Dana"
    # Every later step sends the result again: what it costs, in the mock's token count.
    assert (mock_tokens(raw), mock_tokens(short)) == (66, 14)


def test_the_bad_tool_reads_any_conversation_the_model_names():
    bad, good = toolboxes()
    leaked = bad.call("get_notes", {"conversation_id": "c2"}).content
    assert "my PIN is 4921" in leaked  # text in a note or a web page could ask for this
    refused = good.call("list_notes", {"conversation_id": "c2"})
    assert refused.is_error and "Extra inputs are not permitted" in refused.content


def test_the_good_error_says_how_to_recover():
    bad, good = toolboxes()
    assert bad.call("delete_notes_id", {"id": "0" * 32}).content == (
        f"DELETE /v1/notes/{'0' * 32}: 404"
    )
    assert good.call("delete_note", {"note": "00000009"}).content == (
        "No note [00000009] in this conversation. Call list_notes to see the notes and their refs."
    )

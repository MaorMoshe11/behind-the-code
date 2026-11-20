"""The notes service, as tools for the model: list (and search), add, delete.

Three tools, not one per endpoint. Each one is shaped for its client, a model: inputs it can
get right (no conversation id, no note id it would have to invent), short results that carry
what it needs next (a ref for each note), and errors that say how to recover.
"""

import hashlib

from pydantic import Field

from agent.clock import make_current_time
from agent.memory_tools import memory_tools
from agent.notes import Note, NotesUnavailable
from agent.tools import Tool, ToolContext, ToolError, ToolInput, ToolRegistry

PAGE = 20  # notes in one result, at most: every later step sends the result again
NOTE_CHARS = 300  # longer notes are cut in a result; the note itself is unchanged
UNAVAILABLE = "The notes service is unavailable right now. Tell the user; do not retry now."


def ref(note: Note) -> str:
    """A short handle for a note: the first 8 characters of its id."""
    return note.id[:8]


def line(note: Note) -> str:
    text = note.text if len(note.text) <= NOTE_CHARS else note.text[:NOTE_CHARS] + "..."
    return f"- [{ref(note)}] {text}"


def note_key(conversation_id: str, text: str) -> str:
    """The Idempotency-Key of an add_note: the same note in the same conversation, the same key.

    A repeated request (the user sends the message again after a timeout, the model asks
    twice) saves the note once. Made by our code, never by the model.
    """
    digest = hashlib.sha256(f"{conversation_id}\n{text}".encode()).hexdigest()
    return f"tool-{digest[:40]}"


class ListNotesInput(ToolInput):
    search: str = Field(
        "",
        max_length=200,
        description="Only notes that contain this text (any case), for example 'milk'. "
        "Leave it out to list every note.",
    )


def list_notes(context: ToolContext, args: ListNotesInput) -> str:
    try:  # one more than a page: so we know whether there are more
        found = context.notes_client().list(context.conversation_id, args.search or None, PAGE + 1)
    except NotesUnavailable as error:
        raise ToolError(UNAVAILABLE) from error
    if not found:
        if args.search:
            return f"No notes contain {args.search!r}. Try one shorter word, or no search."
        return "No notes found."
    lines = [line(note) for note in found[:PAGE]]
    if len(found) > PAGE:
        lines.append(f"(Only the first {PAGE} notes are shown. Use search to find others.)")
    return "\n".join(lines)


class AddNoteInput(ToolInput):
    text: str = Field(
        min_length=1,
        max_length=2000,
        description="The note, in the user's words. One note per call.",
    )


def add_note(context: ToolContext, args: AddNoteInput) -> str:
    text = " ".join(args.text.split())
    try:
        note = context.notes_client().add(
            context.conversation_id, text, idempotency_key=note_key(context.conversation_id, text)
        )
    except NotesUnavailable as error:
        raise ToolError(UNAVAILABLE + " The note was not saved.") from error
    return f"Saved: {line(note)[2:]}"


class DeleteNoteInput(ToolInput):
    note: str = Field(
        pattern=r"^[0-9a-f]{8}$",
        description="The note's ref: the 8 characters in brackets that list_notes shows, "
        "for example 3f2a9c1b.",
    )


def delete_note(context: ToolContext, args: DeleteNoteInput) -> str:
    try:
        # Only a note of THIS conversation can be deleted: look for the ref among its notes.
        mine = context.notes_client().list(context.conversation_id, limit=100)
        found = [note for note in mine if note.id.startswith(args.note)]
        if not found:
            raise ToolError(
                f"No note [{args.note}] in this conversation. "
                "Call list_notes to see the notes and their refs."
            )
        context.notes_client().delete(found[0].id)
    except NotesUnavailable as error:
        raise ToolError(UNAVAILABLE + " Nothing was deleted.") from error
    return f"Deleted: {line(found[0])[2:]}"


def build_registry() -> ToolRegistry:
    """Every tool the agent has. The agent loop, agent.trace and the MCP server all use it."""
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="list_notes",
            description=(
                "List or search the notes the user saved in this conversation. Call it when "
                "the user asks what they saved, noted or wrote down, refers to their notes, "
                "or before delete_note to find a note's ref. Returns one note per line, "
                "oldest first, as '- [ref] text', at most 20."
            ),
            input_model=ListNotesInput,
            run=list_notes,
            needs="notes",
        )
    )
    registry.register(
        Tool(
            name="add_note",
            description=(
                "Save a note in this conversation. Call it when the user asks you to remember, "
                "note or write something down. Saving the same text twice keeps one note. "
                "Returns the saved note with its ref."
            ),
            input_model=AddNoteInput,
            run=add_note,
            writes=True,
            needs="notes",
        )
    )
    registry.register(
        Tool(
            name="delete_note",
            description=(
                "Delete one note of this conversation, by its ref from list_notes. Call it only "
                "when the user clearly asks to delete or forget that note. It cannot be undone."
            ),
            input_model=DeleteNoteInput,
            run=delete_note,
            writes=True,
            needs="notes",
        )
    )
    registry.register(make_current_time())  # read-only, and needs no notes
    for tool in memory_tools():  # long-term memory and search (agent/memory_tools.py)
        registry.register(tool)
    return registry


TOOLS = build_registry()

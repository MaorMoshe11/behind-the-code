"""Tools: what the model may ask the program to do.

A tool is a name, a description and a JSON schema for its input. The model never runs a
tool. It answers with a request to call one; the agent loop (agent/loop.py) runs it here,
in our code, and sends the result back to the model.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anthropic.types import ToolParam

from agent.notes import NotesClient, NotesUnavailable


class ToolError(Exception):
    """The tool could not do what was asked. The message goes back to the model."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # the model reads this to decide when to call the tool
    input_schema: dict[str, Any]  # JSON schema of the input the model must send
    run: Callable[[dict[str, Any]], str]  # our code: takes the input, returns text for the model

    def param(self) -> ToolParam:
        """The tool as the API expects it in `tools`: everything except our code."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def notes_tool(notes: NotesClient, conversation_id: str) -> Tool:
    """list_notes: read the notes of THIS conversation. Read-only, so a wrong call harms nothing.

    The conversation id is fixed here, by our code. The model chooses only what to search for,
    so it cannot read the notes of another conversation, whatever text it was given.
    """

    def run(tool_input: dict[str, Any]) -> str:
        # The model wrote this input. Check it like any other input from outside.
        unknown = set(tool_input) - {"search"}
        if unknown:
            raise ToolError(f"Unknown input field(s): {', '.join(sorted(unknown))}.")
        search = tool_input.get("search")
        if search is not None and not isinstance(search, str):
            raise ToolError("search must be a string.")
        try:
            found = notes.list(conversation_id, search or None)
        except NotesUnavailable as error:
            raise ToolError("The notes service is unavailable right now.") from error
        if not found:
            return "No notes found."
        return "\n".join(f"- {note.text}" for note in found)

    return Tool(
        name="list_notes",
        description=(
            "List the notes the user saved in this conversation (with /note). Call it when "
            "the user asks what they saved, noted or wrote down, or refers to their notes. "
            "Returns one note per line, oldest first, or 'No notes found.'"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Only notes that contain this text (any case). Leave it "
                    "out to list every note.",
                }
            },
            "additionalProperties": False,
        },
        run=run,
    )

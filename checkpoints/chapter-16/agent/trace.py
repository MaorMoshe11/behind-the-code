"""Run the agent loop once, on one question, and print every message of the run as JSON.

    uv run python -m agent.trace "What did I save in my notes about milk?"

It uses the settings in .env (CHAT_MOCK, NOTES_URL, CHAT_MAX_STEPS). The tool reads the
notes of the newest conversation; --conversation picks another one. Nothing is saved, and
the conversation's earlier messages are not sent: only this question.
"""

import argparse
import json
import sys
from typing import Any

from anthropic.types import MessageParam
from dotenv import load_dotenv

from agent.cli import make_client
from agent.config import load_settings
from agent.conversations import Conversations
from agent.db import make_engine
from agent.loop import run_agent
from agent.notes import make_notes
from agent.tools import notes_tool


def plain(value: Any) -> Any:
    """The model's blocks are SDK objects: turn them into plain JSON, like the wire format."""
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    if isinstance(value, list):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Print every message of one agent run.")
    parser.add_argument("message", help="the question to ask")
    parser.add_argument("--conversation", help="whose notes the tool reads (default: newest)")
    args = parser.parse_args()
    load_dotenv()
    settings = load_settings()
    notes = make_notes(settings)
    if notes is None:
        print("NOTES_URL is not set, so there is no tool to call. See README, 'The notes service'.")
        sys.exit(1)
    client = make_client(settings)
    conversations = Conversations(client, settings.max_turns, make_engine(settings.database_url))
    conversation_id = args.conversation or conversations.latest()
    if conversation_id is None:
        print("There is no conversation yet. Start one, and save a note with /note.")
        sys.exit(1)

    question: list[MessageParam] = [{"role": "user", "content": args.message}]
    tools = [notes_tool(notes, conversation_id)]
    run = run_agent(client, question, tools, settings.max_steps)

    print(f"tools: {json.dumps([tool.param() for tool in tools], indent=2)}")
    for number, message in enumerate(run.messages, start=1):
        print(f"--- message {number}, role: {message['role']}")
        print(json.dumps(plain(message["content"]), indent=2, ensure_ascii=False))
    print(f"--- stop: {run.stop}, steps: {run.steps}, tool calls: {run.tool_calls}")


if __name__ == "__main__":
    main()

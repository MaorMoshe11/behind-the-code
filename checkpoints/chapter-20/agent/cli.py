"""The terminal chat: reads what you type and prints the agent's replies."""

import argparse
import logging
import sys

from dotenv import load_dotenv
from rich.console import Console

from agent import logs
from agent.config import SYSTEM_PROMPT, ConfigError, Settings, load_settings
from agent.conversations import Conversations
from agent.db import DatabaseNotReady, make_engine
from agent.llm import AgentClient, ClaudeClient, LLMError, MockClient
from agent.notes import make_notes, note_command
from agent.security import DEFAULT_CLIENT
from agent.team import make_team

console = Console()
log = logging.getLogger(__name__)


def make_client(settings: Settings) -> AgentClient:
    """Pick the mock or the real client, according to the settings."""
    if settings.mock:
        print("Running in MOCK mode - answers are fake, nothing is sent to the API.")
        return MockClient(delay=settings.mock_delay)
    if not settings.api_key:
        print("ANTHROPIC_API_KEY is not set.")
        print("Put it in a .env file, or set CHAT_MOCK=1 to run without a key.")
        sys.exit(1)
    print(f"Chatting with {settings.model}.")
    return ClaudeClient(settings.model, SYSTEM_PROMPT)


def count_turns(turns: int) -> str:
    """'1 turn', '2 turns'. One turn is a question and its answer: two messages."""
    return "1 turn" if turns == 1 else f"{turns} turns"


def context_command(
    conversations: Conversations, client: AgentClient, conversation_id: str, text: str
) -> str | None:
    """/context, /compact, /memories and /forget; None for anything else."""
    if text == "/context":  # what the next call would send, before the next question
        toolbox = conversations.toolbox(conversation_id)
        context = conversations.context(conversation_id, toolbox)
        turns = len(conversations.messages(conversation_id)) // 2
        lines = [
            f"The next call, estimated (budget {context.budget.limit} tokens):",
            context.budget.report(),
            f"Saved in the database: {count_turns(turns)}.",
        ]
        if context.messages:  # the API counts only a request that has messages
            counted = client.count_tokens(context.messages, toolbox.params())
            lines.append(f"Counted by the client: {counted} tokens.")
        return "\n".join(lines)
    if text == "/compact":
        done = conversations.compact_now(conversation_id)
        return "Older turns summarised." if done else "Nothing to summarise yet."
    owner = conversations.owner(conversation_id) or DEFAULT_CLIENT
    memory = conversations.memory(owner)
    if text == "/memories":
        facts = memory.recall()
        if not facts:
            return "Nothing is remembered yet."
        return "\n".join(f"- [{fact.id[:8]}] {fact.text}" for fact in facts)
    if text.startswith("/forget"):
        ref = text.removeprefix("/forget").strip()
        if ref == "all":
            return f"Forgot {memory.forget_all()} memories."
        fact = memory.forget(ref) if ref else None
        return (
            f"Forgot: {fact.text}"
            if fact
            else "Usage: /forget <ref> (from /memories), or /forget all"
        )
    return None


def chat_loop(client: AgentClient, settings: Settings, resume: bool = False) -> None:
    """Run the conversation until the user quits. `resume` continues the newest one."""
    engine = make_engine(settings.database_url)
    notes = make_notes(settings)
    conversations = Conversations(
        client,
        settings.max_turns,
        engine,
        notes,
        settings.max_steps,
        settings.write_tools,
        context_tokens=settings.context_tokens,
        compact=settings.compact,
        team=make_team(settings),
    )
    print(
        "Type a message and press Enter. Commands: /reset, /history, /title, /note, /notes,\n"
        "/context, /compact, /memories, /forget, exit.\n"
    )
    # The terminal holds one conversation: the newest one, or a new one.
    last_id = conversations.latest() if resume else None
    if last_id is None:
        conversation_id = conversations.start(DEFAULT_CLIENT)  # the terminal is the owner's
    else:
        conversation_id = last_id
        turns = len(conversations.messages(conversation_id)) // 2
        title = conversations.title(conversation_id)
        print(f'Continuing "{title}" ({count_turns(turns)}).\n')

    while True:
        user_text = input("you> ").strip()
        if user_text.lower() in ("exit", "quit", "bye"):
            break
        if not user_text:
            continue
        if user_text == "/reset":
            # Forget the whole conversation and start a new one.
            conversations.reset(conversation_id)
            print("Conversation cleared. Starting over.\n")
            continue
        if user_text == "/history":
            turns = len(conversations.messages(conversation_id)) // 2
            print(f"{count_turns(turns)} saved in this conversation.\n")
            continue
        if user_text == "/title":
            try:  # the model suggests a title, as JSON (agent/titles.py)
                title, topic = conversations.retitle(conversation_id)
            except LLMError as error:
                print(f"{error}\n")
                continue
            about = f" (topic: {topic})" if topic else " (the model's suggestion did not fit)"
            print(f"Title: {title}{about}\n")
            continue
        context_reply = context_command(conversations, client, conversation_id, user_text)
        if context_reply is not None:
            print(f"{context_reply}\n")
            continue
        command_reply = note_command(notes, conversation_id, user_text)
        if command_reply is not None:
            print(f"{command_reply}\n")
            continue

        try:
            reply = conversations.send(conversation_id, user_text)
        except LLMError as error:
            # The user gets one clear sentence; the log gets the full traceback.
            log.exception("request failed")
            print(f"{error}\n")
            if error.fatal:
                sys.exit(1)
            continue

        console.print(f"{settings.agent_name}> {reply}\n", style="cyan", markup=False)

    print("Bye!")


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m agent", description="Chat in the terminal.")
    parser.add_argument(
        "--continue", dest="resume", action="store_true", help="continue the last conversation"
    )
    args = parser.parse_args()
    load_dotenv()
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"Configuration error: {error}")
        print("Fix the value in .env (or in the terminal) and run again.")
        sys.exit(1)
    # The terminal is for the chat, so the log lines go to a file.
    logs.setup_logging(settings.log_level, "chat-cli", filename="agent.log")
    log.info(
        "starting: mock=%s model=%s max_turns=%d", settings.mock, settings.model, settings.max_turns
    )
    client = make_client(settings)
    try:
        chat_loop(client, settings, resume=args.resume)
    except DatabaseNotReady as error:
        print(f"Database error: {error}")
        sys.exit(1)

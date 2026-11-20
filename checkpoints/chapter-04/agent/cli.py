"""The terminal chat: reads what you type and prints the agent's replies."""

import logging
import sys

from anthropic.types import MessageParam
from dotenv import load_dotenv
from rich.console import Console

from agent.config import SYSTEM_PROMPT, ConfigError, Settings, load_settings
from agent.history import trim_history
from agent.llm import ChatClient, ClaudeClient, LLMError, MockClient

console = Console()
log = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    """Send log records to agent.log, so the terminal stays clean for the chat."""
    logging.basicConfig(
        filename="agent.log",
        encoding="utf-8",
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def make_client(settings: Settings) -> ChatClient:
    """Pick the mock or the real client, according to the settings."""
    if settings.mock:
        print("Running in MOCK mode - answers are fake, nothing is sent to the API.")
        return MockClient()
    if not settings.api_key:
        print("ANTHROPIC_API_KEY is not set.")
        print("Put it in a .env file, or set CHAT_MOCK=1 to run without a key.")
        sys.exit(1)
    print(f"Chatting with {settings.model}.")
    return ClaudeClient(settings.model, SYSTEM_PROMPT)


def chat_loop(client: ChatClient, settings: Settings) -> None:
    """Run the conversation until the user quits."""
    print("Type a message and press Enter. Commands: /reset, /history, exit.\n")
    messages: list[MessageParam] = []

    while True:
        user_text = input("you> ").strip()
        if user_text.lower() in ("exit", "quit", "bye"):
            break
        if not user_text:
            continue
        if user_text == "/reset":
            # Forget the whole conversation and start a new one.
            messages.clear()
            print("Conversation cleared. Starting over.\n")
            continue
        if user_text == "/history":
            # One turn is a question and its answer: two messages.
            print(f"{len(messages) // 2} turns in memory.\n")
            continue

        messages.append({"role": "user", "content": user_text})
        log.info("sending %d messages", len(messages))

        try:
            reply = client.reply(messages)
        except LLMError as error:
            # The user gets one clear sentence; the log gets the full traceback.
            log.exception("request failed")
            print(f"{error}\n")
            if error.fatal:
                sys.exit(1)
            messages.pop()  # forget the message that got no answer
            continue

        messages.append({"role": "assistant", "content": reply})
        # Keep only the last turns, so long chats do not get slow and expensive.
        messages = trim_history(messages, settings.max_turns)
        console.print(f"{settings.agent_name}> {reply}\n", style="cyan", markup=False)

    print("Bye!")


def main() -> None:
    load_dotenv()
    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"Configuration error: {error}")
        print("Fix the value in .env (or in the terminal) and run again.")
        sys.exit(1)
    setup_logging(settings.log_level)
    log.info(
        "starting: mock=%s model=%s max_turns=%d", settings.mock, settings.model, settings.max_turns
    )
    client = make_client(settings)
    chat_loop(client, settings)

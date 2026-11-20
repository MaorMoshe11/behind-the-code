"""chat.py - a minimal chat agent that runs in the terminal.

This is the starting point of the workbook project. It keeps the whole
conversation in a list called `messages` and sends that list to Claude on
every turn, because the API itself remembers nothing between requests.

Settings come from environment variables (see .env.example):
    ANTHROPIC_API_KEY  your secret API key (not needed in mock mode)
    CHAT_MODEL         which Claude model to use
    CHAT_MOCK          set to 1 to get fake answers without calling the API
    AGENT_NAME         the name printed before each reply
"""

import os
import sys

import anthropic
from dotenv import load_dotenv
from rich.console import Console

# Read the .env file (if there is one) into environment variables.
load_dotenv()

MODEL = os.getenv("CHAT_MODEL", "claude-opus-5-5")
MOCK = os.getenv("CHAT_MOCK", "0") == "1"
AGENT_NAME = os.getenv("AGENT_NAME", "agent")
SYSTEM_PROMPT = "You are a friendly assistant. Keep your answers short."

console = Console()


def ask_claude(client, messages):
    """Send the whole conversation to Claude and return the reply text."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    if response.stop_reason == "refusal":
        return "(The model declined to answer this request.)"
    return "".join(block.text for block in response.content if block.type == "text")


def ask_mock(messages):
    """Return a fake reply. Costs nothing and needs no API key."""
    last_user_message = messages[-1]["content"]
    turn = (len(messages) + 1) // 2
    return f"[mock reply, turn {turn}] You said: {last_user_message}"


def main():
    if MOCK:
        client = None
        print("Running in MOCK mode - answers are fake, nothing is sent to the API.")
    else:
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set.")
            print("Put it in a .env file, or set CHAT_MOCK=1 to run without a key.")
            sys.exit(1)
        client = anthropic.Anthropic()
        print(f"Chatting with {MODEL}.")

    print("Type a message and press Enter. Type 'exit' to quit.\n")
    messages = []

    while True:
        user_text = input("you> ").strip()
        if user_text.lower() in ("exit", "quit"):
            break
        if not user_text:
            continue

        messages.append({"role": "user", "content": user_text})

        try:
            reply = ask_mock(messages) if MOCK else ask_claude(client, messages)
        except anthropic.AuthenticationError:
            print("The API rejected your key. Check ANTHROPIC_API_KEY in .env.")
            sys.exit(1)
        except anthropic.APIConnectionError:
            print("Could not reach the API. Check your internet connection.\n")
            messages.pop()
            continue
        except anthropic.APIStatusError as error:
            print(f"The API returned an error ({error.status_code}): {error.message}\n")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})
        console.print(f"{AGENT_NAME}> {reply}\n", style="cyan", markup=False)

    print("Bye!")


if __name__ == "__main__":
    main()

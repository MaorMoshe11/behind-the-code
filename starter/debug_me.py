"""debug_me.py - a small function with a bug, for the debugger exercise.

Long conversations cost more, so chat agents often keep only the most
recent turns. One turn = one user message + one assistant reply.

Run this file. The output is wrong. Find out why with the debugger,
not by staring at the code.
"""


def trim_history(messages, max_turns):
    """Keep only the last `max_turns` turns of the conversation."""
    if len(messages) <= max_turns * 2:
        return messages
    return messages[-max_turns:]


def build_demo_history(turns):
    """Build a fake conversation with the given number of turns."""
    messages = []
    for number in range(1, turns + 1):
        messages.append({"role": "user", "content": f"question {number}"})
        messages.append({"role": "assistant", "content": f"answer {number}"})
    return messages


if __name__ == "__main__":
    history = build_demo_history(turns=5)
    trimmed = trim_history(history, max_turns=3)

    print("Expected: 6 messages, the first one from 'user'")
    print(f"Got:      {len(trimmed)} messages, the first one from '{trimmed[0]['role']}'")

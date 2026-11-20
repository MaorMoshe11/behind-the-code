"""The conversation history, and how it is kept short."""

from anthropic.types import MessageParam


def trim_history(messages: list[MessageParam], max_turns: int) -> list[MessageParam]:
    """Keep only the last `max_turns` turns of the conversation.

    One turn is two messages: the user's message and the assistant's reply.
    The result always starts with a user message, because the API requires it.
    """
    if max_turns < 1:
        # messages[-0:] would silently return everything, so refuse instead.
        raise ValueError(f"max_turns must be 1 or more, got {max_turns}")
    if len(messages) <= max_turns * 2:
        return messages
    trimmed = messages[-max_turns * 2 :]
    if trimmed[0]["role"] != "user":
        # The cut fell between a question and its answer: drop the orphan answer.
        trimmed = trimmed[1:]
    return trimmed

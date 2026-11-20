"""A saga: one business operation over several services, as a chain of local steps.

There is no transaction across the chat's database and the notes service. So every step
commits on its own, and every step that may need undoing comes with a compensation: a new
action that undoes it in business terms. If a step fails, the steps already done are
compensated, newest first. This module is the orchestrator: one place runs the steps in order.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from agent.conversations import Conversations
from agent.notes import Note, NotesClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    name: str
    action: Callable[[], None]
    compensate: Callable[[], None] | None = None  # None: nothing to undo


def run_saga(name: str, steps: list[Step]) -> None:
    """Run the steps in order. If one fails, compensate those done, then raise its error."""
    done: list[Step] = []
    for step in steps:
        try:
            step.action()
        except Exception:
            log.warning("saga %s: step %r failed; compensating", name, step.name)
            for finished in reversed(done):
                if finished.compensate is None:
                    continue
                try:
                    finished.compensate()
                    log.warning("saga %s: compensated %r", name, finished.name)
                except Exception:
                    # Now the data is inconsistent, and only a person can fix it: say so loudly.
                    log.exception("saga %s: COMPENSATION FAILED for %r", name, finished.name)
            raise
        log.info("saga %s: step %r done", name, step.name)
        done.append(step)


def delete_conversation(
    conversations: Conversations, notes: NotesClient | None, conversation_id: str
) -> list[Step]:
    """The steps that delete a conversation in the chat and its notes in the notes service."""
    deleted: list[Note] = []  # what step 2 deleted, kept for its compensation

    def delete_notes() -> None:
        assert notes is not None
        deleted.extend(notes.delete_all(conversation_id))

    def restore_notes() -> None:
        assert notes is not None
        notes.restore(conversation_id, deleted)

    steps = [
        # 1. Hide it first, so nobody writes to a conversation that is being deleted.
        Step(
            "archive the conversation",
            lambda: conversations.archive(conversation_id),
            lambda: conversations.unarchive(conversation_id),
        )
    ]
    if notes is not None:
        # 2. The step that may fail: another service, over the network.
        steps.append(Step("delete its notes", delete_notes, restore_notes))
    # 3. The point of no return: after this, the saga only goes forward.
    steps.append(Step("delete the conversation", lambda: conversations.delete(conversation_id)))
    return steps

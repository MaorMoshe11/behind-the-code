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
from agent.metrics import SAGAS
from agent.notes import Note, NotesClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Step:
    name: str
    action: Callable[[], None]
    compensate: Callable[[], None] | None = None  # None: nothing to undo


def run_saga(name: str, steps: list[Step]) -> None:
    """Run the steps in order. If one fails, compensate it and those done, then raise its error.

    The failed step is compensated too: "failed" may mean "timed out after doing the work",
    so its compensation must work whatever the step really did (nothing, part, or all).
    """
    done: list[Step] = []
    for step in steps:
        try:
            step.action()
        except Exception:
            log.warning("saga %s: step %r failed; compensating", name, step.name, exc_info=True)
            outcome = "compensated"
            for finished in reversed([*done, step]):
                if finished.compensate is None:
                    continue
                try:
                    finished.compensate()
                    log.warning("saga %s: compensated %r", name, finished.name)
                except Exception:
                    # Now the data is inconsistent, and only a person can fix it: say so loudly.
                    log.exception("saga %s: COMPENSATION FAILED for %r", name, finished.name)
                    outcome = "compensation_failed"
            SAGAS.labels(name, outcome).inc()
            raise
        log.info("saga %s: step %r done", name, step.name)
        done.append(step)
    SAGAS.labels(name, "done").inc()


def delete_conversation(
    conversations: Conversations, notes: NotesClient | None, conversation_id: str
) -> list[Step]:
    """The steps that delete a conversation in the chat and its notes in the notes service."""
    before: list[Note] = []  # the notes as they were before step 2, for its compensation

    def delete_notes() -> None:
        assert notes is not None
        # Remember first. The answer to the delete may never arrive (a timeout), even
        # when the delete itself happened: then only this list knows what was there.
        before.extend(notes.list(conversation_id))
        notes.delete_all(conversation_id)

    def restore_notes() -> None:
        assert notes is not None
        if not before:
            return  # nothing was there, or step 2 failed before it could change anything
        # Put back the notes that are gone now, whatever the delete really did.
        present = {note.id for note in notes.list(conversation_id)}
        notes.restore(conversation_id, [note for note in before if note.id not in present])

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

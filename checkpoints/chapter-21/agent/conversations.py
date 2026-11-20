"""The core of the agent: conversations and their messages.

The terminal chat and the HTTP API both use this module, so they behave the same.
Every message is saved in the database, so conversations survive a restart: the questions
and answers, and (since chapter 19) the tool steps of every agent run. What the model sees
on a call is assembled from them within a budget (agent/context.py); older turns are
summarised rather than dropped (agent/compaction.py).

Every message is one trace (agent/tracing.py): its spans say what ran, how long it took, what
it cost. Guardrails check the message before the model and the reply after it.
"""

import json
import logging
import time
import uuid

from anthropic.types import MessageParam
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from agent import tracing
from agent.approvals import Approver, Pending
from agent.compaction import KEEP_TURNS, summarize
from agent.config import SYSTEM_PROMPT
from agent.context import Context, build_context, fingerprint, plain, shrink_result, split_turns
from agent.db import ConversationRow, MessageRow, SummaryRow, now
from agent.guardrails import check_input, check_output
from agent.history import trim_history
from agent.llm import AgentClient
from agent.loop import run_agent
from agent.memory import MemoryStore
from agent.metrics import COMPACTIONS, LLM_SECONDS
from agent.notes import NotesClient
from agent.notes_tools import TOOLS
from agent.security import DEFAULT_CLIENT
from agent.team import Team
from agent.titles import TITLE_LENGTH, suggest_title
from agent.tools import Outcome, Toolbox, ToolContext, ToolRegistry

log = logging.getLogger(__name__)
CUT = "..."  # ends a title that was cut; ASCII, so every terminal and file can show it
NEW_TITLE = "New conversation"  # until the first message arrives
VISIBLE = ConversationRow.archived_at.is_(None)  # lists never show archived conversations


class ConversationNotFound(Exception):
    """No conversation has this id (it was deleted, or never existed)."""


def make_title(text: str) -> str:
    """One line for lists: the start of the first message, cut after a whole word.

    Migration 0008 has a copy of this rule as it was then (AGENT-42); that copy never changes.
    """
    words = " ".join(text.split())  # line breaks, tabs and repeated spaces become one space
    if not words:
        return NEW_TITLE
    if len(words) <= TITLE_LENGTH:
        return words
    room = TITLE_LENGTH - len(CUT)
    space = words.rfind(" ", 0, room + 1)  # the last space that leaves room for the CUT
    end = space if space > 0 else room  # one word longer than the room: cut inside it
    return words[:end].rstrip(".,;:") + CUT  # "2." + "..." would read "2...."


# Blocks that are not sent back from a stored turn: a thinking block is valid only in the
# exact conversation that produced it, and a later context (trimmed, summarised) is not that.
NOT_REPLAYED = {"thinking", "redacted_thinking"}


def to_param(row: MessageRow) -> MessageParam:
    """A row from the database, in the shape the model client expects."""
    if row.kind == "blocks":  # one step of an agent run, stored as JSON blocks
        blocks = [block for block in json.loads(row.content) if block["type"] not in NOT_REPLAYED]
        if row.role == "user":
            return {"role": "user", "content": blocks}
        return {"role": "assistant", "content": blocks}
    if row.role == "user":
        return {"role": "user", "content": row.content}
    return {"role": "assistant", "content": row.content}


class Conversations:
    """Every conversation, by id, and the one way to add a message to it."""

    def __init__(
        self,
        client: AgentClient,
        max_turns: int,
        engine: Engine,
        notes: NotesClient | None = None,
        max_steps: int = 5,
        write_tools: bool = False,
        tools: ToolRegistry = TOOLS,
        context_tokens: int = 16000,
        compact: bool = True,
        system_prompt: str = SYSTEM_PROMPT,
        team: Team | None = None,
        approve_writes: bool = False,
        trace_dir: str | None = None,
    ) -> None:
        self.client = client
        self.max_turns = max_turns
        self.sessions = sessionmaker(engine)
        self.notes = notes  # with a notes service, the model gets the notes tools
        self.max_steps = max_steps
        self.write_tools = write_tools  # CHAT_WRITE_TOOLS: may the model add and delete notes?
        self.tools = tools
        self.context_tokens = context_tokens  # CHAT_CONTEXT_TOKENS: the budget of one call
        self.compact = compact  # CHAT_COMPACT: summarise older turns instead of dropping them
        self.system_prompt = system_prompt  # only to count it: the client sends it
        self.team = team  # CHAT_TEAM=1: a router may hand a message to the orchestrator
        self.approve_writes = approve_writes  # CHAT_WRITE_TOOLS=ask: a person approves writes
        self.trace_dir = trace_dir  # CHAT_TRACE_DIR: save every message's trace there

    def toolbox(self, conversation_id: str, approver: Approver | None = None) -> Toolbox:
        """The tools of one run. The conversation and its owner are fixed here, by our code;
        so is who may approve a write (the terminal, the API's desk, or nobody)."""
        owner = self.owner(conversation_id) or DEFAULT_CLIENT
        context = ToolContext(self.notes, conversation_id, MemoryStore(self.sessions, owner))
        return self.tools.toolbox(context, self.write_tools, approver, self.approve_writes)

    def carry_out(self, pending: Pending) -> Outcome:
        """Run a call a person approved over HTTP: exactly the stored tool and input."""
        toolbox = self.toolbox(pending.conversation_id)
        outcome = toolbox.call(pending.request.tool, pending.request.input, approved=True)
        log.info(
            "approved call ran", extra={"tool": pending.request.tool, "ok": not outcome.is_error}
        )
        return outcome

    def answer(
        self, prompt: list[MessageParam], toolbox: Toolbox
    ) -> tuple[str, list[MessageParam]]:
        """The reply, and the tool steps that led to it (requests and results, to be stored).
        No tools: one model call. With tools: the agent loop."""
        if not toolbox.tools:
            return self.client.reply(prompt), []
        run = run_agent(self.client, prompt, toolbox, self.max_steps)
        steps = run.messages[len(prompt) :]
        if steps and steps[-1]["role"] == "assistant":
            steps = steps[:-1]  # the final answer is stored as text, like every answer
        return run.reply, steps

    def _since_summary(
        self, session: Session, conversation_id: str
    ) -> tuple[SummaryRow | None, list[MessageRow]]:
        """The newest summary, and every message after the last one it covers."""
        summary = session.scalar(
            select(SummaryRow)
            .where(SummaryRow.conversation_id == conversation_id)
            .order_by(SummaryRow.id.desc())
            .limit(1)
        )
        query = select(MessageRow).where(MessageRow.conversation_id == conversation_id)
        if summary is not None:
            query = query.where(MessageRow.id > summary.upto_message_id)
        return summary, list(session.scalars(query.order_by(MessageRow.id)))

    def context(
        self, conversation_id: str, toolbox: Toolbox, question: MessageParam | None = None
    ) -> Context:
        """What the model would see now: the summary, the newest turns that fit, the question."""
        with self.sessions() as session:
            self._require(session, conversation_id)
            summary, rows = self._since_summary(session, conversation_id)
            history = [to_param(row) for row in rows]
        return build_context(
            self.system_prompt,
            toolbox.params(),
            history,
            question,
            self.context_tokens,
            self.max_turns,
            summary.content if summary else None,
        )

    def compact_now(self, conversation_id: str, keep: int = KEEP_TURNS) -> bool:
        """Summarise every turn except the newest `keep`. The turns stay stored; the new
        summary replaces them in the context. False if there was nothing old enough."""
        with self.sessions() as session:
            summary, rows = self._since_summary(session, conversation_id)
            turns = split_turns([to_param(row) for row in rows])
            if len(turns) <= keep:
                return False
            old = turns[: len(turns) - keep]
            upto = rows[sum(len(turn) for turn in old) - 1].id  # the last message summarised
            before = summary.content if summary else None
        with tracing.span("compaction", "compaction"):
            text = summarize(self.client, before, old)
        with self.sessions.begin() as session:
            session.add(
                SummaryRow(conversation_id=conversation_id, upto_message_id=upto, content=text)
            )
        COMPACTIONS.inc()
        log.info("conversation compacted", extra={"turns": len(old), "summary_chars": len(text)})
        return True

    def _require(self, session: Session, conversation_id: str) -> ConversationRow:
        row = session.get(ConversationRow, conversation_id)
        if row is None or row.archived_at is not None:  # archived: hidden, as if deleted
            raise ConversationNotFound(conversation_id)
        return row

    def start(self, user_id: str | None = None) -> str:
        """Open a new, empty conversation for this user and return its id."""
        conversation_id = uuid.uuid4().hex
        with self.sessions.begin() as session:
            session.add(ConversationRow(id=conversation_id, title=NEW_TITLE, user_id=user_id))
        return conversation_id

    def memory(self, owner: str) -> MemoryStore:
        """The long-term memory of one owner (for /memories, /forget and the API)."""
        return MemoryStore(self.sessions, owner)

    def owner(self, conversation_id: str) -> str | None:
        """Who the conversation belongs to (its user_id)."""
        with self.sessions() as session:
            return self._require(session, conversation_id).user_id

    def latest(self) -> str | None:
        """The id of the newest conversation, or None when there is none."""
        return latest_conversation(self.sessions)

    def newest(self, limit: int = 50, user_id: str | None = None) -> list[tuple[str, str]]:
        """(id, title) of the newest conversations, newest first; only this user's, if given."""
        query = select(ConversationRow.id, ConversationRow.title).where(VISIBLE)
        if user_id is not None:
            query = query.where(ConversationRow.user_id == user_id)
        with self.sessions() as session:
            rows = session.execute(query.order_by(ConversationRow.created_at.desc()).limit(limit))
            return [(row.id, row.title) for row in rows]

    def title(self, conversation_id: str) -> str:
        """The conversation's title: the start of its first message."""
        with self.sessions() as session:
            return self._require(session, conversation_id).title

    def messages(self, conversation_id: str) -> list[MessageParam]:
        """Every question and answer in this conversation, oldest first (not the tool steps)."""
        with self.sessions() as session:
            self._require(session, conversation_id)
            rows = session.scalars(
                select(MessageRow)
                .where(MessageRow.conversation_id == conversation_id)
                .where(MessageRow.kind == "text")
                .order_by(MessageRow.id)
            )
            return [to_param(row) for row in rows]

    def send(self, conversation_id: str, text: str, approver: Approver | None = None) -> str:
        """Send the user's message in a context built from the stored history, and save the
        whole turn: the question, the tool steps, and the answer. One trace per message."""
        check_input(text)  # a guardrail: before the model, the database and the logs
        top = tracing.current.get() is None  # an eval wraps this in a span of its own
        with tracing.span("message", "message") as root:
            reply = self._send(conversation_id, text, approver)
        if top and self.trace_dir:
            path = tracing.save(root, self.trace_dir)
            log.info("trace saved", extra={"trace": str(path)})
        return reply

    def _send(self, conversation_id: str, text: str, approver: Approver | None) -> str:
        root = tracing.current.get()
        history = self.messages(conversation_id)
        toolbox = self.toolbox(conversation_id, approver)
        question: MessageParam = {"role": "user", "content": text}
        context = self.context(conversation_id, toolbox, question)
        if context.budget.dropped and self.compact:
            # Something would fall out of the context: summarise the older turns first,
            # keeping as many recent turns as fit (at most KEEP_TURNS).
            if self.compact_now(conversation_id, min(KEEP_TURNS, context.budget.kept)):
                context = self.context(conversation_id, toolbox, question)
        start = time.perf_counter()
        # If this fails, nothing was saved.
        if self.team is not None and self.team.wants(text):
            # The team's work stays in the log; the conversation keeps the question and
            # the answer, as text (the delegations belong to the orchestrator's tools).
            reply = self.team.answer(context.messages, toolbox.context)
            steps: list[MessageParam] = []
        else:
            reply, steps = self.answer(context.messages, toolbox)
        reply = check_output(reply)  # a guardrail: after the model, before saving and showing
        seconds = time.perf_counter() - start
        LLM_SECONDS.observe(seconds)
        budget = context.budget
        log.info(
            "model replied",
            extra={
                "conversation_id": conversation_id,  # cost per conversation: sum these lines
                "messages": len(context.messages),
                "llm_ms": round(seconds * 1000),
                "context_tokens": budget.total,  # estimated, before the call
                "turns_sent": budget.kept,
                "turns_left_out": budget.dropped,
                # What this message cost, all model calls together (the router, the team...)
                "tokens": root.total_tokens() if root else None,
                "cost_usd": round(root.total_cost(), 6) if root else None,
                # Which prompt and tool descriptions answered: changes when either changes
                "prompt_version": fingerprint(self.system_prompt, toolbox.params()),
            },
        )
        # One transaction: the whole turn is saved, or none of it.
        with self.sessions.begin() as session:
            session.add(MessageRow(conversation_id=conversation_id, role="user", content=text))
            for step in steps:  # tool requests and results, long results cut (agent/context.py)
                kept = json.dumps(plain(shrink_result(step)["content"]), ensure_ascii=False)
                session.add(
                    MessageRow(
                        conversation_id=conversation_id,
                        role=step["role"],
                        kind="blocks",
                        content=kept,
                    )
                )
            session.add(
                MessageRow(conversation_id=conversation_id, role="assistant", content=reply)
            )
            if not history:  # the first message names the conversation
                session.execute(
                    update(ConversationRow)
                    .where(ConversationRow.id == conversation_id)
                    .values(title=make_title(text))
                )
        return reply

    def retitle(self, conversation_id: str) -> tuple[str, str | None]:
        """Ask the model for a better title and save it: (title, topic).

        When the model's answer does not fit, even after a retry, the title stays the
        automatic one (the start of the first message), and topic is None.
        """
        history = self.messages(conversation_id)
        suggestion = suggest_title(self.client, trim_history(history, self.max_turns))
        if suggestion is None:
            first = next((m["content"] for m in history if m["role"] == "user"), "")
            title, topic = make_title(str(first)), None
        else:
            title, topic = suggestion.title, suggestion.topic
        with self.sessions.begin() as session:
            self._require(session, conversation_id).title = title
        log.info("conversation retitled", extra={"suggested": suggestion is not None})
        return title, topic

    def reset(self, conversation_id: str) -> None:
        """Delete every message (and summary) in this conversation, but keep the conversation."""
        with self.sessions.begin() as session:
            self._require(session, conversation_id)
            session.execute(delete(SummaryRow).where(SummaryRow.conversation_id == conversation_id))
            session.execute(delete(MessageRow).where(MessageRow.conversation_id == conversation_id))

    def archive(self, conversation_id: str) -> None:
        """Hide the conversation: it is still stored, but works as if it were deleted."""
        with self.sessions.begin() as session:
            self._require(session, conversation_id).archived_at = now()

    def unarchive(self, conversation_id: str) -> None:
        """Undo archive(): the conversation is back, exactly as it was."""
        with self.sessions.begin() as session:
            session.execute(
                update(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .values(archived_at=None)
            )

    def delete(self, conversation_id: str) -> None:
        """Delete the conversation and its messages, archived or not. Its id stops working."""
        with self.sessions.begin() as session:
            if session.get(ConversationRow, conversation_id) is None:
                raise ConversationNotFound(conversation_id)
            session.execute(delete(SummaryRow).where(SummaryRow.conversation_id == conversation_id))
            session.execute(delete(MessageRow).where(MessageRow.conversation_id == conversation_id))
            session.execute(delete(ConversationRow).where(ConversationRow.id == conversation_id))


def latest_conversation(sessions: sessionmaker[Session]) -> str | None:
    """The id of the newest conversation that is not archived, or None when there is none."""
    with sessions() as session:
        newest_first = select(ConversationRow.id).order_by(ConversationRow.created_at.desc())
        return session.scalar(newest_first.where(VISIBLE).limit(1))

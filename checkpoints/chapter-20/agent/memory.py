"""Long-term memory, and search over earlier conversations: what outlives one conversation.

A MemoryStore belongs to one owner (the client a conversation belongs to, chapter 14). Every
query here filters by that owner, in our code: one client's memories and conversations are
never visible to another, whatever the model asks for.

Search is by keywords, in SQL: offline, deterministic, and good at exact words. It does not
know that "dessert" and "cake" are related; that is what embeddings are for.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from agent.db import ConversationRow, MemoryRow, MessageRow, now

MEMORY_LIMIT = 100  # facts per owner, at most: memory is for what matters, not for everything
# Words that match almost every message, so they are not searched for.
STOP_WORDS = {
    "the", "and", "for", "you", "your", "are", "was", "what", "did", "about", "that", "this",
    "with", "have", "has", "had", "how", "can", "our", "from", "they", "them", "she", "her",
}  # fmt: skip


def stem(word: str) -> str:
    """A plural without its s, so that "cakes" also finds "cake" (a search for "cake" finds
    "cakes" already: it is contained in it). Crude, English only, and enough here."""
    if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def keywords(text: str) -> list[str]:
    """The words worth searching for: lowercase, three letters or more, no stop words,
    plurals without their s."""
    words = re.findall(r"[^\W_]{3,}", text.lower())
    return list(dict.fromkeys(stem(word) for word in words if word not in STOP_WORDS))


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    created_at: datetime


@dataclass(frozen=True)
class Hit:
    """One message of an earlier conversation that matches a search."""

    title: str
    created_at: datetime
    role: str
    text: str
    score: int  # how many of the search words it contains


def snippet(text: str, word: str, width: int = 160) -> str:
    """The part of a long text around the first place the word appears."""
    flat = " ".join(text.split())
    if len(flat) <= width:
        return flat
    at = max(flat.lower().find(word), 0)
    start = max(at - width // 3, 0)
    return ("..." if start else "") + flat[start : start + width] + "..."


class MemoryStore:
    """The memories and the earlier conversations of ONE owner."""

    def __init__(self, sessions: sessionmaker[Session], owner: str) -> None:
        self.sessions = sessions
        self.owner = owner

    def _mine(self) -> list[MemoryRow]:
        with self.sessions() as session:
            query = select(MemoryRow).where(MemoryRow.user_id == self.owner)
            return list(session.scalars(query.order_by(MemoryRow.created_at, MemoryRow.id)))

    def remember(self, text: str) -> tuple[Fact, bool]:
        """Save a fact; (fact, True) if new, (the same fact, False) if it was already there."""
        for row in self._mine():
            if row.text.lower() == text.lower():
                return Fact(row.id, row.text, row.created_at), False
        fact = Fact(uuid.uuid4().hex, text, now())
        with self.sessions.begin() as session:
            session.add(
                MemoryRow(id=fact.id, user_id=self.owner, text=text, created_at=fact.created_at)
            )
        return fact, True

    def is_full(self) -> bool:
        return len(self._mine()) >= MEMORY_LIMIT

    def recall(self, search: str = "") -> list[Fact]:
        """Every fact, oldest first; with `search`, only facts that contain one of its words."""
        words = keywords(search)
        facts = [Fact(row.id, row.text, row.created_at) for row in self._mine()]
        if not words:
            return facts
        return [fact for fact in facts if any(word in fact.text.lower() for word in words)]

    def forget(self, ref: str) -> Fact | None:
        """Delete one of this owner's facts, by the start of its id."""
        for fact in self.recall():
            if fact.id.startswith(ref):
                with self.sessions.begin() as session:
                    session.execute(delete(MemoryRow).where(MemoryRow.id == fact.id))
                return fact
        return None

    def forget_all(self) -> int:
        """Delete everything this owner's memory holds (the right to be forgotten)."""
        with self.sessions.begin() as session:
            result = session.execute(delete(MemoryRow).where(MemoryRow.user_id == self.owner))
            return int(getattr(result, "rowcount", 0) or 0)

    def search_conversations(self, query: str, exclude: str | None, limit: int = 5) -> list[Hit]:
        """Messages of this owner's other conversations that contain the query's words.

        Keyword search in SQL: each word must appear as written (any case). The messages
        that contain the most words, then the newest, come first.
        """
        words = keywords(query)
        if not words:
            return []
        text = func.lower(MessageRow.content)
        found = (
            select(MessageRow, ConversationRow.title)
            .join(ConversationRow, MessageRow.conversation_id == ConversationRow.id)
            .where(ConversationRow.user_id == self.owner)  # only this owner's conversations
            .where(ConversationRow.archived_at.is_(None))
            .where(MessageRow.kind == "text")  # questions and answers, not tool steps
            .where(or_(*[text.contains(word, autoescape=True) for word in words]))
            .order_by(MessageRow.id.desc())
            .limit(200)
        )
        if exclude is not None:  # the conversation we are in is already in the context
            found = found.where(MessageRow.conversation_id != exclude)
        with self.sessions() as session:
            rows = session.execute(found).all()
        hits = []
        for message, title in rows:
            lower = message.content.lower()
            matched = [word for word in words if word in lower]
            hits.append(
                Hit(
                    title=title,
                    created_at=message.created_at,
                    role=message.role,
                    text=snippet(message.content, matched[0]),
                    score=len(matched),
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)  # stable: newest first among equals
        return hits[:limit]

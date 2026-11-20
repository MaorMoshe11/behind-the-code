"""A conversation's title, made from its first message (AGENT-42).

One test case per acceptance criterion of the ticket, so a reviewer can check them one by one.
"""

import pytest

from agent.conversations import NEW_TITLE, TITLE_LENGTH, make_title

CASES = [
    # 4. a message that fits is the whole title
    ("hi", "hi"),
    ("x" * 50, "x" * 50),
    # 1. line breaks, tabs and repeated spaces become one space; the ends are trimmed
    ("  plan   a\ttrip\n", "plan a trip"),
    # 1 and 3. a pasted error: one line, cut after the last whole word, with ...
    (
        "Here is my error:\nTraceback (most recent call last):\n  File app.py, line 3",
        "Here is my error: Traceback (most recent call...",
    ),
    (
        "Could you explain how database indexes work in PostgreSQL and in SQLite?",
        "Could you explain how database indexes work in...",
    ),
    # 3. a first word longer than the limit is cut inside the word
    ("https://example.com/" + "a" * 60, "https://example.com/" + "a" * 27 + "..."),
    # Hebrew is cut at words too
    (
        "אפשר עזרה במכתב לבעל הדירה על החימום שלא עובד כבר שבוע שלם?",
        "אפשר עזרה במכתב לבעל הדירה על החימום שלא עובד...",
    ),
    # AGENT-44: a cut after a word that ends in a dot ("2.") must not end in "...."
    (
        "Please review my plan:\n1. Read the ticket\n2. Ask questions\n3. Write the design doc",
        "Please review my plan: 1. Read the ticket 2...",
    ),
    # 5. whitespace only: the conversation keeps its first title
    (" \n\t ", NEW_TITLE),
]


@pytest.mark.parametrize(("text", "title"), CASES)
def test_the_title_is_one_line_cut_at_a_word(text, title):
    assert make_title(text) == title


@pytest.mark.parametrize(("text", "title"), CASES)
def test_a_title_is_never_longer_than_the_limit(text, title):
    # 2. at most 50 characters, including the "..."
    assert len(make_title(text)) <= TITLE_LENGTH

"""current_time: what a model cannot know by itself, today's date and time (exercise 3)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from agent.tools import Tool, ToolContext, ToolInput

Zone = Literal["UTC", "Asia/Jerusalem", "Europe/London", "America/New_York"]


class CurrentTimeInput(ToolInput):
    timezone: Zone = Field("UTC", description="Where the user is. Leave it out for UTC.")


def make_current_time(now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> Tool:
    """The tool. A test passes its own `now`, so the answer is always the same."""

    def run(context: ToolContext, args: CurrentTimeInput) -> str:
        local = now().astimezone(ZoneInfo(args.timezone))
        return local.strftime(f"%A %Y-%m-%d %H:%M ({args.timezone})")

    return Tool(
        name="current_time",
        description=(
            "Today's date, the day of the week and the time. Call it when the answer depends "
            "on today: 'what day is it', 'how long until Monday', 'is it late in London'."
        ),
        input_model=CurrentTimeInput,
        run=run,
    )

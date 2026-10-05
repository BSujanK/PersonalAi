"""WRITE tools that act on the phone. Approval only queues a command; the app fires it."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from agent.core.clock import Clock
from agent.core.tools import Tool, ToolKind, ToolRegistry
from agent.phone.commands import CommandQueue
from agent.workspace.calendar_tools import check_int, check_text

ALARM_TTL = timedelta(hours=24)
MAX_TIMER_SECONDS = 24 * 60 * 60
MAX_REMINDER_AHEAD = timedelta(days=365)
_DAY_NAMES = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")  # Android: 1 = Sunday


def _label(args: dict[str, Any], name: str, limit: int, *, required: bool = False) -> str:
    value = args.get(name)
    if value is None and not required:
        return ""
    return check_text(value, name, limit=limit, minimum=1 if required else 0, one_line=True)


def _alarm(args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {
        "hour": check_int(args.get("hour"), 0, 23, "hour"),
        "minute": check_int(args.get("minute"), 0, 59, "minute"),
        "label": _label(args, "label", 60),
    }
    days = args.get("days")
    if days is not None:
        if not isinstance(days, list) or not 1 <= len(days) <= 7:
            raise ValueError("days must be a list of 1 to 7 weekdays")
        checked = sorted({check_int(d, 1, 7, "days") for d in days})
        if len(checked) != len(days):
            raise ValueError("days must not repeat")
        params["days"] = checked
    return params


def _timer(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "seconds": check_int(args.get("seconds"), 1, MAX_TIMER_SECONDS, "seconds"),
        "label": _label(args, "label", 60),
    }


def _reminder(args: dict[str, Any], now: datetime) -> tuple[dict[str, Any], datetime]:
    raw = args.get("at")
    if not isinstance(raw, str):
        raise ValueError("at must be an ISO datetime")
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        raise ValueError("at must be an ISO datetime") from None
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("at needs an explicit UTC offset")
    if not now < at <= now + MAX_REMINDER_AHEAD:
        raise ValueError("at must be in the future and within a year")
    text = _label(args, "text", 200, required=True)
    return {"at": at.isoformat(), "text": text}, at


def _duration(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{v} {unit}" for v, unit in ((hours, "h"), (minutes, "min"), (secs, "s")) if v]
    return " ".join(parts)


def _labelled(label: str) -> str:
    return f" labelled “{label}”" if label else ""


def register_phone_tools(registry: ToolRegistry, queue: CommandQueue, clock: Clock) -> None:
    def alarm_preview(args: dict[str, Any]) -> str:
        p = _alarm(args)
        days = p.get("days")
        repeat = f", repeating {', '.join(_DAY_NAMES[d - 1] for d in days)}" if days else ""
        return (
            f"Set an alarm on your phone for {p['hour']:02d}:{p['minute']:02d}"
            f"{repeat}{_labelled(p['label'])}."
        )

    def alarm_run(args: dict[str, Any]) -> Any:
        return {"command_id": queue.enqueue("set_alarm", _alarm(args), clock() + ALARM_TTL)}

    def timer_preview(args: dict[str, Any]) -> str:
        p = _timer(args)
        return f"Start a {_duration(p['seconds'])} timer on your phone{_labelled(p['label'])}."

    def timer_run(args: dict[str, Any]) -> Any:
        p = _timer(args)
        # A timer that reaches the phone after it would have rung is pointless.
        return {
            "command_id": queue.enqueue("set_timer", p, clock() + timedelta(seconds=p["seconds"]))
        }

    def reminder_preview(args: dict[str, Any]) -> str:
        p, _at = _reminder(args, clock())
        return f"Remind you on your phone at {p['at']}:\n{p['text']}"

    def reminder_run(args: dict[str, Any]) -> Any:
        p, at = _reminder(args, clock())
        return {"command_id": queue.enqueue("reminder", p, at)}

    label_prop = {"type": "string", "maxLength": 60}
    for name, description, properties, required, run, preview in (
        (
            "phone_set_alarm",
            "Set a clock alarm on the owner's phone (requires approval). hour is 0-23 local time; "
            "days optionally repeats it on weekdays, 1 = Sunday ... 7 = Saturday. For a "
            "reminder with text use phone_reminder instead.",
            {
                "hour": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 23,
                    "description": "Hour in 24-hour local time (6:30 pm is 18).",
                },
                "minute": {"type": "integer", "minimum": 0, "maximum": 59},
                "label": label_prop,
                "days": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 7},
                    "maxItems": 7,
                },
            },
            ["hour", "minute"],
            alarm_run,
            alarm_preview,
        ),
        (
            "phone_set_timer",
            "Start a countdown timer on the owner's phone (requires approval).",
            {
                "seconds": {"type": "integer", "minimum": 1, "maximum": MAX_TIMER_SECONDS},
                "label": label_prop,
            },
            ["seconds"],
            timer_run,
            timer_preview,
        ),
        (
            "phone_reminder",
            "Schedule a one-off reminder notification on the owner's phone (requires approval). "
            "Use it for 'remind me ... to ...' requests, including reminders about a date found "
            "in mail or Classroom, e.g. the evening before an exam. Not for alarms or timers.",
            {
                "at": {
                    "type": "string",
                    "description": (
                        "When the reminder fires: ISO 8601 datetime with the owner's UTC offset, "
                        "such as 2026-10-13T18:00:00+05:30. If the owner gave a time with an "
                        "offset, copy it unchanged; for 'tomorrow 9am' work from the current "
                        "date and time. It must be in the future."
                    ),
                },
                "text": {
                    "type": "string",
                    "maxLength": 200,
                    "description": (
                        "What to remind about, as a short imperative such as Submit the lab "
                        "record. Leave the time out of it."
                    ),
                },
            },
            ["at", "text"],
            reminder_run,
            reminder_preview,
        ),
    ):
        registry.register(
            Tool(
                name=name,
                description=description,
                parameters={
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
                kind=ToolKind.WRITE,
                run=run,
                preview=preview,
                untrusted_output=False,
            )
        )

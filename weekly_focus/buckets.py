"""Due / start date -> Today / Tomorrow / This week / nothing.

All comparisons are on calendar dates in the configured timezone, not on 24-hour spans.
"""
from datetime import date, datetime
from enum import Enum

WINDOW_DAYS = 7  # "This week" runs up to today + 7 days, weekends included


class Bucket(Enum):
    TODAY = "today"
    TOMORROW = "tomorrow"
    THIS_WEEK = "this_week"


def local_date(value, tz):
    """Trello date string ('2026-10-01T21:21:00.000Z' or '2026-10-01') -> local date."""
    if not value:
        return None
    if len(value) == 10:
        return date.fromisoformat(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(tz).date()


def bucket_for(due, start, today):
    """The due date decides when it falls in the window; otherwise a start date on or before
    today + 7 puts the card in This week. A start date never gives Today or Tomorrow."""
    if due is not None:
        days = (due - today).days
        if days <= 0:
            return Bucket.TODAY
        if days == 1:
            return Bucket.TOMORROW
        if days <= WINDOW_DAYS:
            return Bucket.THIS_WEEK
    if start is not None and (start - today).days <= WINDOW_DAYS:
        return Bucket.THIS_WEEK
    return None

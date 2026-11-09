from datetime import date
from zoneinfo import ZoneInfo

import pytest

from weekly_focus.buckets import Bucket, bucket_for, local_date

PARIS = ZoneInfo("Europe/Paris")
WED = date(2026, 9, 30)


def d(day, month=10):
    return date(2026, month, day)


@pytest.mark.parametrize("due, expected", [
    (date(2026, 9, 1), Bucket.TODAY),  # long overdue
    (date(2026, 9, 29), Bucket.TODAY),  # yesterday
    (WED, Bucket.TODAY),
    (d(1), Bucket.TOMORROW),  # Thursday
    (d(2), Bucket.THIS_WEEK),  # Friday
    (d(4), Bucket.THIS_WEEK),  # Sunday: weekends included
    (d(7), Bucket.THIS_WEEK),  # next Wednesday = today + 7, included
    (d(8), None),  # today + 8
])
def test_due_date(due, expected):
    assert bucket_for(due, None, WED) is expected


def test_no_dates():
    assert bucket_for(None, None, WED) is None


def test_window_on_a_sunday():
    sunday = d(4)
    assert bucket_for(d(5), None, sunday) is Bucket.TOMORROW
    assert bucket_for(d(11), None, sunday) is Bucket.THIS_WEEK
    assert bucket_for(d(12), None, sunday) is None


@pytest.mark.parametrize("start", [WED, date(2026, 9, 1), d(1), d(7)])
def test_start_within_window_gives_this_week(start):
    assert bucket_for(d(30), start, WED) is Bucket.THIS_WEEK  # due far away
    assert bucket_for(None, start, WED) is Bucket.THIS_WEEK  # start only


def test_start_never_gives_today_or_tomorrow():
    assert bucket_for(None, WED, WED) is Bucket.THIS_WEEK
    assert bucket_for(None, d(1), WED) is Bucket.THIS_WEEK


def test_start_too_far():
    assert bucket_for(d(30), d(8), WED) is None


def test_due_wins_over_start():
    assert bucket_for(d(1), date(2026, 9, 1), WED) is Bucket.TOMORROW
    assert bucket_for(WED, date(2026, 9, 1), WED) is Bucket.TODAY


@pytest.mark.parametrize("value, expected", [
    (None, None),
    ("", None),
    ("2026-10-01", d(1)),  # date only
    ("2026-10-01T21:21:00.000Z", d(1)),  # 23:21 in Paris (CEST)
    ("2026-09-30T22:30:00.000Z", d(1)),  # 00:30 Paris: already tomorrow
    ("2026-09-30T21:59:00.000Z", WED),  # 23:59 Paris
    # DST ends on Sunday 2026-10-25 at 03:00 CEST -> 02:00 CET
    ("2026-10-24T22:30:00.000Z", d(25)),  # CEST: 00:30 on the 25th
    ("2026-10-25T22:30:00.000Z", d(25)),  # CET: 23:30 on the 25th
    ("2026-10-25T23:30:00.000Z", d(26)),  # CET: 00:30 on the 26th
    # DST starts on Sunday 2026-03-29 at 02:00 CET -> 03:00 CEST
    ("2026-03-28T23:30:00.000Z", date(2026, 3, 29)),  # CET: 00:30
    ("2026-03-29T22:30:00.000Z", date(2026, 3, 30)),  # CEST: 00:30
])
def test_local_date(value, expected):
    assert local_date(value, PARIS) == expected

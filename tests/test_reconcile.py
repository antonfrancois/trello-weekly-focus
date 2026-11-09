from datetime import date, timedelta

from weekly_focus.reconcile import hidden_sources, plan
from weekly_focus.snapshot import FocusCard, Snapshot, SourceCard

TODAY = date(2026, 9, 30)  # a Wednesday
LISTS = {"doing": "L-doing", "today": "L-today", "tomorrow": "L-tomorrow",
         "this_week": "L-week", "done": "L-done"}


def src(sid, days=None, start=None, complete=False, closed=False, eligible=True, hour=10):
    due = TODAY + timedelta(days=days) if days is not None else None
    return SourceCard(
        id=sid, name=f"card {sid}", board="Misc.", short_url=f"https://trello.com/c/{sid}",
        due=due, due_at=f"{due}T{hour:02}:00:00.000Z" if due else None,
        start=TODAY + timedelta(days=start) if start is not None else None,
        complete=complete, closed=closed, eligible=eligible)


def mirror(cid, sid, role, pos=1):
    return FocusCard(cid, f"https://trello.com/c/{sid}", LISTS.get(role, role), pos, sid)


def handmade(cid, role, pos=1, complete=False):
    return FocusCard(cid, f"hand-made {cid}", LISTS[role], pos, complete=complete)


def snap(sources=(), cards=(), archived=()):
    return Snapshot(dict(LISTS), list(cards), frozenset(archived),
                    {s.id: s for s in sources}, ["Misc."])


def kinds(actions):
    return [(a.kind, a.list_role, (a.source.id if a.source else a.card.id)) for a in actions
            if a.kind != "sort"]


# --- create / move / leave

def test_creates_mirror_in_bucket():
    actions = plan(snap([src("a", 0), src("b", 1), src("c", 5), src("d", 8), src("e")]), TODAY)
    assert kinds(actions) == [("create", "today", "a"), ("create", "tomorrow", "b"),
                              ("create", "this_week", "c")]


def test_start_date_creates_in_this_week():
    actions = plan(snap([src("a", days=20, start=0), src("b", start=-3)]), TODAY)
    assert kinds(actions) == [("create", "this_week", "a"), ("create", "this_week", "b")]


def test_up_to_date_board_needs_nothing():
    s = snap([src("a", 0), src("b", 1)], [mirror("m1", "a", "today"), mirror("m2", "b", "tomorrow")])
    assert plan(s, TODAY) == []


def test_moves_mirror_to_new_bucket():
    s = snap([src("a", 0)], [mirror("m1", "a", "tomorrow")])
    [move] = plan(s, TODAY)
    assert (move.kind, move.from_role, move.list_role, move.card.id) == \
        ("move", "tomorrow", "today", "m1")


def test_mirror_in_doing_is_not_touched_by_dates():
    s = snap([src("a", 0), src("b", 30)], [mirror("m1", "a", "doing"), mirror("m2", "b", "doing")])
    assert plan(s, TODAY) == []


def test_mirror_in_unknown_list_is_left_alone():
    s = snap([src("a", 0)], [mirror("m1", "a", "L-someday")])
    assert plan(s, TODAY) == []


def test_handmade_cards_are_ignored():
    s = snap([], [handmade("h1", "today"), handmade("h2", "done")])
    assert plan(s, TODAY) == []


def test_unscanned_source_gets_no_mirror():
    assert plan(snap([src("a", 0, eligible=False)]), TODAY) == []


# --- delete

def test_deletes_mirror_whose_source_left_the_window():
    s = snap([src("a", 8), src("b"), src("d", 0, closed=True), src("e", 0, complete=True,
                                                                   closed=True)],
             [mirror("m1", "a", "this_week"), mirror("m2", "b", "today"),
              mirror("m4", "d", "tomorrow"), mirror("m5", "gone", "today"),
              mirror("m6", "e", "today")])
    actions = plan(s, TODAY)
    assert {a.card.id: a.reason for a in actions} == {
        "m1": "no date in the next 7 days",
        "m2": "no date in the next 7 days",
        "m4": "source archived",
        "m5": "source deleted, archived or on an unscanned board",
        "m6": "source archived",
    }
    assert all(a.kind == "delete" for a in actions)


# --- completed source -> mirror moves to Done

def test_completed_source_moves_its_mirror_to_done():
    s = snap([src("a", 0, complete=True), src("b", 30, complete=True), src("c", complete=True)],
             [mirror("m1", "a", "today"), mirror("m2", "b", "this_week"),
              mirror("m3", "c", "doing")])
    actions = plan(s, TODAY)
    assert [(a.kind, a.from_role, a.list_role, a.card.id) for a in actions] == [
        ("move", "today", "done", "m1"),
        ("move", "this_week", "done", "m2"),
        ("move", "doing", "done", "m3"),
    ]


def test_completed_source_already_in_done_drops_the_duplicate():
    s = snap([src("a", 0, complete=True)],
             [mirror("m1", "a", "done", 1), mirror("m2", "a", "today", 2)])
    [delete] = plan(s, TODAY)
    assert (delete.kind, delete.card.id, delete.reason) == ("delete", "m2", "duplicate mirror")


def test_completed_handmade_card_moves_to_done():
    s = snap([], [handmade("h1", "today", complete=True), handmade("h2", "doing", complete=True),
                  handmade("h3", "tomorrow"), handmade("h4", "done", complete=True),
                  FocusCard("h5", "x", "L-someday", 1, complete=True)])
    actions = plan(s, TODAY)
    assert [(a.kind, a.from_role, a.list_role, a.card.id, a.reason) for a in actions] == [
        ("move", "today", "done", "h1", "card completed"),
        ("move", "doing", "done", "h2", "card completed"),
    ]


def test_completed_source_without_mirror_gets_none():
    assert plan(snap([src("a", 0, complete=True)]), TODAY) == []


def test_completed_source_in_unknown_list_is_left_alone():
    s = snap([src("a", 0, complete=True)], [mirror("m1", "a", "L-someday")])
    assert plan(s, TODAY) == []


def test_completed_then_daily_clear_next_night():
    s = snap([src("a", 0, complete=True)], [mirror("m1", "a", "done")])
    actions = plan(s, TODAY, clear_done=True)
    assert [(a.kind, a.card.id) for a in actions] == [("archive_source", "m1"), ("delete", "m1")]


def test_duplicates_in_managed_lists_keep_the_right_one():
    s = snap([src("a", 1)], [mirror("m1", "a", "today"), mirror("m2", "a", "tomorrow")])
    [delete] = plan(s, TODAY)
    assert (delete.kind, delete.card.id, delete.reason) == ("delete", "m1", "duplicate mirror")


def test_duplicate_next_to_a_doing_mirror_is_deleted():
    s = snap([src("a", 0)], [mirror("m1", "a", "doing"), mirror("m2", "a", "today")])
    [delete] = plan(s, TODAY)
    assert (delete.kind, delete.card.id) == ("delete", "m2")


# --- archived mirrors (Q6)

def test_archived_mirror_hides_its_source():
    s = snap([src("a", 0), src("b", 0)], archived={"a"})
    assert kinds(plan(s, TODAY)) == [("create", "today", "b")]
    assert [x.id for x in hidden_sources(s, TODAY)] == ["a"]


def test_archived_mirror_does_not_block_an_open_one():
    s = snap([src("a", 0)], [mirror("m1", "a", "tomorrow")], archived={"a"})
    assert kinds(plan(s, TODAY)) == [("move", "today", "a")]
    assert hidden_sources(s, TODAY) == []


# --- Done

def test_done_completes_the_source_every_run():
    s = snap([src("a", 0), src("b", 0, complete=True)],
             [mirror("m1", "a", "done"), mirror("m2", "b", "done")])
    assert kinds(plan(s, TODAY)) == [("complete_source", "done", "a")]


def test_daily_clear():
    s = snap([src("a", 0), src("b", 0, complete=True), src("c", 0, closed=True)],
             [mirror("m1", "a", "done", 1), mirror("m2", "b", "done", 2),
              mirror("m3", "c", "done", 3), mirror("m4", "missing", "done", 4),
              handmade("h1", "done", 5), handmade("h2", "today", 6)])
    actions = plan(s, TODAY, clear_done=True)
    assert [(a.kind, a.card.id) for a in actions] == [
        ("complete_source", "m1"), ("archive_source", "m1"), ("delete", "m1"),
        ("archive_source", "m2"), ("delete", "m2"),
        ("delete", "m3"),  # source already archived
        ("delete", "m4"),  # source gone
        ("archive_card", "h1"),  # hand-made: archived, never deleted
    ]


def test_no_clear_without_flag():
    s = snap([src("a", 0, complete=True)], [mirror("m1", "a", "done"), handmade("h1", "done")])
    assert plan(s, TODAY) == []


# --- Today ordering

def test_today_sorted_oldest_due_first():
    s = snap([src("a", 0), src("b", -3), src("c", -1)],
             [mirror("m1", "a", "today", 1), mirror("m2", "b", "today", 2),
              mirror("m3", "c", "today", 3)])
    [sort] = plan(s, TODAY)
    assert (sort.kind, sort.order) == ("sort", ("b", "c", "a"))


def test_today_already_sorted():
    s = snap([src("a", 0), src("b", -3)],
             [mirror("m1", "b", "today", 1), mirror("m2", "a", "today", 2)])
    assert plan(s, TODAY) == []


def test_same_day_sorted_by_time():
    s = snap([src("a", 0, hour=15), src("b", 0, hour=8)],
             [mirror("m1", "a", "today", 1), mirror("m2", "b", "today", 2)])
    assert plan(s, TODAY)[-1].order == ("b", "a")


def test_new_overdue_card_triggers_sort():
    s = snap([src("a", 0), src("b", -2)], [mirror("m1", "a", "today")])
    actions = plan(s, TODAY)
    assert kinds(actions) == [("create", "today", "b")]
    assert actions[-1].order == ("b", "a")


def test_new_cards_arriving_in_order_need_no_sort():
    s = snap([src("a", -2), src("b", 0), src("c", 0, hour=12)],
             [mirror("m1", "a", "today"), mirror("m2", "b", "tomorrow")])
    actions = plan(s, TODAY)
    assert kinds(actions) == [("move", "today", "b"), ("create", "today", "c")]
    assert all(a.kind != "sort" for a in actions)

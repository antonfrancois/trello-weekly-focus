from weekly_focus.apply import apply_actions
from weekly_focus.client import TrelloError
from weekly_focus.reconcile import Action
from weekly_focus.snapshot import FocusCard, Snapshot, SourceCard

LISTS = {"doing": "L-doing", "today": "L-today", "tomorrow": "L-tomorrow",
         "this_week": "L-week", "done": "L-done"}
SRC = SourceCard("s1", "card", "Misc.", "https://trello.com/c/s1", None, None, None, False, False)
CARD = FocusCard("m1", "https://trello.com/c/s1", "L-tomorrow", 1, "s1")


class FakeClient:
    def __init__(self, list_cards=(), fail_on=()):
        self.calls, self._list_cards, self.fail_on = [], list(list_cards), set(fail_on)

    def _record(self, *call):
        self.calls.append(call)
        if call[0] in self.fail_on:
            raise TrelloError("X", "/x", 500, "boom")

    def create_mirror(self, list_id, url, pos):
        self._record("create", list_id, url, pos)

    def update_card(self, card_id, **fields):
        self._record("update", card_id, fields)

    def delete_card(self, card_id):
        self._record("delete", card_id)

    def list_cards(self, list_id, fields):
        return self._list_cards


def run(client, *actions):
    snap = Snapshot(dict(LISTS), [], frozenset(), {}, [])
    return apply_actions(client, snap, list(actions), describe=lambda a: a.kind)


def test_each_action_maps_to_one_call():
    c = FakeClient()
    run(c,
        Action("create", "today", source=SRC),
        Action("move", "today", "tomorrow", card=CARD, source=SRC),
        Action("delete", "tomorrow", card=CARD, source=SRC),
        Action("complete_source", "done", card=CARD, source=SRC),
        Action("archive_source", "done", card=CARD, source=SRC),
        Action("archive_card", "done", card=CARD))
    assert c.calls == [
        ("create", "L-today", "https://trello.com/c/s1", "bottom"),
        ("update", "m1", {"idList": "L-today", "pos": "bottom"}),
        ("delete", "m1"),
        ("update", "s1", {"dueComplete": True}),
        ("update", "s1", {"closed": True}),
        ("update", "m1", {"closed": True}),
    ]


def test_a_failure_does_not_stop_the_run():
    c = FakeClient(fail_on={"delete"})
    failures = run(c, Action("delete", "today", card=CARD), Action("create", "today", source=SRC))
    assert failures == 1
    assert [call[0] for call in c.calls] == ["delete", "create"]


def mirror(cid, sid, pos):
    return {"id": cid, "pos": pos, "cardRole": "mirror", "mirrorSourceId": sid}


def test_sort_reuses_mirror_slots_and_skips_hand_made_cards():
    cards = [mirror("m-a", "a", 100), {"id": "h", "pos": 150, "cardRole": None},
             mirror("m-b", "b", 200), mirror("m-c", "c", 300)]
    c = FakeClient(list_cards=cards)
    run(c, Action("sort", "today", order=("c", "a", "b")))
    assert c.calls == [("update", "m-c", {"pos": 100.0}),
                       ("update", "m-a", {"pos": 200.0}),
                       ("update", "m-b", {"pos": 300.0})]


def test_sort_only_moves_cards_out_of_place():
    cards = [mirror("m-a", "a", 100), mirror("m-c", "c", 200), mirror("m-b", "b", 300)]
    c = FakeClient(list_cards=cards)
    run(c, Action("sort", "today", order=("a", "b", "c")))
    assert c.calls == [("update", "m-b", {"pos": 200.0}), ("update", "m-c", {"pos": 300.0})]


def test_sort_ignores_mirrors_that_failed_to_be_created():
    c = FakeClient(list_cards=[mirror("m-b", "b", 100)])
    run(c, Action("sort", "today", order=("a", "b")))
    assert c.calls == []

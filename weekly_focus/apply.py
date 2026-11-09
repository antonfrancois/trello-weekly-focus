"""Carry out the reconciler's actions on Trello. One failed action never stops the others."""
import logging

from .client import TrelloError

log = logging.getLogger("weekly_focus")


def apply_actions(client, snapshot, actions, describe):
    """Returns the number of failed actions."""
    failures = 0
    for action in actions:
        try:
            _apply(client, snapshot, action)
            log.info("done    %s", describe(action))
        except TrelloError as e:
            failures += 1
            log.error("FAILED  %s: %s", describe(action), e)
    return failures


def _apply(client, snapshot, a):
    list_id = snapshot.list_ids.get(a.list_role)
    if a.kind == "create":
        client.create_mirror(list_id, a.source.short_url, pos="bottom")
    elif a.kind == "move":
        client.update_card(a.card.id, idList=list_id, pos="bottom")
    elif a.kind == "delete":
        client.delete_card(a.card.id)
    elif a.kind == "complete_source":
        client.update_card(a.source.id, dueComplete=True)
    elif a.kind == "archive_source":
        client.update_card(a.source.id, closed=True)
    elif a.kind == "archive_card":
        client.update_card(a.card.id, closed=True)
    elif a.kind == "sort":
        _sort_list(client, list_id, a.order)
    else:
        raise ValueError(f"unknown action {a.kind!r}")


def _sort_list(client, list_id, order):
    """Reorder the mirrors of a list among the positions they already occupy, so hand-made
    cards keep their place. Only cards whose position changes are updated."""
    cards = client.list_cards(list_id, "pos,cardRole,mirrorSourceId")
    mirrors = {c["mirrorSourceId"]: c for c in cards if c.get("cardRole") == "mirror"}
    wanted = [mirrors[sid] for sid in order if sid in mirrors]
    slots = sorted(float(c["pos"]) for c in wanted)
    for card, pos in zip(wanted, slots):
        if float(card["pos"]) != pos:
            client.update_card(card["id"], pos=pos)

"""Desired state vs actual state -> list of actions. Pure: no API calls here."""
from collections import defaultdict
from dataclasses import dataclass

from .buckets import Bucket, bucket_for
from .snapshot import FocusCard, SourceCard

MANAGED = tuple(b.value for b in Bucket)  # the lists the reconciler fills and empties


@dataclass(frozen=True)
class Action:
    kind: str  # create | move | delete | complete_source | archive_source | archive_card | sort
    list_role: str | None = None  # target list (create, move, sort), else the card's list
    from_role: str | None = None  # move only
    card: FocusCard | None = None  # card on the master board
    source: SourceCard | None = None
    reason: str = ""
    order: tuple = ()  # sort only: source ids in the wanted order


def sort_key(source):
    """Oldest due first (overdue before due today), then by name."""
    return (source.due_at or "9999", source.name.casefold())


def desired_buckets(snapshot, today):
    """Source card id -> bucket, for every source that belongs on the master board."""
    desired = {}
    for s in snapshot.sources.values():
        if s.eligible and not s.closed and not s.complete:
            bucket = bucket_for(s.due, s.start, today)
            if bucket is not None:
                desired[s.id] = bucket
    return desired


def hidden_sources(snapshot, today):
    """Sources that would get a mirror, but the user archived theirs."""
    mirrored = {c.source_id for c in snapshot.cards if c.is_mirror}
    return [snapshot.sources[sid] for sid in desired_buckets(snapshot, today)
            if sid not in mirrored and sid in snapshot.archived_mirror_sources]


def _why_removed(source):
    if source is None:
        return "source deleted, archived or on an unscanned board"
    if source.closed:
        return "source archived"
    if source.complete:
        return "source completed"
    if not source.eligible:
        return "source board not scanned"
    return "no date in the next 7 days"


def plan(snapshot, today, clear_done=False):
    roles = {list_id: role for role, list_id in snapshot.list_ids.items()}
    sources = snapshot.sources
    desired = desired_buckets(snapshot, today)
    cards = sorted(snapshot.cards, key=lambda c: c.pos)
    actions = []

    mirrors = defaultdict(list)
    for card in cards:
        if card.is_mirror:
            mirrors[card.source_id].append(card)

    # 1. Done: complete the source (every run); daily clear (midnight run only).
    for card in cards:
        if roles.get(card.list_id) != "done":
            continue
        if card.is_mirror:
            src = sources.get(card.source_id)
            if src and not src.closed and not src.complete:
                actions.append(Action("complete_source", "done", card=card, source=src))
            if clear_done:
                if src and not src.closed:
                    actions.append(Action("archive_source", "done", card=card, source=src))
                actions.append(Action("delete", "done", card=card, source=src,
                                      reason="daily clear"))
        elif clear_done:
            actions.append(Action("archive_card", "done", card=card, reason="daily clear"))

    # 2. Every source with a bucket: create, move, or leave its mirror.
    for sid, bucket in sorted(desired.items(), key=lambda kv: sort_key(sources[kv[0]])):
        src, own = sources[sid], mirrors.get(sid, [])
        if not own:
            if sid not in snapshot.archived_mirror_sources:
                actions.append(Action("create", bucket.value, source=src))
            continue
        managed = [c for c in own if roles.get(c.list_id) in MANAGED]
        if len(managed) < len(own):
            extras = managed  # the user moved it to Doing / Done: never touch that one
        else:
            keep = next((c for c in managed if roles[c.list_id] == bucket.value), managed[0])
            if roles[keep.list_id] != bucket.value:
                actions.append(Action("move", bucket.value, roles[keep.list_id], card=keep,
                                      source=src))
            extras = [c for c in managed if c is not keep]
        for card in extras:
            actions.append(Action("delete", roles[card.list_id], card=card, source=src,
                                  reason="duplicate mirror"))

    # 3. Completed cards go to Done (from a managed list or Doing): hand-made cards ticked
    #    complete, and mirrors whose source is complete. Other mirrors whose source no
    #    longer belongs here are deleted from the managed lists.
    in_done = {c.source_id for c in cards if c.is_mirror and roles.get(c.list_id) == "done"}
    for card in cards:
        role = roles.get(card.list_id)
        if not card.is_mirror:
            if card.complete and role in MANAGED + ("doing",):
                actions.append(Action("move", "done", role, card=card, reason="card completed"))
            continue
        if card.source_id in desired:
            continue
        src = sources.get(card.source_id)
        if src and src.complete and not src.closed and role in MANAGED + ("doing",):
            if card.source_id in in_done:
                actions.append(Action("delete", role, card=card, source=src,
                                      reason="duplicate mirror"))
            else:
                actions.append(Action("move", "done", role, card=card, source=src,
                                      reason="source completed"))
                in_done.add(card.source_id)
        elif role in MANAGED:
            actions.append(Action("delete", role, card=card, source=src,
                                  reason=_why_removed(src)))

    # 4. Today: overdue first, then due today. Only when the resulting order is wrong.
    sort = _sort_today(cards, actions, snapshot)
    if sort:
        actions.append(sort)
    return actions


def _sort_today(cards, actions, snapshot):
    """New and moved mirrors land at the bottom; sort only if that order is wrong."""
    today_id = snapshot.list_ids["today"]
    leaving = {a.card.id for a in actions if a.kind in ("move", "delete") and a.card}
    staying = [c.source_id for c in cards
               if c.list_id == today_id and c.is_mirror and c.id not in leaving]
    arriving = [a.source.id for a in actions
                if a.kind in ("create", "move") and a.list_role == "today"]
    sequence = staying + arriving
    wanted = sorted(sequence, key=lambda sid: sort_key(snapshot.sources[sid]))
    if sequence != wanted:
        return Action("sort", "today", order=tuple(wanted))
    return None

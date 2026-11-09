"""Read the current state of Trello into plain data (the reconciler's input)."""
from dataclasses import dataclass, field
from datetime import date

from .buckets import local_date
from .client import FOCUS_CARD_FIELDS, SOURCE_CARD_FIELDS
from .config import normalize


class SnapshotError(Exception):
    pass


@dataclass(frozen=True)
class SourceCard:
    id: str
    name: str
    board: str
    short_url: str
    due: date | None
    due_at: str | None  # raw ISO timestamp, used to sort cards due the same day
    start: date | None
    complete: bool
    closed: bool
    eligible: bool = True  # False if not found by scanning the source boards


@dataclass(frozen=True)
class FocusCard:
    id: str
    name: str
    list_id: str
    pos: float
    source_id: str | None = None  # set for native mirrors only
    complete: bool = False  # the card's own due checkbox (meaningful for hand-made cards)

    @property
    def is_mirror(self):
        return self.source_id is not None


@dataclass
class Snapshot:
    list_ids: dict  # role -> list id on the master board
    cards: list  # open FocusCards on the master board
    archived_mirror_sources: frozenset  # sources hidden by an archived mirror
    sources: dict  # source card id -> SourceCard
    boards_scanned: list = field(default_factory=list)


def _focus_card(c):
    source_id = c.get("mirrorSourceId") if c.get("cardRole") == "mirror" else None
    return FocusCard(c["id"], c["name"], c["idList"], float(c.get("pos") or 0), source_id,
                     bool(c.get("dueComplete")))


def _source_card(c, board_name, tz, eligible):
    return SourceCard(
        id=c["id"], name=c["name"], board=board_name, short_url=c["shortUrl"],
        due=local_date(c.get("due"), tz), due_at=c.get("due"),
        start=local_date(c.get("start"), tz),
        complete=bool(c.get("dueComplete")), closed=bool(c.get("closed")),
        eligible=eligible,
    )


def fetch_snapshot(client, config):
    tz = config.timezone
    boards = client.open_boards()
    board_names = {b["id"]: b["name"] for b in boards}

    focus = next((b for b in boards if normalize(b["name"]) == normalize(config.board)), None)
    if not focus:
        raise SnapshotError(f"No open board named {config.board!r}.")

    lists = {normalize(l["name"]): l["id"] for l in client.board_lists(focus["id"])}
    list_ids = {}
    for role, name in config.lists.items():
        if normalize(name) not in lists:
            raise SnapshotError(f"List {name!r} ({role}) not found on {config.board!r}.")
        list_ids[role] = lists[normalize(name)]

    cards = [_focus_card(c) for c in client.board_cards(focus["id"], FOCUS_CARD_FIELDS)]
    archived = frozenset(
        c["mirrorSourceId"] for c in client.board_cards(focus["id"], FOCUS_CARD_FIELDS, "closed")
        if c.get("cardRole") == "mirror" and c.get("mirrorSourceId"))

    include = {normalize(n) for n in config.include_boards}
    exclude = {normalize(n) for n in config.exclude_boards}
    sources, scanned = {}, []
    for b in boards:
        name = normalize(b["name"])
        if b["id"] == focus["id"] or name in exclude or (include and name not in include):
            continue
        scanned.append(b["name"])
        for c in client.board_cards(b["id"], SOURCE_CARD_FIELDS):
            if c.get("cardRole"):  # mirrors, link cards, separators: not real tasks
                continue
            sources[c["id"]] = _source_card(c, b["name"], tz, eligible=True)

    # Mirrors in Done need their source even when it was not scanned (archived source,
    # excluded board): the reconciler completes / archives it.
    for card in cards:
        if card.list_id == list_ids["done"] and card.is_mirror and card.source_id not in sources:
            c = client.card(card.source_id, SOURCE_CARD_FIELDS)
            if c:
                sources[c["id"]] = _source_card(c, board_names.get(c["idBoard"], "?"), tz,
                                                eligible=False)

    return Snapshot(list_ids, cards, archived, sources, scanned)

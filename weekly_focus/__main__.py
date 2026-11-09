"""CLI: python -m weekly_focus [--dry-run] [--verbose] [--clear-done] [--today YYYY-MM-DD]"""
import argparse
import fcntl
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from .apply import apply_actions
from .client import TrelloClient, TrelloError
from .config import ConfigError, credentials, load_config, load_dotenv
from .buckets import Bucket
from .reconcile import desired_buckets, hidden_sources, plan, sort_key
from .snapshot import SnapshotError, fetch_snapshot

ROOT = Path(__file__).resolve().parent.parent


def _date(d):
    return d.strftime("%a %d/%m") if d else "-"


def _source_label(src):
    if src is None:
        return "(unknown source)"
    dates = f"due {_date(src.due)}"
    if src.start:
        dates += f", start {_date(src.start)}"
    return f"{src.name!r}  [{src.board}, {dates}]"


def describe(action, list_names, sources):
    name = lambda role: list_names.get(role, role)
    k = action.kind
    if k == "create":
        return f"create    {name(action.list_role):10} {_source_label(action.source)}"
    if k == "move":
        where = f"{name(action.from_role)} -> {name(action.list_role)}"
        what = _source_label(action.source) if action.source else \
            f"{action.card.name!r}  (hand-made card)"
        return f"move      {where:10} {what}"
    if k == "delete":
        return (f"delete    {name(action.list_role):10} {_source_label(action.source)}"
                f"  ({action.reason})")
    if k == "complete_source":
        return f"complete  {'source':10} {_source_label(action.source)}"
    if k == "archive_source":
        return f"archive   {'source':10} {_source_label(action.source)}"
    if k == "archive_card":
        return f"archive   {name(action.list_role):10} {action.card.name!r}  (hand-made card)"
    if k == "sort":
        order = ", ".join(repr(sources[sid].name) for sid in action.order)
        return f"sort      {name(action.list_role):10} {order}"
    return repr(action)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="weekly_focus", description=__doc__)
    ap.add_argument("--config", default=ROOT / "config.toml", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="print planned actions, change nothing")
    ap.add_argument("--verbose", action="store_true", help="also list the desired state")
    ap.add_argument("--clear-done", action="store_true", help="daily clear of the Done list")
    ap.add_argument("--today", type=date.fromisoformat,
                    help="pretend today is this date (YYYY-MM-DD); dry runs only")
    args = ap.parse_args(argv)
    if args.today and not args.dry_run:
        ap.error("--today is only allowed with --dry-run")
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    # One run at a time: the midnight run waits for a regular run still in progress.
    lock = open(ROOT / ".weekly_focus.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)

    try:
        config = load_config(args.config)
        load_dotenv(ROOT / ".env")
        client = TrelloClient(*credentials())
        snapshot = fetch_snapshot(client, config)
    except (ConfigError, SnapshotError, TrelloError) as e:
        sys.exit(f"error: {e}")

    now = datetime.now(config.timezone)
    today = args.today or now.date()
    actions = plan(snapshot, today, clear_done=args.clear_done)
    sources = snapshot.sources
    mode = "DRY RUN" if args.dry_run else "LIVE"

    print(f"Weekly focus - {mode} - {now:%Y-%m-%d %H:%M} {config.timezone.key}, "
          f"today = {today:%a %Y-%m-%d}{'  [--clear-done]' if args.clear_done else ''}")
    print(f"Scanned {len(snapshot.boards_scanned)} boards: {', '.join(snapshot.boards_scanned)}")
    desired = desired_buckets(snapshot, today)
    print(f"{len(desired)} source card(s) belong on {config.board!r}; "
          f"{sum(c.is_mirror for c in snapshot.cards)} open mirror(s) there now.")

    hidden = hidden_sources(snapshot, today)
    if hidden:
        print(f"{len(hidden)} card(s) hidden by an archived mirror (left alone):")
        for src in hidden:
            print(f"    {_source_label(src)}")

    if args.verbose:
        print("\nDesired state:")
        order = list(Bucket)
        for sid, bucket in sorted(desired.items(),
                                  key=lambda kv: (order.index(kv[1]), sort_key(sources[kv[0]]))):
            print(f"    {config.lists[bucket.value]:10} {_source_label(sources[sid])}")

    say = lambda action: describe(action, config.lists, sources)
    if not actions:
        print("Nothing to do: Weekly focus is up to date.")
        return
    if args.dry_run:
        print(f"\nPlanned actions ({len(actions)}):")
        for action in actions:
            print("    " + say(action))
        print("\nDry run: nothing was changed.")
        return

    print(f"\nApplying {len(actions)} action(s):")
    failures = apply_actions(client, snapshot, actions, say)
    if failures:
        sys.exit(f"{failures} of {len(actions)} action(s) failed.")
    print("All actions applied.")


if __name__ == "__main__":
    main()

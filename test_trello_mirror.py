#!/usr/bin/env python3
"""
Phase 0 feasibility test: can the Trello REST API create, move, find and remove
NATIVE mirror cards?

Setup:
    pip install requests
    cp .env.example .env      # then fill in TRELLO_KEY and TRELLO_TOKEN
    # (or export TRELLO_KEY / TRELLO_TOKEN in the shell)

Usage:
    python test_trello_mirror.py <source card URL or shortLink> [--board "Weekly focus"]
                                 [--today-list Today] [--tomorrow-list Tomorrow]
                                 [--keep] [--yes]

Use a THROWAWAY source card that has a due date. The script:
    A. creates a mirror of it in "Today"
    B. moves the mirror to "Tomorrow" and checks it is still a mirror
    C. lists the board's cards and checks the mirror is discoverable
    D. deletes the mirror and checks the source card survived (skipped with --keep)

The mirror is always cleaned up (unless --keep), even if a test fails.
"""
import argparse
import os
import re
import sys
from pathlib import Path

import requests

API = "https://api.trello.com/1"
CARD_FIELDS = "name,idList,idBoard,cardRole,mirrorSourceId,due,dueComplete,shortUrl,closed"


class TrelloError(Exception):
    def __init__(self, status, text):
        super().__init__(f"HTTP {status}: {text}")
        self.status = status


def load_dotenv(path):
    """Minimal .env reader: KEY=value lines, no overriding of existing env vars."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def call(method, path, **params):
    # Credentials in the header, never in the URL: a network error message would show the URL.
    auth = f'OAuth oauth_consumer_key="{os.environ["TRELLO_KEY"]}", oauth_token="{os.environ["TRELLO_TOKEN"]}"'
    try:
        r = requests.request(method, f"{API}{path}", params=params,
                             headers={"Authorization": auth}, timeout=30)
    except requests.RequestException as e:
        raise TrelloError(None, f"network error ({type(e).__name__})") from None
    if not r.ok:
        raise TrelloError(r.status_code, r.text)
    return r.json() if r.text else None


def show(label, card, lists_by_id):
    print(f"  [{label}] id={card['id']}")
    for k in ("name", "cardRole", "mirrorSourceId", "due", "dueComplete", "closed"):
        print(f"      {k:15} = {card.get(k)!r}")
    print(f"      {'list':15} = {lists_by_id.get(card['idList'], card['idList'])!r}")


def main():
    load_dotenv(Path(__file__).with_name(".env"))
    if not (os.environ.get("TRELLO_KEY") and os.environ.get("TRELLO_TOKEN")):
        sys.exit("Set TRELLO_KEY and TRELLO_TOKEN (environment or .env) first.")

    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="source card URL or shortLink")
    ap.add_argument("--board", default="Weekly focus")
    ap.add_argument("--today-list", default="Today")
    ap.add_argument("--tomorrow-list", default="Tomorrow")
    ap.add_argument("--keep", action="store_true", help="leave the mirror in place (skips test D)")
    ap.add_argument("--yes", action="store_true", help="do not ask before deleting the mirror")
    args = ap.parse_args()

    m = re.search(r"trello\.com/c/([A-Za-z0-9]+)", args.source)
    source_id = m.group(1) if m else args.source
    results = {}  # test name -> True / False / None (not run)
    notes = []

    # Setup: source card, target board and lists
    source = call("GET", f"/cards/{source_id}", fields=CARD_FIELDS)
    print(f"Source card: {source['name']!r}  due={source.get('due')!r}  ({source['shortUrl']})")
    if not source.get("due"):
        notes.append("Source card has no due date: 'mirror exposes due' could not be checked.")

    boards = call("GET", "/members/me/boards", fields="name", filter="open")
    board = next((b for b in boards if b["name"].strip().lower() == args.board.lower()), None)
    if not board:
        sys.exit(f"No open board named {args.board!r}. Found: {[b['name'] for b in boards]}")
    if source["idBoard"] == board["id"]:
        sys.exit("The source card must live on a project board, not on the target board.")
    lists = call("GET", f"/boards/{board['id']}/lists", fields="name")
    lists_by_name = {l["name"].strip().lower(): l["id"] for l in lists}
    lists_by_id = {l["id"]: l["name"] for l in lists}
    today, tomorrow = args.today_list.strip().lower(), args.tomorrow_list.strip().lower()
    for needed in (today, tomorrow):
        if needed not in lists_by_name:
            sys.exit(f"List {needed!r} not found on {args.board!r}: {list(lists_by_id.values())}")

    mirror = None
    try:
        # TEST A: create a native mirror
        print("\nTEST A - create mirror in 'Today'")
        created = call("POST", "/cards", idList=lists_by_name[today], name=source["shortUrl"],
                       cardRole="mirror", pos="top")
        mirror = call("GET", f"/cards/{created['id']}", fields=CARD_FIELDS)
        show("mirror", mirror, lists_by_id)
        results["A create mirror"] = mirror.get("cardRole") == "mirror"
        results["A mirrorSourceId == source id"] = mirror.get("mirrorSourceId") == source["id"]
        if source.get("due"):
            exposes_due = mirror.get("due") == source["due"]
            notes.append(f"Mirror exposes source due date: {exposes_due} "
                         f"(mirror due={mirror.get('due')!r}).")

        # TEST B: move it (what the reconciler does every day)
        print("\nTEST B - move mirror to 'Tomorrow'")
        call("PUT", f"/cards/{mirror['id']}", idList=lists_by_name[tomorrow], pos="top")
        moved = call("GET", f"/cards/{mirror['id']}", fields=CARD_FIELDS)
        show("mirror", moved, lists_by_id)
        results["B move keeps mirror"] = (moved["idList"] == lists_by_name[tomorrow]
                                          and moved.get("cardRole") == "mirror"
                                          and moved.get("mirrorSourceId") == source["id"])
        src_after = call("GET", f"/cards/{source['id']}", fields=CARD_FIELDS)
        results["B source untouched by move"] = (src_after["idList"] == source["idList"]
                                                 and src_after.get("due") == source.get("due"))

        # TEST C: discover mirrors on the board (how the reconciler finds its cards)
        print("\nTEST C - list mirrors on the board")
        cards = call("GET", f"/boards/{board['id']}/cards", fields=CARD_FIELDS)
        mirrors = [c for c in cards if c.get("cardRole") == "mirror"]
        print(f"  {len(mirrors)} mirror(s) on the board")
        results["C mirror found via board cards"] = any(
            c["id"] == mirror["id"] and c.get("mirrorSourceId") == source["id"] for c in mirrors)

        print("\nOpen Trello now and check the mirror looks right in 'Tomorrow'.")
    except TrelloError as e:
        print(f"  !! API error: {e}")
        notes.append(f"Stopped on API error: {e}")

    # TEST D / cleanup: delete the mirror, check the source survived
    if mirror and not args.keep:
        if args.yes or input("\nDelete the test mirror? [y/N] ").strip().lower() == "y":
            print("\nTEST D - delete mirror, check source survives")
            try:
                call("DELETE", f"/cards/{mirror['id']}")
                src_final = call("GET", f"/cards/{source['id']}", fields=CARD_FIELDS)
                results["D delete mirror leaves source alive"] = not src_final.get("closed")
            except TrelloError as e:
                print(f"  !! API error: {e}")
                results["D delete mirror leaves source alive"] = False
                notes.append(f"Delete step failed (source may be gone if 404): {e}")
        else:
            print(f"Mirror left in place: id={mirror['id']}")

    # Summary
    print("\n=== Summary ===")
    for name, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    for note in notes:
        print(f"  note: {note}")
    core = [results.get("A create mirror"), results.get("B move keeps mirror")]
    if all(core):
        print("\nPhase 0 core criteria met (A and B pass).")
    else:
        print("\nPhase 0 core criteria NOT met -> consider the plain-card fallback.")
        sys.exit(1)


if __name__ == "__main__":
    main()

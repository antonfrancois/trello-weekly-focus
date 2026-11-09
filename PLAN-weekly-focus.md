# Weekly focus reconciler — overview & plan

## TODO

Code lives in this folder (`01_trello_weekly_focus/`).

### Phase 0 — Feasibility test
- [x] Harden `test_trello_mirror.py` (`.env` loading, always clean up, pass/fail summary)
- [x] Add `.env.example` and `.gitignore`
- [x] Create Trello API key + token, fill in `.env` (token: read+write, no expiry)
- [x] Check Weekly focus has no automation rules that touch cards (removed)
- [x] Create a throwaway card with a due date on a project board (Misc.)
- [x] Run `python test_trello_mirror.py <card URL>` and record results (2026-09-30)
  - [x] A — mirror creation: PASS
  - [x] B — mirror move keeps it a mirror: PASS (source untouched)
  - [x] C — mirror found via `/boards/{id}/cards`: PASS
  - [x] D — deleting the mirror leaves the source alive: PASS
  - [x] Mirror exposes the source `due`: NO (`due` is null on the mirror)
- [x] Decide: native mirrors, or the plain-card fallback → **native mirrors**

### Before Phase 1
- [x] Q1 "This week" = rolling 7 days
- [x] Q2 overdue stays in `Today`, sorted first (no label)
- [x] Q3 start dates count
- [x] Q4 all boards, include/exclude option in config
- [x] Q5 `Done` completes the source; `Done` cleared daily
- [x] Confirm the start-date rule (section 5, Bucketing)
- [x] Q6 archived mirrors are left alone
- [x] Daily clear also archives the source cards of mirrors in `Done`

### Phase 1 — Core logic, dry-run
- [x] Project skeleton + `config.toml` (board/list names, `include_boards` / `exclude_boards`)
- [x] `client.py` (REST wrapper, 429/5xx retry/backoff)
- [x] `buckets.py` (due + start dates) + unit tests (midnight, Sunday, overdue, DST, start only)
- [x] `snapshot.py` (reads Trello state) + `reconcile.py` (pure planner) + unit tests: create / move / remove, `Today` ordering,
      `Done` → complete source, daily `Done` clear
- [x] `__main__.py` with `--dry-run` / `--verbose` / `--clear-done` / `--today` (56 tests pass)
- [x] Dry-run against the real boards matches expectations

### Phase 2 — Live + scheduling
- [x] Apply actions (`apply.py`, 61 tests pass); first live run 2026-10-01: 9 mirrors created,
      second run no-op
- [x] systemd user units written in `systemd/` (every 10 min; 00:05 with `--clear-done`)
- [ ] Install + enable the timers (user runs the commands)
- [ ] Optional: `sudo loginctl enable-linger $USER` so timers run while logged out
- [ ] One week of normal use without broken mirrors

### Phase 3 — Optional
- [ ] What happens when Trello is used and the main computer is off? What are the
      alternatives? (see section 6, Phase 3)

Project 1 of 2. The companion project is the Obsidian ↔ Trello plugin
(`PLAN-obsidian-trello-plugin.md`). The two projects share no code, only the Trello API.

## 1. Context

- **Trello**: several project boards + one master board, **Weekly focus**, with lists
  `Doing | Today | Tomorrow | This week | Done`.
- **Machine**: Ubuntu, Python 3, systemd.
- **Goal**: cards with a due date on any project board automatically appear on Weekly focus
  as **native mirror cards**, in `Today`, `Tomorrow` or `This week`, and move between those
  lists as time passes or dates change.

## 2. Why a script and not Trello automation

Trello supports native mirror cards (Standard plan and up), and automation can create them,
but automation alone is not enough:

- Automation rules are defined per board, so every project board needs its own rules.
- Automation edits to a mirror edit the mirror itself and break it into a plain link card.
- Rescheduling a card does not move its mirror back; date rules are not retroactive.

A small script that recomputes the correct state on every run avoids all three problems.
It must run even when no app is open (midnight updates), so it is a standalone service.

## 3. Key technical findings

### Creating a native mirror via the API (undocumented, used by the `trello-dotnet` library)

```
POST https://api.trello.com/1/cards
  idList   = <target list id on Weekly focus>
  name     = <source card shortUrl>
  cardRole = mirror
  pos      = top | bottom
```

Reading cards back: a mirror has `cardRole == "mirror"` and `mirrorSourceId == <source card id>`.
Request these explicitly with `fields=...,cardRole,mirrorSourceId`.

### Known pitfalls

- **Any automation rule on Weekly focus that modifies incoming cards (e.g. add label on
  card added) breaks mirrors into plain link cards.** Weekly focus must have no such rules.

### Phase 0 results (2026-09-30)

- `POST /cards` with `cardRole=mirror` creates a native mirror; `mirrorSourceId` is the
  source card id.
- `PUT /cards/{id}?idList=...&pos=top` moves a mirror and it stays a mirror; the source is
  not touched.
- `GET /boards/{id}/cards` returns mirrors with `cardRole` and `mirrorSourceId`.
- `DELETE /cards/{mirror id}` removes the mirror only; the source card survives.
- **The mirror does not expose the source's `due`** (null), and its `name` is the source
  `shortUrl`. Due dates must be read from the source boards, never from the mirrors.
- Archived mirrors are excluded from `/boards/{id}/cards` (default filter) but returned by
  `/boards/{id}/cards/closed`, still with `cardRole` and `mirrorSourceId`.
- **Archiving a mirror (`PUT closed=true`) does not archive or complete the source**, and
  neither does deleting it. Mirror and source have independent lifecycles.
- Decision (2026-09-30): keep the paid plan and native mirrors. Self-made copies (plain
  cards synced one way from the source) were considered to allow a downgrade, but rejected
  for now: they are snapshots, not live views, and the free plan caps a Workspace at
  10 boards.

## 4. Architecture

```
01_trello_weekly_focus/
├── config.toml              # board/list names, source boards, timezone (no secrets)
├── .env                     # TRELLO_KEY, TRELLO_TOKEN (not committed)
├── pyproject.toml           # dependencies (requests) + pytest settings
├── weekly_focus/
│   ├── config.py            # config.toml + .env loading
│   ├── client.py            # thin REST wrapper, retry/backoff on HTTP 429 / 5xx
│   ├── buckets.py           # due/start date -> Today / Tomorrow / This week / none
│   ├── snapshot.py          # reads Trello into plain data (only module that reads)
│   ├── reconcile.py         # desired state vs actual state -> actions (pure, no API)
│   ├── apply.py             # actions -> Trello writes (one failure never stops the rest)
│   └── __main__.py          # CLI: --dry-run, --verbose, --clear-done, --today
├── tests/                   # python3 -m pytest
├── test_trello_mirror.py    # Phase 0 feasibility test
└── systemd/                 # weekly-focus.service + weekly-focus.timer
```

- **Polling, not webhooks** (webhooks need a public HTTPS endpoint).
- **Reconciliation, not events**: each run recomputes the desired state from scratch and
  applies the difference. Runs are idempotent and self-healing (missed runs, rescheduled
  cards, new boards).
- `--dry-run` prints planned actions and changes nothing.
- All date logic in `Europe/Paris`.
- Secrets from environment / `.env`; everything else in `config.toml`.

## 5. Reconciler design

### Inputs

- Source boards: all open boards except Weekly focus. `config.toml` has two optional
  lists, both empty by default: `include_boards` (if set, only these) and
  `exclude_boards` (always skipped).
- Source cards: open cards with a `due` and/or `start` date and `dueComplete == false`.

### Bucketing (evaluated in Europe/Paris)

| Condition on source `due` | Bucket |
|---|---|
| today, or overdue | `Today` |
| tomorrow | `Tomorrow` |
| day after tomorrow up to today + 7 days (rolling window, weekends included) | `This week` |
| later / no due date | see start date below, else not on Weekly focus |

**Start date** (confirmed 2026-09-30): if the due date does not put the card in a
bucket (due later than today + 7, or no due date) but the card has a `start` date on or
before today + 7, the card goes to `This week`. The due date always wins when it gives a
bucket. Example: start Monday, due in three weeks → `This week` from Monday until the due
date comes within the window, then `Tomorrow` / `Today` as usual. A start date never puts a
card in `Tomorrow` or `Today`; only the due date does.

Comparisons are on calendar dates in Europe/Paris, not on 24-hour spans: a card due
Thursday 23:00 is "tomorrow" all of Wednesday. Example on a Wednesday: Wednesday or earlier
→ `Today`, Thursday → `Tomorrow`, Friday to next Wednesday → `This week`.

### Rules

- **Managed lists**: `Today`, `Tomorrow`, `This week`. The script only creates, moves and
  removes mirrors in these lists.
- **Unmanaged lists**: `Doing`, `Done`. A mirror the user moved there is **never touched**
  by the bucketing logic.
- **Completed source → mirror to `Done`** (decided 2026-10-01): a mirror in a managed list
  or in `Doing` whose source is complete (checkbox ticked on the source or on the mirror)
  is moved to `Done` instead of deleted. A duplicate already in `Done` is deleted instead.
  To reopen a card, move its mirror out of `Done` first, otherwise the `Done` rule below
  completes the source again.
- **Completed hand-made cards → `Done`** (decided 2026-10-01): a card created directly on
  Weekly focus, ticked complete, in a managed list or `Doing` is moved to `Done` (then
  archived by the daily clear). Hand-made cards are otherwise never moved by their dates.
- For each source card with a bucket:
  - no mirror anywhere on Weekly focus → create a mirror in the bucket list;
  - mirror in a managed list ≠ bucket → move it;
  - mirror in `Doing` / `Done` → leave it.
- For each mirror in a managed list whose source no longer has a bucket (date pushed out,
  date removed, completed, archived, deleted) → remove the mirror.
- Mirrors are identified by `cardRole == "mirror"` + `mirrorSourceId`. No extra state file.
- **Ordering in `Today`**: overdue cards first (oldest due first), then cards due today.
  Mirrors are only repositioned when the order is wrong, to avoid useless API calls.
- **`Done` completes the source**: every run, each mirror in `Done` whose source is not
  complete → set the source's `dueComplete = true`.
- **Daily `Done` clear** (`--clear-done`, run once shortly after midnight): complete the
  sources first (rule above), then **archive the source card** of each mirror in `Done`,
  then **delete** those mirrors (safe, see Phase 0 D) and **archive** hand-made cards in
  `Done` (never delete content that exists only on Weekly focus). Only sources whose
  mirror is in `Done` are archived; other completed cards on project boards are untouched.
- Otherwise, non-mirror cards on Weekly focus (created by hand) are ignored.
- **Archived mirrors are left alone**: each run also reads `/boards/{id}/cards/closed`. A
  source that has an archived mirror is treated as "hidden by the user": no new mirror is
  created for it. This is also why the daily clear deletes mirrors instead of archiving
  them (archiving would hide the source forever).

### Scheduling

systemd timer every 10–15 minutes, plus a run shortly after midnight with `--clear-done`.
The run stays stateless: the daily clear is decided by the timer, not by a state file.

## 6. Phased plan

### Phase 0 — Feasibility test

Run `test_trello_mirror.py` on a throwaway card.
**Done when**: mirror creation (A) and mirror move (B) both PASS; note whether the mirror
exposes `due` and whether deleting a mirror is safe for the source.
If B fails → fallback: plain cards (title + link to source) kept in sync by the script.

### Phase 1 — Core logic, dry-run

REST client, config loading, bucketing with unit tests (fixed "now"; edge cases: midnight,
Sunday, overdue, DST change), reconciler producing an action list, `--dry-run` CLI.
**Done when**: dry-run output matches expectations on the real boards.

### Phase 2 — Live + scheduling

Apply actions, systemd service + timer, logging to journald.
**Done when**: one week of normal use with correct columns and no broken mirrors.

### Phase 3 — Optional

**Question: what happens when Trello is used and the main computer is off? What are the
alternatives?**

Current behaviour, to confirm: while the computer is off or asleep, nothing updates
(no new mirrors, no moves at midnight, `Done` does not complete sources). At the next
wake-up the timers catch up (`Persistent=true`) and, since each run recomputes everything,
one run brings the board back to the correct state. Only the timing is lost, never data.

Alternatives to study (same code, only where it runs changes):

- An always-on machine at home (Raspberry Pi, NAS, home server) with the same systemd units.
- A small cloud VM / VPS with the same systemd units.
- A scheduled cloud job (e.g. GitHub Actions `schedule`, a serverless function with a cron
  trigger), with the key and token stored as secrets. Needs a look at cron precision,
  free-tier limits, and where the logs go.
- Keep the laptop only, and accept delays while it is off.

For each: cost, setup/maintenance effort, reliability, where the token is stored.

(Earlier notes: `Done` → complete, `Done` clear, start dates and `Today` ordering
moved into Phase 1; the overdue label was dropped: it would require editing mirrors or
source cards, and Trello already shows overdue dates in red.)

## 7. Open questions

1. ~~**"This week"**: rest of the current calendar week (Mon–Sun), or the next 7 days?~~
   **Answered (2026-09-30):** the next 7 days, rolling, weekends included (see Bucketing).
2. ~~**Overdue cards**: stay in `Today`, or get special treatment (e.g. a label)?~~
   **Answered (2026-09-30):** they stay in `Today`, sorted first. No label.
3. ~~**Start dates**: should a card with a start date appear before its due date?~~
   **Answered (2026-09-30):** yes, when a start date is present. Exact rule to confirm
   (see Bucketing).
4. ~~**Source boards**: all boards except Weekly focus, or an explicit list?~~
   **Answered (2026-09-30):** all boards for now, with `include_boards` /
   `exclude_boards` in `config.toml` for later.
5. ~~**Done**: should moving a mirror to `Done` complete the source? Should `Done` be
   cleared weekly?~~
   **Answered (2026-09-30):** yes, it completes the source; `Done` is cleared **daily**.
6. ~~**Archived mirrors**: should archiving mean "hide this card", or should the mirror come
   back?~~ **Answered (2026-09-30):** archived mirrors are left alone; no new mirror for that
   source.
7. ~~**Daily clear and sources**: should the daily clear also archive the source cards of
   the mirrors in `Done`?~~ **Answered (2026-09-30):** yes.

## 8. Guardrails

- No automation rules on Weekly focus that touch cards.
- Always run `--dry-run` before enabling live runs or after changing the logic.
- Never modify source cards, except for mirrors in `Done`: set `dueComplete` (every run)
  and archive the source (daily clear only).
- Never delete hand-made cards; the daily clear only archives them.

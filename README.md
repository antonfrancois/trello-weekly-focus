# Weekly focus reconciler

Every card with a date on your Trello project boards automatically appears on the
**Weekly focus** board as a native **mirror card**, in `Today`, `Tomorrow` or `This week`,
and moves between those lists as days pass or dates change.

It is a small Python script run by a systemd timer every 10 minutes. Each run reads
Trello, computes where every mirror should be, and applies only the difference, so a
missed run or a changed date is fixed at the next run.

## How cards flow

| Source card (dates in Europe/Paris) | Mirror on Weekly focus |
|---|---|
| Due today, or overdue | `Today`, overdue first (oldest first) |
| Due tomorrow | `Tomorrow` |
| Due in 2 to 7 days (weekends included) | `This week` |
| Not due within 7 days, but start date within 7 days or already past | `This week` |
| Completed (checkbox on the source or on the mirror) | mirror moves to `Done 🎉` |
| Otherwise, or archived | no mirror (an existing one is removed) |

What you do on Weekly focus:

- **Move a mirror to `Doing`**: dates no longer move it; only completing the card does.
- **Tick the due-date checkbox** (on the mirror or the source card): within 10 minutes the
  mirror moves to `Done 🎉`, from `Today` / `Tomorrow` / `This week` or `Doing`.
- **Move a mirror to `Done 🎉`**: the source card is marked complete (within 10 minutes).
  At 00:05 every night, the source card is archived and the mirror deleted; cards you
  created by hand in `Done 🎉` are archived.
- **Archive a mirror**: the script leaves that card alone and never recreates its mirror.
- **Reopen a card**: first move its mirror out of `Done 🎉`, then untick the checkbox.
  While the mirror is in `Done 🎉`, the script marks the source complete again.
- **Cards you create by hand** on Weekly focus are left where you put them, except: ticked
  complete in `Today` / `Tomorrow` / `This week` / `Doing` → moved to `Done 🎉`; in
  `Done 🎉` → archived by the nightly clear. Their dates do not move them.

The script only modifies source cards for mirrors in `Done 🎉` (complete, then archive).

## Requirements

- Ubuntu (or any Linux with systemd), Python 3.11+, the `requests` package.
- A Trello plan with **mirror cards** (Standard or above) on the Workspace.
- A board named **Weekly focus** with the lists `Doing`, `Today`, `Tomorrow`, `This week`,
  `Done 🎉` (names are configurable, see `config.toml`).
- **No automation rule on Weekly focus that modifies cards** (e.g. "when a card is added,
  add a label"): Trello turns a modified mirror into a plain link card.

## 1. Get a Trello API key and token

1. Go to <https://trello.com/power-ups/admin> and click **New**.
   Trello only issues API keys through a "Power-Up"; this one is just a container for the
   key. Fill in a name (e.g. `Weekly focus`), your Workspace, your email.
   **Leave "Iframe connector URL" empty.** No capabilities, nothing to host.
2. Open the Power-Up, tab **API key**, then **Generate a new API key**.
   **Leave "Allowed origins" empty.** You do not need the **Secret** either.
3. Next to the API key, click the **Token** link, check that the page asks for read *and*
   write access, and click **Allow**. Copy the token shown (it usually starts with `ATTA`).
4. Put both in `.env`:

   ```
   cp .env.example .env
   ```

   ```
   TRELLO_KEY=<API key>
   TRELLO_TOKEN=<token>
   ```

The token acts as you on every board you can see: keep it secret. `.env` is in
`.gitignore`. To revoke it: Trello → your avatar → **Settings** → **Applications**.

## 2. Installation

```
cd 01_trello_weekly_focus
python3 -m pip install -r requirements.txt
```

Install `requests` for the **same Python** that systemd will use (`which python3` shows
its path). If you later change Python or move this folder, reinstall the units (step 4).

Check `config.toml` (board and list names, timezone, which boards to scan):

```toml
[sources]
include_boards = []   # if not empty, only these boards are scanned
exclude_boards = []   # these boards are never scanned
```

## 3. Try it

```
python3 -m weekly_focus --dry-run            # show what would change, change nothing
python3 -m weekly_focus --dry-run --verbose  # also list where every card belongs
python3 -m weekly_focus --dry-run --today 2026-10-05   # preview another day
python3 -m weekly_focus --dry-run --clear-done         # preview the nightly clear
python3 -m weekly_focus                      # apply the changes for real
```

Always do a `--dry-run` after changing `config.toml` or the code.

## 4. Run it automatically (systemd)

Two user timers (no root needed):

| Timer | Runs | Does |
|---|---|---|
| `weekly-focus.timer` | every 10 minutes | create / move / remove mirrors, complete sources in `Done 🎉` |
| `weekly-focus-clear.timer` | every day at 00:05 | the same, plus the daily clear of `Done 🎉` |

Install and enable. The files in `systemd/` are templates: this fills in this folder and
your Python while copying them.

```
mkdir -p ~/.config/systemd/user
for f in systemd/weekly-focus*; do
  sed -e "s|/path/to/trello-weekly-focus|$PWD|" -e "s|/path/to/python3|$(which python3)|" \
    "$f" > ~/.config/systemd/user/"$(basename "$f")"
done
systemctl --user daemon-reload
systemctl --user enable --now weekly-focus.timer weekly-focus-clear.timer
systemctl --user list-timers 'weekly-focus*'
```

`list-timers` must show both timers with a `NEXT` time. If the computer was asleep at
00:05, the clear runs as soon as it wakes up.

By default, user timers only run while you are logged in. To run them when you are
logged out too:

```
sudo loginctl enable-linger $USER
```

## 5. Logs

```
journalctl --user -u weekly-focus -u weekly-focus-clear --since today   # today's runs
journalctl --user -u weekly-focus -f                                   # follow live
journalctl --user -u weekly-focus-clear -n 50                          # last nightly clear
systemctl --user list-timers 'weekly-focus*'                           # next / last run
systemctl --user status weekly-focus.service                           # last run result
```

Each run prints the boards scanned, the number of cards, and one line per action
(`done ...` or `FAILED ...`). A run with a failed action exits with an error, which shows
as `failed` in `systemctl --user status`.

Run it right now instead of waiting for the timer:

```
systemctl --user start weekly-focus.service
```

## 6. Pause, resume, uninstall

```
# pause (nothing runs until you resume)
systemctl --user disable --now weekly-focus.timer weekly-focus-clear.timer

# resume
systemctl --user enable --now weekly-focus.timer weekly-focus-clear.timer

# uninstall
systemctl --user disable --now weekly-focus.timer weekly-focus-clear.timer
rm ~/.config/systemd/user/weekly-focus*
systemctl --user daemon-reload
```

Pausing leaves the mirrors where they are. To pause only the nightly clear, disable
`weekly-focus-clear.timer` alone.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| A card does not appear | It needs a due date within 7 days (or a start date), must not be complete, and its board must be scanned. If you once archived its mirror, it stays hidden: the dry run lists these as "hidden by an archived mirror"; restore or delete the archived mirror. Or the timer is not running: check `list-timers`. |
| A mirror became a plain link card | An automation rule on Weekly focus modified it. Remove the rule, delete the link card; the next run recreates the mirror. |
| `No open board named 'Weekly focus'` / `List ... not found` | Board or list renamed: update `config.toml`. |
| `HTTP 401` | Key or token wrong or revoked: redo step 1. |
| `HTTP 429` | Trello rate limit: the script waits and retries on its own. |

## Development

```
python3 -m pytest          # unit tests, no network
```

```
config.toml              # board/list names, timezone, source boards (no secrets)
.env                     # TRELLO_KEY, TRELLO_TOKEN (not committed)
weekly_focus/
    config.py            # config.toml + .env loading
    client.py            # Trello REST wrapper, retries on 429 / 5xx
    buckets.py           # dates -> Today / Tomorrow / This week
    snapshot.py          # reads Trello (the only module that reads)
    reconcile.py         # current state -> list of actions (pure logic)
    apply.py             # actions -> Trello writes
    __main__.py          # command line
tests/                   # pytest
systemd/                 # service + timer units
test_trello_mirror.py    # Phase 0 feasibility test (creates and deletes one mirror)
PLAN-weekly-focus.md     # design notes, decisions, TODO
```

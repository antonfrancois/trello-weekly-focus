"""Load config.toml and credentials (.env or environment)."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

LIST_ROLES = ("doing", "today", "tomorrow", "this_week", "done")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Config:
    timezone: ZoneInfo
    board: str
    lists: dict  # role -> list name on the master board
    include_boards: tuple
    exclude_boards: tuple


def load_config(path):
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Config file not found: {path}")
    lists = data.get("lists", {})
    missing = [role for role in LIST_ROLES if not lists.get(role)]
    if missing:
        raise ConfigError(f"Missing list names in [lists]: {', '.join(missing)}")
    sources = data.get("sources", {})
    return Config(
        timezone=ZoneInfo(data.get("timezone", "Europe/Paris")),
        board=data.get("board", "Weekly focus"),
        lists={role: lists[role] for role in LIST_ROLES},
        include_boards=tuple(sources.get("include_boards", [])),
        exclude_boards=tuple(sources.get("exclude_boards", [])),
    )


def load_dotenv(path):
    """Minimal .env reader: KEY=value lines, never overrides existing env vars."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def credentials():
    key, token = os.environ.get("TRELLO_KEY"), os.environ.get("TRELLO_TOKEN")
    if not (key and token):
        raise ConfigError("Set TRELLO_KEY and TRELLO_TOKEN (environment or .env).")
    return key, token


def normalize(name):
    """Board/list names are compared ignoring case and surrounding spaces."""
    return name.strip().casefold()

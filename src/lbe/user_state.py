"""User preferences and session state persistence for LittleBigEngine."""

import json
from pathlib import Path

STATE_DIR = Path.home() / ".lbe"
STATE_FILE = STATE_DIR / "state.json"


def get_user_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def set_user_state(**kwargs) -> None:
    state = get_user_state()
    state.update(kwargs)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        temp_file = STATE_DIR / "state.json.tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        temp_file.replace(STATE_FILE)
    except Exception:
        pass


def get_last_project() -> Path | None:
    state = get_user_state()
    path_str = state.get("last_project")
    if path_str:
        try:
            p = Path(path_str).resolve()
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass
    return None


def save_last_project(directory: str | Path) -> None:
    try:
        p = Path(directory).resolve()
        if p.exists() and p.is_dir():
            set_user_state(
                last_project=str(p),
                last_directory=str(p.parent if p.is_dir() else p)
            )
    except Exception:
        pass


def get_last_directory() -> Path:
    state = get_user_state()
    path_str = state.get("last_directory") or state.get("last_project")
    if path_str:
        try:
            p = Path(path_str).resolve()
            if p.exists():
                return p if p.is_dir() else p.parent
        except Exception:
            pass
    user_docs = Path.home() / "Documents"
    if user_docs.exists():
        return user_docs.resolve()
    return Path.home().resolve()

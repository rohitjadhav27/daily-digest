"""Per-template persistent state in state/<template id>.json, committed back by the workflow."""

import json
from datetime import date, timedelta
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state"
URL_RETENTION_DAYS = 30
MAX_CHALLENGES = 60


def default_state() -> dict:
    return {
        "sent_urls": {},
        "last_sent": None,
        "issue": 0,
        "curriculum": {"positions": {}, "next": 0},
        "covered_concepts": [],
        "challenges": [],
        "challenge_history": [],
        "today": None,
    }


def _migrate(state: dict, track_keys: list[str]) -> dict:
    """Upgrade the single-template state format in place."""
    cur = state.get("curriculum") or {}
    if "positions" not in cur:
        positions = {k: v for k, v in cur.items() if isinstance(v, int)}
        nxt = track_keys.index(cur["next"]) if cur.get("next") in track_keys else 0
        state["curriculum"] = {"positions": positions, "next": nxt}
    pending = state.pop("pending_challenge", None)
    if pending:
        pending.setdefault("revealed", False)
        state.setdefault("challenges", []).append(pending)
    return state


def path_for(template_id: str) -> Path:
    return STATE_DIR / f"{template_id}.json"


def load(template_id: str, track_keys: list[str]) -> dict:
    state = default_state()
    path = path_for(template_id)
    if path.exists():
        state.update(json.loads(path.read_text()))
    return _migrate(state, track_keys)


def save(template_id: str, state: dict, today: date) -> None:
    cutoff = (today - timedelta(days=URL_RETENTION_DAYS)).isoformat()
    state["sent_urls"] = {u: d for u, d in state["sent_urls"].items() if d >= cutoff}
    state["challenges"] = state["challenges"][-MAX_CHALLENGES:]
    state["challenge_history"] = state["challenge_history"][-90:]
    STATE_DIR.mkdir(exist_ok=True)
    path_for(template_id).write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")

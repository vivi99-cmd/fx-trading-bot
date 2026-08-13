"""
Record of which breakout signals have already been acted on.

Why this exists: the live runner used to fire only during the exact ET hour
of a session open, so a given signal realistically got one shot. Now that the
runner accepts a multi-hour window (config.SIGNAL_WINDOW_HOURS), the same
signal is visible to several consecutive runs. The "am I already holding a
position?" check alone does not cover that -- if the bracket order's stop or
target fills between two runs, the position is gone but the signal is still
there, and the next run would re-enter a trade that already resolved.

So each acted-on signal is keyed by (session, pair, entry timestamp) and
written to disk. State lands in broker/state/, which the GitHub Actions
workflow commits back to the repo, so it survives ephemeral runners the same
way the kill-switch flag does.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

STATE_DIR = Path(__file__).resolve().parent / "state"
ACTED_FILE = STATE_DIR / "acted_signals.json"

# Entries older than this are dropped on write, so the file does not grow
# without bound. Comfortably longer than any signal stays actionable.
RETENTION_DAYS = 7


def signal_key(session_name: str, pair: str, entry_time) -> str:
    return f"{session_name}|{pair}|{entry_time.isoformat()}"


def _load() -> dict:
    if not ACTED_FILE.exists():
        return {}
    try:
        return json.loads(ACTED_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        # A corrupt or unreadable log must not halt trading, but it also must
        # not silently look like "nothing has been acted on" -- the caller
        # still has the open-position check as a second line of defense.
        print(f"WARNING: could not read {ACTED_FILE}, treating as empty.")
        return {}


def has_acted(session_name: str, pair: str, entry_time) -> bool:
    return signal_key(session_name, pair, entry_time) in _load()


def record(session_name: str, pair: str, entry_time, details: dict = None) -> None:
    acted = _load()
    now = datetime.now(timezone.utc)

    cutoff = now.timestamp() - RETENTION_DAYS * 86400
    acted = {
        key: value
        for key, value in acted.items()
        if _recorded_timestamp(value) is None or _recorded_timestamp(value) >= cutoff
    }

    entry = {"recorded_at": now.isoformat()}
    if details:
        entry.update(details)
    acted[signal_key(session_name, pair, entry_time)] = entry

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ACTED_FILE.write_text(json.dumps(acted, indent=2, sort_keys=True))


def _recorded_timestamp(value: dict):
    try:
        return datetime.fromisoformat(value["recorded_at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None  # unparseable entry: keep it rather than risk dropping a real one


def clear() -> None:
    if ACTED_FILE.exists():
        ACTED_FILE.unlink()

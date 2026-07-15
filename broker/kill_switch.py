"""
Persistent drawdown kill switch, same pattern as the stock bot's. Baseline
is the fixed config.INITIAL_CAPITAL so it works identically on ephemeral
runners (GitHub Actions) or a persistent local disk -- only the tripped
flag needs to survive between runs.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

STATE_DIR = Path(__file__).resolve().parent / "state"
TRIPPED_FILE = STATE_DIR / "kill_switch_tripped.json"


def get_baseline() -> float:
    return float(config.INITIAL_CAPITAL)


def is_tripped() -> bool:
    return TRIPPED_FILE.exists()


def check_and_trip(current_equity: float, baseline_equity: float = None) -> bool:
    if is_tripped():
        return True

    baseline_equity = baseline_equity if baseline_equity is not None else get_baseline()
    threshold = baseline_equity * (1 - config.KILL_SWITCH_DRAWDOWN_PCT)
    if current_equity <= threshold:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        TRIPPED_FILE.write_text(
            json.dumps(
                {
                    "tripped_at": datetime.now(timezone.utc).isoformat(),
                    "baseline_equity": baseline_equity,
                    "equity_at_trip": current_equity,
                    "threshold": threshold,
                }
            )
        )
        return True

    return False


def reset():
    if TRIPPED_FILE.exists():
        TRIPPED_FILE.unlink()

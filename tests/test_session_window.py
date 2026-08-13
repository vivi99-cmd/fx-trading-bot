"""
Checks for the live runner's session gating and the acted-signal log.

Background: the gate used to be `now_et.hour == open_hour`, which meant a run
delivered even one hour late was dropped. Across a 60-run sample only 7 runs
ever passed it, and the London session -- the strategy's best-documented
setup -- never fired once. These tests pin down the window that replaced it,
and the two guards that keep widening it from causing duplicate entries.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from broker import signal_log
from broker.live_fx_runner import get_active_sessions, signal_age_minutes
from strategies.fx_utils import ET


def _et(timestamp: str):
    return pd.Timestamp(timestamp, tz=ET)


def _active_names(timestamp: str):
    return [name for name, _ in get_active_sessions(_et(timestamp))]


def test_run_on_the_hour_still_works():
    """The old exact-hour behaviour has to remain a subset of the new one."""
    for timestamp, expected in [
        ("2026-08-12 03:00", "london"),
        ("2026-08-12 08:00", "new_york"),
        ("2026-08-12 17:00", "sydney"),
        ("2026-08-12 19:00", "tokyo"),
    ]:
        assert expected in _active_names(timestamp), f"{expected} should be active at {timestamp}"
    print("on-the-hour runs still active for all four sessions: OK")


def test_late_run_inside_the_window_is_accepted():
    """The whole point: a run GitHub delivered hours late still gets to act."""
    assert "london" in _active_names("2026-08-12 04:30")
    assert "london" in _active_names("2026-08-12 05:45"), "2h45m late is still inside a 3h window"
    assert "new_york" in _active_names("2026-08-12 10:15")
    print("late runs inside the window are accepted: OK")


def test_run_past_the_window_is_rejected():
    assert "london" not in _active_names("2026-08-12 06:30"), "3h30m past open is outside the window"
    assert "new_york" not in _active_names("2026-08-12 12:00")
    print("runs past the window are rejected: OK")


def test_run_before_the_open_is_rejected():
    """A window looks backwards only -- it must not pre-empt a session."""
    assert "london" not in _active_names("2026-08-12 02:30")
    assert "new_york" not in _active_names("2026-08-12 07:45")
    print("runs before the open are rejected: OK")


def test_overlapping_sessions_are_all_returned():
    """Sydney 17:00 and Tokyo 19:00 windows overlap; both should be actionable."""
    names = _active_names("2026-08-12 19:30")
    assert "tokyo" in names and "sydney" in names, f"expected both sydney and tokyo, got {names}"
    assert names.index("sydney") < names.index("tokyo"), "sessions should come back oldest-open first"
    print("overlapping session windows both returned, oldest first: OK")


def test_after_midnight_does_not_resurrect_the_evening_session():
    """Tokyo's open is on the previous calendar day by 00:30 -- and 5h stale."""
    assert _active_names("2026-08-13 00:30") == [], "nothing should be active 5h after Tokyo's open"
    assert "tokyo" in _active_names("2026-08-12 21:30"), "but 2h30m after Tokyo's open is fine"
    print("post-midnight run does not resurrect a stale evening session: OK")


def test_signal_age_gates_stale_entries():
    now = _et("2026-08-12 05:00")
    fresh = {"entry_time": _et("2026-08-12 04:20")}
    stale = {"entry_time": _et("2026-08-12 03:10")}

    assert signal_age_minutes(fresh, now) == 40
    assert signal_age_minutes(stale, now) == 110

    assert signal_age_minutes(fresh, now) <= config.MAX_SIGNAL_AGE_MINUTES, "40 min old should be tradeable"
    assert signal_age_minutes(stale, now) > config.MAX_SIGNAL_AGE_MINUTES, "110 min old should be rejected"
    print("signal age computed and gated against MAX_SIGNAL_AGE_MINUTES: OK")


def test_acted_signal_log_blocks_reentry():
    signal_log.clear()
    entry_time = _et("2026-08-12 03:15")
    try:
        assert not signal_log.has_acted("london", "EUR_USD", entry_time)

        signal_log.record("london", "EUR_USD", entry_time, {"units": 1000})
        assert signal_log.has_acted("london", "EUR_USD", entry_time), "same signal must not be re-entered"

        # A different pair, session, or trigger time is a genuinely different trade.
        assert not signal_log.has_acted("london", "AUD_USD", entry_time)
        assert not signal_log.has_acted("new_york", "EUR_USD", entry_time)
        assert not signal_log.has_acted("london", "EUR_USD", _et("2026-08-12 03:30"))
        print("acted-signal log blocks re-entry and distinguishes distinct signals: OK")
    finally:
        signal_log.clear()


def test_acted_signal_log_survives_a_reload():
    """It only helps if it persists between runs -- that is the entire job."""
    signal_log.clear()
    entry_time = _et("2026-08-12 03:15")
    try:
        signal_log.record("london", "EUR_USD", entry_time)
        assert signal_log.ACTED_FILE.exists(), "state must be on disk for the workflow to commit it"

        import importlib

        importlib.reload(signal_log)
        assert signal_log.has_acted("london", "EUR_USD", entry_time), "record must survive a fresh process"
        print("acted-signal log persists across processes: OK")
    finally:
        signal_log.clear()


if __name__ == "__main__":
    test_run_on_the_hour_still_works()
    test_late_run_inside_the_window_is_accepted()
    test_run_past_the_window_is_rejected()
    test_run_before_the_open_is_rejected()
    test_overlapping_sessions_are_all_returned()
    test_after_midnight_does_not_resurrect_the_evening_session()
    test_signal_age_gates_stale_entries()
    test_acted_signal_log_blocks_reentry()
    test_acted_signal_log_survives_a_reload()
    print("\nAll session window tests passed.")

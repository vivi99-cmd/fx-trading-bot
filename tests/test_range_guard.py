"""
Checks the lookback-window data-quality guard.

The old guard was `len(range_window) < 2`, which accepted a 2-bar window where
London expects 32. On 2026-08-14 the live Tokyo window arrived with 2 bars and
a measured range of 0.0 pips. Range size sets both the stop distance and, via
risk-based sizing, the position size -- so a sparse window yields a stop inside
the spread with the largest position in the book behind it.
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from strategies.fx_utils import ET
from strategies.session_breakout import bars_per_hour, generate_session_trades, min_range_bars


def test_bars_per_hour_matches_interval():
    assert bars_per_hour("15m") == 4
    assert bars_per_hour("5m") == 12
    assert bars_per_hour("1h") == 1
    print("bars_per_hour derived from interval: OK")


def test_guard_scales_with_lookback():
    """Each session's requirement should track its own window length."""
    for name, cfg in config.SESSIONS.items():
        expected = cfg["lookback_hours"] * bars_per_hour()
        required = min_range_bars(cfg["lookback_hours"])
        assert required >= 2, f"{name}: guard must never fall below the old floor"
        assert required <= expected, f"{name}: cannot require more bars than the window holds"
        assert required == round(expected * config.MIN_RANGE_BAR_COVERAGE + 0.5) or required >= expected * config.MIN_RANGE_BAR_COVERAGE
    assert min_range_bars(8) > min_range_bars(2), "a longer lookback must require more bars"
    print("guard scales with each session's lookback: OK")


def _bars(start_et, count, price=1.1000, step=0.0002):
    idx = pd.date_range(start_et, periods=count, freq="15min", tz=ET)
    closes = [price + step * (i % 3) for i in range(count)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + step for c in closes],
            "Low": [c - step for c in closes],
            "Close": closes,
            "Volume": [1000] * count,
        },
        index=idx,
    )


def test_sparse_window_produces_no_trade():
    """The 2026-08-14 Tokyo case: 2 bars where 8 are expected."""
    tokyo_open = pd.Timestamp("2026-08-14 19:00", tz=ET)
    lookback = config.SESSIONS["tokyo"]["lookback_hours"]

    # Two bars immediately before the open, then a strong move after it. The
    # post-open move is what would have been traded on the bad range.
    sparse = _bars(tokyo_open - pd.Timedelta(minutes=30), 2)
    after = _bars(tokyo_open, 4, price=1.1100, step=0.0010)
    df = pd.concat([sparse, after])

    assert len(sparse) < min_range_bars(lookback), "fixture must be sparser than the guard allows"
    assert generate_session_trades(df, "tokyo") == [], "a 2-bar lookback must not produce a trade"
    print("sparse lookback window produces no trade: OK")


def test_well_covered_window_still_trades():
    """The guard must not suppress normal sessions -- only starved ones."""
    tokyo_open = pd.Timestamp("2026-08-14 19:00", tz=ET)
    lookback = config.SESSIONS["tokyo"]["lookback_hours"]

    full = _bars(tokyo_open - pd.Timedelta(hours=lookback), lookback * int(bars_per_hour()))
    breakout = _bars(tokyo_open, 4, price=1.1200, step=0.0015)
    df = pd.concat([full, breakout])

    assert len(full) >= min_range_bars(lookback), "fixture should satisfy the guard"
    trades = generate_session_trades(df, "tokyo")
    assert trades, "a fully covered window with a real breakout should still trade"
    print("well-covered window still trades: OK")


if __name__ == "__main__":
    test_bars_per_hour_matches_interval()
    test_guard_scales_with_lookback()
    test_sparse_window_produces_no_trade()
    test_well_covered_window_still_trades()
    print("\nAll range guard tests passed.")

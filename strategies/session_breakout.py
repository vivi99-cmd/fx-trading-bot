import math
import sys
from datetime import time as dtime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from strategies.fx_utils import ET, to_et

import pandas as pd


def bars_per_hour(interval: str = None) -> float:
    """Bars an hour of data should contain at the configured interval."""
    interval = interval or config.INTERVAL
    if interval.endswith("m"):
        return 60.0 / int(interval[:-1])
    if interval.endswith("h"):
        return 1.0 / int(interval[:-1])
    raise ValueError(f"cannot derive bars per hour from interval {interval!r}")


def min_range_bars(lookback_hours: int) -> int:
    """How many bars a lookback window must contain to be trusted.

    The old guard was `len(range_window) < 2`, which accepted 2 bars where
    London's 8-hour window expects 32. That is a placeholder, not a
    threshold, and it let bad data through as real setups: on 2026-08-14 the
    Tokyo window arrived with 2 bars instead of 8 and a measured range of
    0.0 pips. Range size drives both the stop distance and the position
    size, so a window built from a couple of sparse bars produces a stop
    inside the spread and -- because size is risk/stop-distance -- the
    largest position in the book behind it.

    yfinance FX bars are indicative and go missing in thin hours, so this is
    a data-quality check rather than a strategy parameter.
    """
    expected = lookback_hours * bars_per_hour()
    return max(2, math.ceil(expected * config.MIN_RANGE_BAR_COVERAGE))


def generate_session_trades(price_df: pd.DataFrame, session_name: str) -> list:
    """
    For one FX pair's price history, find every occurrence of the given
    session's breakout setup: measure the high/low range over the
    lookback window immediately before the session opens, then check
    whether price breaks out of that range within the first hour after
    open. Returns a list of trade setups (not yet simulated) with entry
    price/time, direction, stop-loss, and take-profit levels.
    """
    session = config.SESSIONS[session_name]
    open_hour = session["open_hour_et"]
    lookback_hours = session["lookback_hours"]

    df = to_et(price_df)
    trades = []

    dates = sorted(set(df.index.date))
    for d in dates:
        open_time = pd.Timestamp.combine(d, dtime(hour=open_hour, minute=0)).tz_localize(ET)
        range_start = open_time - timedelta(hours=lookback_hours)
        detection_end = open_time + timedelta(hours=1)

        range_window = df[(df.index >= range_start) & (df.index < open_time)]
        if len(range_window) < min_range_bars(lookback_hours):
            continue
        range_high = range_window["High"].max()
        range_low = range_window["Low"].min()
        range_size = range_high - range_low
        if range_size <= 0:
            continue

        detection_window = df[(df.index >= open_time) & (df.index < detection_end)]
        if detection_window.empty:
            continue

        upper_trigger = range_high * (1 + config.BREAKOUT_BUFFER_PCT)
        lower_trigger = range_low * (1 - config.BREAKOUT_BUFFER_PCT)

        direction = None
        entry_price = None
        entry_time = None
        for ts, row in detection_window.iterrows():
            if row["High"] >= upper_trigger:
                direction = 1
                entry_price = upper_trigger
                entry_time = ts
                break
            if row["Low"] <= lower_trigger:
                direction = -1
                entry_price = lower_trigger
                entry_time = ts
                break

        if direction is None:
            continue

        if direction == 1:
            stop_loss = entry_price - config.STOP_LOSS_RANGE_MULT * range_size
            take_profit = entry_price + config.TAKE_PROFIT_RANGE_MULT * range_size
        else:
            stop_loss = entry_price + config.STOP_LOSS_RANGE_MULT * range_size
            take_profit = entry_price - config.TAKE_PROFIT_RANGE_MULT * range_size

        trades.append(
            {
                "session": session_name,
                "entry_time": entry_time,
                "entry_price": entry_price,
                "direction": direction,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "max_hold_until": entry_time + timedelta(hours=config.MAX_HOLD_HOURS),
                "range_size": range_size,
            }
        )

    return trades


def generate_all_session_trades(price_df: pd.DataFrame) -> list:
    all_trades = []
    for session_name in config.SESSIONS:
        all_trades.extend(generate_session_trades(price_df, session_name))
    return sorted(all_trades, key=lambda t: t["entry_time"])

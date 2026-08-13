"""
Finds which of the 4 session opens happened recently enough to still be
actionable, computes each one's breakout signal using the exact same
strategies/session_breakout.py logic as the backtest, then sizes and submits
a bracket market order (stop-loss + take-profit attached, so OANDA handles
the exit -- no polling needed for that part).

"Recently enough" is a window (config.SIGNAL_WINDOW_HOURS), not an exact hour
match, because the GitHub Actions scheduler delivers runs late and drops most
of them. Three guards keep that widening safe:

  1. config.MAX_SIGNAL_AGE_MINUTES caps how stale a breakout can be and still
     be entered, so a late run cannot chase a long-gone move.
  2. broker/signal_log.py remembers signals already acted on, so consecutive
     runs in the same window cannot re-enter the same trade.
  3. The existing open-position check still blocks stacking onto a live position.

Defaults to --dry-run. Pass --execute to actually submit orders.
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

import pandas as pd

import config
from broker import kill_switch, signal_log
from broker.oanda_connector import (
    close_all_positions,
    get_account_summary,
    get_open_position,
    get_pricing,
    submit_bracket_market_order,
)
from data.fetch_fx_prices import fetch_pair
from strategies.fx_utils import ET
from strategies.session_breakout import generate_session_trades


def session_open_times(session_cfg, now_et):
    """Today's and yesterday's ET open timestamps for one session.

    Yesterday matters for the late-evening sessions: a run just after
    midnight ET is a plausibly-late run for Tokyo's 19:00 open, and the
    calendar date has already rolled over by then.
    """
    open_hour = session_cfg["open_hour_et"]
    today = now_et.normalize()
    return [
        today.replace(hour=open_hour),
        (today - pd.Timedelta(days=1)).replace(hour=open_hour),
    ]


def get_active_sessions(now_et) -> list:
    """Sessions whose open is within the last config.SIGNAL_WINDOW_HOURS.

    Returns (session_name, open_time) pairs, oldest open first. Replaces an
    exact `now_et.hour == open_hour` match, which meant a run delivered even
    one hour late was gated out entirely -- the common case on GitHub's
    scheduler rather than the exception.
    """
    window = pd.Timedelta(hours=config.SIGNAL_WINDOW_HOURS)
    active = []
    for name, session_cfg in config.SESSIONS.items():
        for open_time in session_open_times(session_cfg, now_et):
            if open_time <= now_et < open_time + window:
                active.append((name, open_time))
    return sorted(active, key=lambda item: item[1])


def _fetch_prices_cached(yf_ticker: str, _cache={}):
    """One price fetch per pair per run.

    Overlapping session windows mean the same pair can now be evaluated for
    two sessions in a single run; without this that doubles the yfinance
    calls for identical data, for no benefit and some rate-limit risk.
    """
    if yf_ticker not in _cache:
        _cache[yf_ticker] = fetch_pair(yf_ticker, interval=config.INTERVAL, period="5d", subdir="prices_live")
    return _cache[yf_ticker]


def compute_live_signal(yf_ticker: str, session_name: str, session_open):
    """The breakout for one session's open, or None if there wasn't one.

    Matched on the session's own open timestamp rather than "today" so that a
    run after midnight ET still resolves the previous evening's session
    correctly.
    """
    price_df = _fetch_prices_cached(yf_ticker)
    if price_df.empty:
        return None
    trades = generate_session_trades(price_df, session_name)
    session_trades = [t for t in trades if t["entry_time"].date() == session_open.date()]
    return session_trades[-1] if session_trades else None


def signal_age_minutes(trade, now_et) -> float:
    return (now_et - trade["entry_time"]).total_seconds() / 60.0


def size_position(pair_config: dict, equity: float, entry_price: float, stop_loss: float) -> int:
    # Simplification: assumes quote currency is USD, so 1 unit of risk math
    # needs no conversion, and the base currency's USD value equals the
    # pair's own price. Both current pairs (EUR_USD, AUD_USD) satisfy this.
    # If a non-USD-quote pair is ever added, this needs the general
    # quote/base conversion machinery from backtest/fx_engine.py instead.
    if pair_config["quote"] != "USD":
        raise NotImplementedError(f"size_position assumes quote currency USD, got {pair_config['quote']} for {pair_config['pair']}")

    risk_amount_usd = equity * config.RISK_PCT_PER_TRADE
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        return 0
    units = risk_amount_usd / stop_distance

    max_notional_usd = equity * config.MAX_LEVERAGE
    units = min(units, max_notional_usd / entry_price)
    return int(units)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually submit orders (default: dry run only)")
    args = parser.parse_args()

    now_et = pd.Timestamp.now(tz=ET)
    active_sessions = get_active_sessions(now_et)
    if not active_sessions:
        print(f"No session-open window active at {now_et} (hour={now_et.hour}). Skipping.")
        return
    print(
        f"Active session windows at {now_et}: "
        + ", ".join(f"{name} (opened {open_time:%Y-%m-%d %H:%M})" for name, open_time in active_sessions)
    )

    account = get_account_summary()
    equity = float(account["NAV"])
    print(f"OANDA account NAV: ${equity:,.2f}")

    baseline = kill_switch.get_baseline()
    if kill_switch.check_and_trip(equity, baseline):
        threshold = baseline * (1 - config.KILL_SWITCH_DRAWDOWN_PCT)
        print(
            f"KILL SWITCH TRIPPED: equity ${equity:,.2f} <= threshold ${threshold:,.2f}. "
            f"{'Liquidating all positions and halting.' if args.execute else '[dry-run] would liquidate all positions and halt.'} "
            "Delete broker/state/kill_switch_tripped.json to resume."
        )
        if args.execute:
            close_all_positions()
        return

    instruments = [p["pair"] for p in config.PAIRS]
    pricing = get_pricing(instruments)

    for session_name, session_open in active_sessions:
        for pair_config in config.PAIRS:
            pair = pair_config["pair"]

            price_info = pricing.get(pair)
            if price_info is None or not price_info["tradeable"]:
                print(f"[{session_name}] {pair}: not tradeable right now, skipping.")
                continue

            trade = compute_live_signal(pair_config["yf_ticker"], session_name, session_open)
            if trade is None:
                print(f"[{session_name}] {pair}: no breakout signal for this session's open.")
                continue

            # Order matters below: the already-acted check has to come before
            # the open-position check, because a signal whose bracket already
            # filled leaves no position behind and would otherwise re-enter.
            if signal_log.has_acted(session_name, pair, trade["entry_time"]):
                print(f"[{session_name}] {pair}: breakout at {trade['entry_time']:%H:%M} already acted on, skipping.")
                continue

            age_minutes = signal_age_minutes(trade, now_et)
            if age_minutes > config.MAX_SIGNAL_AGE_MINUTES:
                print(
                    f"[{session_name}] {pair}: breakout at {trade['entry_time']:%H:%M} is {age_minutes:.0f} min old "
                    f"(limit {config.MAX_SIGNAL_AGE_MINUTES}), too stale to enter. Skipping."
                )
                continue

            position = get_open_position(pair)
            if position is not None:
                print(f"[{session_name}] {pair}: breakout signal present but already holding a {position['direction']} position, skipping.")
                continue

            entry_price = trade["entry_price"]
            stop_loss = trade["stop_loss"]
            take_profit = trade["take_profit"]
            direction = trade["direction"]

            units = size_position(pair_config, equity, entry_price, stop_loss)
            if units <= 0:
                print(f"[{session_name}] {pair}: signal present but computed size is 0, skipping.")
                continue
            if direction == -1:
                units = -units

            print(
                f"[{session_name}] {pair}: breakout, direction={'long' if direction == 1 else 'short'}, units={units}, "
                f"stop={stop_loss:.5f}, target={take_profit:.5f}, signal age {age_minutes:.0f} min -> "
                f"{'submitting' if args.execute else '[dry-run] would submit'} bracket order"
            )
            if args.execute:
                submit_bracket_market_order(pair, units, stop_loss, take_profit)
                signal_log.record(
                    session_name,
                    pair,
                    trade["entry_time"],
                    {"units": units, "stop_loss": stop_loss, "take_profit": take_profit},
                )


if __name__ == "__main__":
    main()

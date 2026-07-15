"""
Checks whether we're inside one of the 4 session-open detection windows
right now, and if so, computes today's breakout signal for each pair using
the exact same strategies/session_breakout.py logic as the backtest, then
sizes and submits a bracket market order (stop-loss + take-profit attached,
so OANDA handles the exit -- no polling needed for that part).

Defaults to --dry-run. Pass --execute to actually submit orders. Meant to
be run on a schedule around each of the 4 session-open times, not
continuously -- see README.
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
from broker import kill_switch
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


def get_active_session(now_et) -> str:
    for name, session_cfg in config.SESSIONS.items():
        if now_et.hour == session_cfg["open_hour_et"]:
            return name
    return None


def compute_live_signal(yf_ticker: str, session_name: str, now_et):
    price_df = fetch_pair(yf_ticker, interval=config.INTERVAL, period="5d", subdir="prices_live")
    if price_df.empty:
        return None
    trades = generate_session_trades(price_df, session_name)
    today = now_et.date()
    todays_trades = [t for t in trades if t["entry_time"].date() == today]
    return todays_trades[-1] if todays_trades else None


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
    session_name = get_active_session(now_et)
    if session_name is None:
        print(f"No session-open window active at {now_et} (hour={now_et.hour}). Skipping.")
        return
    print(f"Active session: {session_name} at {now_et}")

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

    for pair_config in config.PAIRS:
        pair = pair_config["pair"]

        price_info = pricing.get(pair)
        if price_info is None or not price_info["tradeable"]:
            print(f"{pair}: not tradeable right now, skipping.")
            continue

        trade = compute_live_signal(pair_config["yf_ticker"], session_name, now_et)
        if trade is None:
            print(f"{pair}: no breakout signal for {session_name} session today.")
            continue

        position = get_open_position(pair)
        if position is not None:
            print(f"{pair}: breakout signal present but already holding a {position['direction']} position, skipping.")
            continue

        entry_price = trade["entry_price"]
        stop_loss = trade["stop_loss"]
        take_profit = trade["take_profit"]
        direction = trade["direction"]

        units = size_position(pair_config, equity, entry_price, stop_loss)
        if units <= 0:
            print(f"{pair}: signal present but computed size is 0, skipping.")
            continue
        if direction == -1:
            units = -units

        print(
            f"{pair}: {session_name} breakout, direction={'long' if direction == 1 else 'short'}, units={units}, "
            f"stop={stop_loss:.5f}, target={take_profit:.5f} -> "
            f"{'submitting' if args.execute else '[dry-run] would submit'} bracket order"
        )
        if args.execute:
            submit_bracket_market_order(pair, units, stop_loss, take_profit)


if __name__ == "__main__":
    main()

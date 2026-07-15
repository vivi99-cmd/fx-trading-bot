import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from strategies.fx_utils import base_to_usd_factor, quote_to_usd_factor, to_et

import pandas as pd


class RateLookup:
    """asof price lookup across every pair's history, used to convert quote-currency P&L into USD."""

    def __init__(self, all_prices_et: dict):
        self.all_prices_et = all_prices_et

    def __call__(self, pair_name: str, timestamp) -> float:
        df = self.all_prices_et.get(pair_name)
        if df is None or df.empty:
            return None
        value = df["Close"].asof(timestamp)
        return None if pd.isna(value) else float(value)


def simulate_exit(price_df_et: pd.DataFrame, trade: dict):
    """Walk forward from entry looking for whichever of stop-loss/take-profit/max-hold triggers first."""
    entry_time = trade["entry_time"]
    direction = trade["direction"]
    stop_loss = trade["stop_loss"]
    take_profit = trade["take_profit"]
    max_hold_until = trade["max_hold_until"]

    subsequent = price_df_et[price_df_et.index > entry_time]
    for ts, row in subsequent.iterrows():
        if ts > max_hold_until:
            break
        if direction == 1:
            if row["Low"] <= stop_loss:
                return ts, stop_loss, "stop_loss"
            if row["High"] >= take_profit:
                return ts, take_profit, "take_profit"
        else:
            if row["High"] >= stop_loss:
                return ts, stop_loss, "stop_loss"
            if row["Low"] <= take_profit:
                return ts, take_profit, "take_profit"

    time_exit_window = price_df_et[(price_df_et.index > entry_time) & (price_df_et.index <= max_hold_until)]
    if not time_exit_window.empty:
        return time_exit_window.index[-1], float(time_exit_window["Close"].iloc[-1]), "max_hold"

    return None, None, None  # ran off the end of available data, can't resolve this trade


def run_fx_backtest(price_df: pd.DataFrame, trades: list, quote_currency: str, base_currency: str, rate_lookup: RateLookup, initial_capital: float = None) -> dict:
    capital = initial_capital if initial_capital is not None else config.INITIAL_CAPITAL
    cash = capital
    price_df_et = to_et(price_df)

    equity_curve = [(price_df_et.index[0], cash)]
    trade_log = []
    open_until = None

    for trade in trades:
        if open_until is not None and trade["entry_time"] < open_until:
            continue  # a previous session's trade is still open on this pair, skip overlap

        exit_time, exit_price, exit_reason = simulate_exit(price_df_et, trade)
        if exit_time is None:
            continue

        entry_price = trade["entry_price"]
        stop_loss = trade["stop_loss"]
        direction = trade["direction"]

        risk_amount_usd = cash * config.RISK_PCT_PER_TRADE
        stop_distance = abs(entry_price - stop_loss)
        factor = quote_to_usd_factor(quote_currency, rate_lookup, trade["entry_time"])
        if stop_distance <= 0 or factor <= 0:
            continue
        units = risk_amount_usd / (stop_distance * factor)

        # cap notional so a tight stop can't force an oversized, spread-cost-heavy position
        base_factor = base_to_usd_factor(base_currency, rate_lookup, trade["entry_time"])
        max_notional_usd = cash * config.MAX_LEVERAGE
        if base_factor > 0:
            max_units = max_notional_usd / base_factor
            units = min(units, max_units)

        pnl_quote = (exit_price - entry_price) * units * direction
        pnl_usd = pnl_quote * factor

        notional_quote = units * entry_price
        spread_cost_usd = notional_quote * config.SPREAD_PCT * factor

        net_pnl = pnl_usd - spread_cost_usd
        cash += net_pnl
        open_until = exit_time

        trade_log.append(
            {
                "session": trade["session"],
                "entry_time": trade["entry_time"],
                "exit_time": exit_time,
                "direction": "long" if direction == 1 else "short",
                "entry_price": entry_price,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "units": units,
                "pnl_usd": net_pnl,
            }
        )
        equity_curve.append((exit_time, cash))

    equity_series = pd.Series([e[1] for e in equity_curve], index=[e[0] for e in equity_curve])
    return {
        "equity_curve": equity_series,
        "trades": pd.DataFrame(trade_log),
        "final_capital": cash,
    }

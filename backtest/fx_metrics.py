import numpy as np
import pandas as pd


def compute_metrics(equity_curve: pd.Series, trades: pd.DataFrame, initial_capital: float, period_days: int) -> dict:
    if len(equity_curve) < 2 or trades.empty:
        return {"total_return_pct": 0, "sharpe_ratio": 0, "max_drawdown_pct": 0, "num_trades": 0, "win_rate_pct": 0}

    total_return = (equity_curve.iloc[-1] / initial_capital) - 1

    # per-trade returns (not per-bar, since trades are sparse/event-driven), annualized
    # using how many trades actually occurred over the backtested period.
    trade_returns = trades["pnl_usd"] / initial_capital
    sharpe = 0.0
    if trade_returns.std() > 0 and period_days > 0:
        trades_per_year = len(trades) / period_days * 365
        sharpe = (trade_returns.mean() / trade_returns.std()) * np.sqrt(trades_per_year)

    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    max_drawdown = drawdown.min()

    win_rate = (trades["pnl_usd"] > 0).mean()

    return {
        "total_return_pct": round(total_return * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "num_trades": len(trades),
        "win_rate_pct": round(win_rate * 100, 2),
    }

import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import config
from backtest.fx_engine import RateLookup, run_fx_backtest
from backtest.fx_metrics import compute_metrics
from data.fetch_fx_prices import fetch_all
from strategies.fx_utils import to_et
from strategies.session_breakout import generate_all_session_trades

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PERIOD_DAYS = int(config.PERIOD.rstrip("d"))


def main():
    prices = fetch_all()
    prices_et = {pair: to_et(df) for pair, df in prices.items()}
    rate_lookup = RateLookup(prices_et)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    summary_rows = []

    fig, axes = plt.subplots(len(config.PAIRS), 1, figsize=(10, 4 * len(config.PAIRS)))
    if len(config.PAIRS) == 1:
        axes = [axes]

    for ax, pair_config in zip(axes, config.PAIRS):
        pair = pair_config["pair"]
        quote_currency = pair_config["quote"]
        base_currency = pair_config["base"]
        price_df = prices[pair]
        if price_df.empty:
            print(f"No price data for {pair}, skipping.")
            continue

        trade_setups = generate_all_session_trades(price_df)
        result = run_fx_backtest(price_df, trade_setups, quote_currency, base_currency, rate_lookup)
        metrics = compute_metrics(result["equity_curve"], result["trades"], config.INITIAL_CAPITAL, PERIOD_DAYS)
        metrics["pair"] = pair
        summary_rows.append(metrics)

        ax.plot(result["equity_curve"].values)
        ax.set_title(f"{pair} — equity curve ({metrics['num_trades']} trades, {metrics['total_return_pct']}% return)")
        ax.set_ylabel("Equity ($)")

        if not result["trades"].empty:
            result["trades"].to_csv(RESULTS_DIR / f"{pair}_trades_{timestamp}.csv", index=False)

    plt.tight_layout()
    chart_path = RESULTS_DIR / f"equity_curves_{timestamp}.png"
    plt.savefig(chart_path)

    summary_df = pd.DataFrame(summary_rows)
    summary_path = RESULTS_DIR / f"summary_{timestamp}.csv"
    summary_df.to_csv(summary_path, index=False)

    print("\n=== FX Session Breakout Backtest Summary ===")
    print(summary_df.to_string(index=False))
    print(f"\nChart saved to {chart_path}")
    print(f"Summary saved to {summary_path}")


if __name__ == "__main__":
    main()

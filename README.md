# FX Session Breakout Trading Bot

A rules-based currency trading system that tests, and then live-trades, a single
well-known FX pattern: the **session breakout**. Price tends to coil into a range
while one trading session is quiet, then break out when the next major session
opens and volume arrives. This bot measures that pre-open range, trades the
breakout, and manages the position with hard risk rules.

It has two halves: a **backtester** that evaluates the strategy on historical
intraday data, and a **live runner** that executes the same logic through OANDA's
API on a schedule.

## The strategy

For each of the four session opens (Sydney, Tokyo, London, New York):

1. **Measure the range.** Take the high and low over a lookback window immediately
   before the session opens — 8 hours before London, 5 before New York, shorter for
   Sydney and Tokyo. The London and New York windows follow the classic pairing
   (Asian range feeds the London breakout, London range feeds the New York one).
2. **Wait for a breakout.** In the first hour after the open, if price clears the
   range high or low by more than a 0.05% buffer, enter in that direction. The
   buffer exists so ordinary noise at the boundary doesn't count as a signal.
3. **Set exits at entry.** Stop-loss at 0.5× the measured range, take-profit at
   1.5× the range — a 3:1 reward-to-risk ratio. A trade that hits neither within
   8 hours is closed anyway.

Position size is derived from risk, not from a fixed lot: each trade risks 1% of
account equity based on the distance to the stop.

## Backtest results

60 days of 15-minute data across 10 major pairs. **Eight of the ten lost money.**

| Pair | Return | Sharpe | Max drawdown | Trades | Win rate |
|---|---:|---:|---:|---:|---:|
| EUR_USD | **+4.36%** | 1.09 | -5.81% | 31 | 38.7% |
| AUD_USD | -0.40% | -0.11 | -8.20% | 36 | 41.7% |
| USD_CAD | -6.80% | -2.06 | -10.54% | 28 | 32.1% |
| GBP_USD | -7.51% | -1.78 | -15.87% | 37 | 32.4% |
| NZD_USD | -8.93% | -1.75 | -21.02% | 57 | 35.1% |
| USD_JPY | -9.86% | -3.21 | -15.46% | 21 | 23.8% |
| EUR_JPY | -22.72% | -8.74 | -23.00% | 36 | 19.4% |
| GBP_JPY | -30.82% | -10.49 | -30.82% | 43 | 14.0% |
| EUR_GBP | -36.47% | -18.44 | -36.47% | 43 | 9.3% |
| USD_CHF | -43.09% | -12.06 | -43.09% | 73 | 17.8% |

The live configuration was cut from ten pairs to the two that were breakeven or
better (EUR_USD, AUD_USD). The cross pairs were the worst performers by a wide
margin, which is consistent with their wider spreads eating a strategy whose
edge per trade is small.

**How much to read into this:** not much, and that's the point of showing it. Sixty
days is roughly 30 trades per pair, which is far too small a sample to establish an
edge. EUR_USD's +4.36% is well within what randomness produces at that sample size.
The honest conclusion is that the strategy is not obviously profitable and would
need a multi-year sample and walk-forward testing before anyone should size real
risk to it.

Win rates below 50% are expected here rather than a problem — the 3:1 target-to-stop
ratio means the strategy is built to be right less than half the time and still come
out ahead.

## Risk controls

- **1% equity risk per trade**, sized off the stop distance.
- **20× notional leverage cap.** Risk-based sizing can demand enormous notional when
  a stop is tight, and spread cost scales with notional rather than with risk. The
  cap binds in those cases, which means actual risk taken comes in *below* the 1%
  target — never above it.
- **3 bps round-trip spread** modeled on every backtested trade, so results are not
  quoted on frictionless fills.
- **Drawdown kill switch.** If equity falls to 70% of its baseline, trading halts and
  the tripped state is written to disk so it survives across runs — including on
  ephemeral CI runners, where nothing else persists.

## Live execution

`broker/live_fx_runner.py` runs on a GitHub Actions cron, firing during windows
around each session open. The cron windows are deliberately generous to cover both
EDT and EST; the actual gate is in the runner, which checks how long ago each
session opened and confirms OANDA reports the instrument as tradeable. Firing on a
weekend, holiday, or outside real session hours is a harmless no-op.

**The scheduler is not reliable, and the runner is built around that.** GitHub
delivers scheduled runs late and drops most of them: a cron asking for a run every
15 minutes produced about three runs a day, arriving at hours the cron never asked
for. The gate was originally an exact hour match (`now.hour == open_hour`), and the
combination was close to fatal — across a 60-run sample only 7 runs passed the gate,
every one of them Tokyo. London, the session this strategy is actually built around,
never fired once.

So the runner now accepts any session that opened within `SIGNAL_WINDOW_HOURS`
(default 3) rather than demanding an exact hour, which means a run delivered two
hours late still gets to act. Three guards keep that from turning into sloppy fills
or duplicate trades:

- **`MAX_SIGNAL_AGE_MINUTES`** (default 90) caps how stale a breakout can be and
  still be entered. The backtest assumes entry at the trigger price the moment it is
  breached; this bounds how far a live fill can drift from that assumption. A late
  run reports the stale signal and declines it rather than chasing the move.
- **`broker/signal_log.py`** records every signal acted on, keyed by session, pair,
  and trigger time. Without it, a signal whose bracket order already filled and
  closed would look untraded to the next run in the same window and get re-entered.
- The **open-position check** still blocks stacking a second entry onto a live position.

Credentials come from the `OANDA_API_TOKEN` and `OANDA_ACCOUNT_ID` environment
variables, supplied as GitHub Actions secrets. Nothing sensitive is committed.

Read requests to OANDA retry up to three times on transient failures; order
submission never retries, because a duplicate read costs nothing and a duplicate
order is a second position. A failed run opens a GitHub issue, since a run that dies
is otherwise invisible unless you happen to open the Actions tab — one transient 401
cost a New York session that way and went unnoticed for over a week.

## Run it

```bash
git clone https://github.com/vivi99-cmd/fx-trading-bot.git
cd fx-trading-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python run_fx_backtest.py
```

The backtest writes per-pair trade logs, a summary CSV, and equity-curve charts to
`results/`. No API key is needed — historical prices come from Yahoo Finance.

For live trading, set the two OANDA environment variables and run
`python broker/live_fx_runner.py --execute`. Without `--execute` it reports signals
without placing orders.

## Limitations

- **Yahoo Finance caps intraday history at 60 days**, which is the binding constraint
  on the whole backtest. A serious evaluation needs a paid intraday data source and
  several years of history.
- **No walk-forward or out-of-sample testing.** Parameters (buffer size, stop and
  target multiples, lookback windows) were chosen from reasoning about the strategy
  rather than fitted, but they have also never been validated on held-out data.
- **Spread is a flat assumption**, not a real bid/ask series. Real spreads widen at
  exactly the moments this strategy trades — session opens and news.
- **No slippage on stops.** Stop-outs are assumed to fill at the stop price, which is
  optimistic during fast moves.
- **Backtest fills are bar-based.** When a bar's range contains both the stop and the
  target, the engine has to assume an order of events it cannot observe at 15-minute
  resolution.

## Project structure

```
config.py                    pairs, session times, risk parameters, thresholds
data/fetch_fx_prices.py      intraday price download (yfinance)
strategies/session_breakout.py   range measurement and breakout detection
strategies/fx_utils.py       timezone handling (all logic runs in US/Eastern)
backtest/fx_engine.py        trade simulation, spread cost, currency conversion
backtest/fx_metrics.py       return, Sharpe, max drawdown, win rate
broker/oanda_connector.py    OANDA REST client (reads retry, writes never do)
broker/live_fx_runner.py     live signal generation and order placement
broker/kill_switch.py        persistent drawdown halt
broker/signal_log.py         record of signals already acted on, blocks re-entry
tests/test_kill_switch.py    kill switch unit tests
tests/test_session_window.py session gating and acted-signal log tests
run_fx_backtest.py           backtest entry point
```

Built as a personal project to learn intraday strategy research end to end —
data pipeline, strategy logic, backtesting with realistic costs, risk management,
and live deployment. It is not investment advice and is not a claim of edge.

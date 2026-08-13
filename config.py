# Narrowed from an original 10-pair basket after backtesting: only these two
# were breakeven-or-better with the session breakout strategy over the
# initial 60-day test. GBP_USD/USD_JPY/USD_CAD/NZD_USD were moderately
# negative and USD_CHF/EUR_GBP/EUR_JPY/GBP_JPY were badly negative -- see
# results/summary_2026-07-14_1948.csv for the full comparison.
PAIRS = [
    {"pair": "EUR_USD", "yf_ticker": "EURUSD=X", "base": "EUR", "quote": "USD"},
    {"pair": "AUD_USD", "yf_ticker": "AUDUSD=X", "base": "AUD", "quote": "USD"},
]

# How to convert 1 unit of a quote currency into USD (our account currency),
# using pairs we're already fetching. ("<pair to read a rate from>", "multiply"|"divide"|"identity")
# e.g. USD_JPY quotes JPY per USD, so a JPY amount / rate = USD amount ("divide").
# GBP_USD quotes USD per GBP, so a GBP amount * rate = USD amount ("multiply").
QUOTE_TO_USD = {
    "USD": (None, "identity"),
    "JPY": ("USD_JPY", "divide"),
    "CHF": ("USD_CHF", "divide"),
    "CAD": ("USD_CAD", "divide"),
    "GBP": ("GBP_USD", "multiply"),
}

# Same idea but for a pair's BASE currency -- needed to cap position notional
# in USD terms regardless of which currency the position is denominated in.
BASE_TO_USD = {
    "USD": (None, "identity"),
    "EUR": ("EUR_USD", "multiply"),
    "GBP": ("GBP_USD", "multiply"),
    "AUD": ("AUD_USD", "multiply"),
    "NZD": ("NZD_USD", "multiply"),
}

# yfinance intraday data: sub-daily intervals only go back 60 days max
INTERVAL = "15m"
PERIOD = "60d"

# Session open times in US/Eastern, and how many hours immediately before
# open to measure the pre-breakout range over. Chosen per the classic
# pairing (Asian range -> London breakout, London range -> NY breakout);
# Sydney/Tokyo use a simpler fixed lookback since there's no equivalently
# well-known preceding range for those two.
SESSIONS = {
    "sydney": {"open_hour_et": 17, "lookback_hours": 3},
    "tokyo": {"open_hour_et": 19, "lookback_hours": 2},
    "london": {"open_hour_et": 3, "lookback_hours": 8},
    "new_york": {"open_hour_et": 8, "lookback_hours": 5},
}

# How long after a session's open the live runner will still consider that
# session's breakout. This exists because GitHub Actions delivers scheduled
# runs late and drops most of them -- in one 60-run sample, only 7 landed in
# the exact ET open hour and London never fired at all. Matching on the exact
# open hour meant the bot was gated out of nearly every session it was
# scheduled for. Widening to a window is about surviving the scheduler, not
# about trading a different setup: the breakout itself is still only detected
# in the first hour after open (see strategies/session_breakout.py), and
# MAX_SIGNAL_AGE_MINUTES below is what actually bounds how stale an entry can be.
SIGNAL_WINDOW_HOURS = 3

# Hard staleness bound: never enter on a breakout whose trigger is older than
# this. The backtest assumes entry at the trigger price the moment it's
# breached; a late fill drifts from that assumption, so this caps the drift.
# Anything older is reported and skipped rather than traded.
MAX_SIGNAL_AGE_MINUTES = 90

INITIAL_CAPITAL = 1_000
RISK_PCT_PER_TRADE = 0.01  # fraction of equity risked per trade (based on stop-loss distance)
BREAKOUT_BUFFER_PCT = 0.0005  # price must clear the range by this fraction to count as a real breakout, not noise
STOP_LOSS_RANGE_MULT = 0.5  # stop-loss distance = this multiple of the measured range
TAKE_PROFIT_RANGE_MULT = 1.5  # take-profit distance = this multiple of the measured range
MAX_HOLD_HOURS = 8  # backstop: close the trade if neither stop nor target hit within this long

# Risk-based sizing (risk_amount / stop_distance) can produce huge notional
# when the stop is tight (common for thin pre-session ranges), which then
# makes spread cost -- which scales with notional, not risk -- eat a
# disproportionate chunk of the intended risk budget. This caps position
# notional at this multiple of account equity regardless of stop distance;
# when the cap binds, actual risk taken ends up below the 1% target (safer
# than intended, never riskier).
MAX_LEVERAGE = 20

SPREAD_PCT = 0.0003  # ~3 bps round-trip spread cost assumption, applied like slippage

OANDA_API_KEY_ENV = "OANDA_API_TOKEN"
OANDA_ACCOUNT_ID_ENV = "OANDA_ACCOUNT_ID"

# Kill switch: halts all trading and liquidates open positions if account
# value falls to this fraction of INITIAL_CAPITAL.
KILL_SWITCH_DRAWDOWN_PCT = 0.70

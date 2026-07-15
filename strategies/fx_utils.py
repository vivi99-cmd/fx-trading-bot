import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

ET = "US/Eastern"


def to_et(df):
    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.tz_convert(ET)
    return df


def _convert(currency: str, table: dict, rate_lookup, timestamp) -> float:
    pair_name, op = table[currency]
    if op == "identity":
        return 1.0
    rate = rate_lookup(pair_name, timestamp)
    if rate is None or rate == 0:
        return 1.0  # fallback: no data available, treat as roughly 1:1 rather than crash
    if op == "multiply":
        return rate
    if op == "divide":
        return 1.0 / rate
    raise ValueError(f"unknown conversion op: {op}")


def quote_to_usd_factor(quote_currency: str, rate_lookup, timestamp) -> float:
    """1 unit of quote_currency == this many USD, using a rate observed at/before timestamp."""
    return _convert(quote_currency, config.QUOTE_TO_USD, rate_lookup, timestamp)


def base_to_usd_factor(base_currency: str, rate_lookup, timestamp) -> float:
    """1 unit of base_currency == this many USD -- used to cap position notional in USD terms."""
    return _convert(base_currency, config.BASE_TO_USD, rate_lookup, timestamp)

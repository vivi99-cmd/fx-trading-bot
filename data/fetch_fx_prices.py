import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

import yfinance as yf

PRICES_DIR = Path(__file__).resolve().parent / "prices"
PRICES_DIR.mkdir(parents=True, exist_ok=True)


def fetch_pair(yf_ticker: str, interval: str = None, period: str = None, subdir: str = "prices"):
    interval = interval or config.INTERVAL
    period = period or config.PERIOD
    out_dir = Path(__file__).resolve().parent / subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    df = yf.download(yf_ticker, period=period, interval=interval, progress=False)
    if isinstance(df.columns, __import__("pandas").MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index.name = "datetime"
    df.to_csv(out_dir / f"{yf_ticker.replace('=', '_')}.csv")
    return df


def fetch_all(interval: str = None, period: str = None, subdir: str = "prices"):
    data = {}
    for p in config.PAIRS:
        print(f"Fetching {p['pair']} ({p['yf_ticker']})...")
        data[p["pair"]] = fetch_pair(p["yf_ticker"], interval=interval, period=period, subdir=subdir)
    return data


if __name__ == "__main__":
    fetch_all()

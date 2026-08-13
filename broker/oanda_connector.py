"""
Thin wrapper around OANDA's v20 REST API. Hardcoded to the practice
(demo/paper) environment -- there is no config flag or argument to switch
it to a live account. Get a free practice account and API token at
https://oanda.com (you sign up yourself; this code never does that for you).
"""
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

import time

import requests

BASE_URL = "https://api-fxpractice.oanda.com"

# Read requests get retried; writes never do. A duplicate GET is free, a
# duplicate order is a second position. Prompted by a run that died on a
# one-off 401 from OANDA during the New York session -- the token was fine
# before and after, so a single blip cost the only NY signal in a 60-run
# sample. 401 is included deliberately for that reason; if credentials are
# genuinely wrong every attempt fails and the error still surfaces.
RETRY_STATUS_CODES = {401, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2


def _get_with_retry(url: str, token: str, **kwargs):
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=_headers(token), timeout=10, **kwargs)
        except requests.RequestException as exc:
            last_error = exc
        else:
            if resp.status_code not in RETRY_STATUS_CODES:
                return resp
            last_error = requests.HTTPError(f"{resp.status_code} from {url}", response=resp)

        if attempt < MAX_ATTEMPTS:
            wait = RETRY_BACKOFF_SECONDS * attempt
            print(f"OANDA request failed ({last_error}), retry {attempt}/{MAX_ATTEMPTS - 1} in {wait}s")
            time.sleep(wait)

    if isinstance(last_error, requests.HTTPError) and last_error.response is not None:
        return last_error.response  # let the caller's raise_for_status report it
    raise last_error


def _get_credentials():
    token = os.environ.get(config.OANDA_API_KEY_ENV)
    account_id = os.environ.get(config.OANDA_ACCOUNT_ID_ENV)
    if not token or not account_id:
        raise RuntimeError(
            f"Set {config.OANDA_API_KEY_ENV} and {config.OANDA_ACCOUNT_ID_ENV} "
            "(free practice account credentials from your OANDA account) before using the broker connector."
        )
    return token, account_id


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_account_summary() -> dict:
    token, account_id = _get_credentials()
    resp = _get_with_retry(f"{BASE_URL}/v3/accounts/{account_id}/summary", token)
    resp.raise_for_status()
    return resp.json()["account"]


def get_pricing(instruments: list) -> dict:
    """Returns {instrument: {"bid":..., "ask":..., "tradeable": bool}}."""
    token, account_id = _get_credentials()
    resp = _get_with_retry(
        f"{BASE_URL}/v3/accounts/{account_id}/pricing",
        token,
        params={"instruments": ",".join(instruments)},
    )
    resp.raise_for_status()
    result = {}
    for p in resp.json()["prices"]:
        result[p["instrument"]] = {
            "bid": float(p["bids"][0]["price"]) if p.get("bids") else None,
            "ask": float(p["asks"][0]["price"]) if p.get("asks") else None,
            "tradeable": p["tradeable"],
        }
    return result


def get_open_position(instrument: str):
    """Returns None if flat, else {'direction': 'long'|'short', 'units': float}."""
    token, account_id = _get_credentials()
    resp = _get_with_retry(f"{BASE_URL}/v3/accounts/{account_id}/positions/{instrument}", token)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    position = resp.json()["position"]
    long_units = float(position["long"]["units"])
    short_units = float(position["short"]["units"])
    if long_units != 0:
        return {"direction": "long", "units": long_units}
    if short_units != 0:
        return {"direction": "short", "units": short_units}
    return None


def submit_bracket_market_order(instrument: str, units: int, stop_loss_price: float, take_profit_price: float) -> dict:
    """units: positive to buy/long, negative to sell/short."""
    token, account_id = _get_credentials()
    order = {
        "order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{stop_loss_price:.5f}"},
            "takeProfitOnFill": {"price": f"{take_profit_price:.5f}"},
        }
    }
    resp = requests.post(f"{BASE_URL}/v3/accounts/{account_id}/orders", headers=_headers(token), json=order, timeout=10)
    resp.raise_for_status()
    return resp.json()


def close_position(instrument: str, direction: str) -> dict:
    token, account_id = _get_credentials()
    payload = {"longUnits": "ALL"} if direction == "long" else {"shortUnits": "ALL"}
    resp = requests.put(
        f"{BASE_URL}/v3/accounts/{account_id}/positions/{instrument}/close",
        headers=_headers(token),
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def close_all_positions() -> list:
    token, account_id = _get_credentials()
    resp = _get_with_retry(f"{BASE_URL}/v3/accounts/{account_id}/openPositions", token)
    resp.raise_for_status()
    results = []
    for position in resp.json()["positions"]:
        instrument = position["instrument"]
        if float(position["long"]["units"]) != 0:
            results.append(close_position(instrument, "long"))
        if float(position["short"]["units"]) != 0:
            results.append(close_position(instrument, "short"))
    return results

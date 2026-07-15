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

import requests

BASE_URL = "https://api-fxpractice.oanda.com"


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
    resp = requests.get(f"{BASE_URL}/v3/accounts/{account_id}/summary", headers=_headers(token), timeout=10)
    resp.raise_for_status()
    return resp.json()["account"]


def get_pricing(instruments: list) -> dict:
    """Returns {instrument: {"bid":..., "ask":..., "tradeable": bool}}."""
    token, account_id = _get_credentials()
    resp = requests.get(
        f"{BASE_URL}/v3/accounts/{account_id}/pricing",
        headers=_headers(token),
        params={"instruments": ",".join(instruments)},
        timeout=10,
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
    resp = requests.get(f"{BASE_URL}/v3/accounts/{account_id}/positions/{instrument}", headers=_headers(token), timeout=10)
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
    resp = requests.get(f"{BASE_URL}/v3/accounts/{account_id}/openPositions", headers=_headers(token), timeout=10)
    resp.raise_for_status()
    results = []
    for position in resp.json()["positions"]:
        instrument = position["instrument"]
        if float(position["long"]["units"]) != 0:
            results.append(close_position(instrument, "long"))
        if float(position["short"]["units"]) != 0:
            results.append(close_position(instrument, "short"))
    return results

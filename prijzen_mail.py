import os
import ssl
import smtplib
from datetime import datetime
from email.message import EmailMessage

import requests


API_BASE_URL = "https://euenergy.live/api/v1/prices"
ZONE = "BE"
TIMEOUT_SECONDS = 30


def get_secret(name):
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(f"Secret ontbreekt of is leeg: {name}")

    return value


def get_prices(day):
    token = get_secret("EUENERGY_TOKEN")
    url = f"{API_BASE_URL}/{day}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "github-energy-prices/1.0",
    }

    print(f"Prijsdata downloaden voor: {day}")
    print(f"Zone: {ZONE}")
    print(f"Token aanwezig: {bool(token)}")
    print(f"Tokenlengte: {len(token)}")

    response = requests.get(
        url,
        params={"zone": ZONE},
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    )

    print(f"API-status met Bearer-token: {response.status_code}")

    if response.status_code in (401, 403):
        print("Bearer-token geweigerd; probeer token als queryparameter.")

        response = requests.get(
            url,
            params={
                "zone": ZONE,
                "token": token,
            },
            headers={
                "Accept": "application/json",
                "User-Agent": "github-energy-prices/1.0",
            },
            timeout=TIMEOUT_SECONDS,
        )

        print(f"API-status met query-token: {response.status_code}")

    if not response.ok:
        print(f"API-foutantwoord: {response.text[:500]}")
        response.raise_for_status()

    return response.json()


def records_from_response(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            return data["data"]

        if isinstance(data.get("prices"), list):
            return data["prices"]

        return [data]

    return []


def get_price(record):
    candidate_keys = [
        "price",
        "value",
        "eur_per_mwh",
        "price_eur_mwh",
        "eurMwh",
        "marketprice",
    ]

    for key in candidate_keys:
        if key in record:
            try:
                return float(record[key])
            except (TypeError, ValueError):
                pass

    return None


def get_time(record):
    candidate_keys = [
        "datetime",
        "timestamp",
        "time",
        "start",
        "start_time",
        "period_start",
        "from",
    ]

    for key in candidate_keys:
        if record.get(key):
            return str(record[key])

    return "Onbekend"


def format_price(price):
    if price is None:
        return "geen prijs"

    return f"EUR {price:.2f}/MWh"


def create_text_report(title, data):
    records =

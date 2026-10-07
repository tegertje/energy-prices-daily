import os
import ssl
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import requests


API_BASE_URL = "https://euenergy.live/api/v1/prices"
ZONE = "BE"
TIMEOUT_SECONDS = 30


def required_env(name: str) -> str:
    """Lees een verplichte environment variable zonder spaties."""
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(f"GitHub Secret ontbreekt of is leeg: {name}")

    return value


def get_prices(day: str):
    """
    Haal elektriciteitsprijzen op bij euenergy.live.

    Probeert eerst de aanbevolen Bearer-header.
    Bij 401/403 probeert het daarna de token als queryparameter.
    """
    token = required_env("EUENERGY_TOKEN")
    url = f"{API_BASE_URL}/{day}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "github-energy-prices/1.0",
    }

    print(f"Start prijsdata-download: {day}")
    print(f"Zone: {ZONE}")
    print(f"Token aanwezig: {bool(token)}")
    print(f"Tokenlengte: {len(token)}")

    response = requests.get(
        url,
        params={"zone": ZONE},
        headers=headers,
        timeout=TIMEOUT_SECONDS,
    )

    print(f"Bearer-aanvraag status: {response.status_code}")

    if response.status_code in (401, 403):
        print("Bearer-aanvraag geweigerd; probeer token als queryparameter.")

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

        print(f"Query-token-aanvraag status: {response.status_code}")

    if not response.ok:
        print(f"API-antwoord: {response.text[:500]}")
        response.raise_for_status()

    data = response.json()
    return data


def extract_records(data):
    """
    Ondersteunt mogelijke antwoordvormen:
    - lijst met records
    - {'data': [...]}
    - {'prices': [...]}
    - één record
    """
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            return data["data"]

        if isinstance(data.get("prices"), list):
            return data["prices"]

        return [data]

    raise ValueError("Onbekend API-antwoordformaat.")


def as_float(value):
    """Zet prijswaarde veilig om naar een float."""
    if value is None:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_price_value(record):
    """Zoek de prijs, ongeacht de veldnaam in het API-antwoord."""
    for key in (
        "price",
        "value",
        "eur_per_mwh",
        "price_eur_mwh",
        "eurMwh",
        "marketprice",
    ):
        if key in record:
            value = as_float(record[key])

            if value is not None:
                return value

    return None


def get_time_value(record):
    """Zoek de tijd of het tijdsinterval in een record."""
    for key in (
        "datetime",
        "timestamp",
        "time",
        "start",
        "start_time",
        "period_start",
        "from",
    ):
        if key in record and record[key]:
            return str(record[key])

    return "Onbekend tijdstip"


def format_price(value):
    """Formatteer prijs als euro per MWh."""
    if value is None:
        return "—"

    return f"€ {value:.2f}/MWh"


def build_price_rows(records):
    """Maak HTML-tabelrijen en bereken min/max/gemiddelde."""
    rows = []
    values = []

    for record in records:
        if not isinstance(record, dict):
            continue

        price = get_price_value(record)
        timestamp = get_time_value(record)

        if price is not None:
            values.append(price)

        rows.append(
            f"""
            <tr>
              <td style="padding:8px;border-bottom:1px solid #e5e7eb;">{timestamp}</td>
              <td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:right;">
                {format_price(price)}
              </td>
            </tr>
            """
        )

    if not rows:
        rows.append(
            """
            <tr>
              <td colspan="2" style="padding:8px;">
                Geen prijsrecords ontvangen.
              </td>
            </tr>
            """
        )

    summary = {
        "count": len(values),
        "minimum": min(values) if values else None,
        "maximum": max(values) if values else None,
        "average": sum(values) / len(values) if values else None,
    }

    return "\n".join(rows), summary


def build_email_html(today_data, tomorrow_data):
    """Bouw de HTML-inhoud van de prijsmail."""
    today_records = extract_records(today_data)
    tomorrow_records = extract_records(tomorrow_data)

    today_rows, today_summary = build_price_rows(today_records)
    tomorrow_rows, tomorrow_summary = build_price_rows(tomorrow_records)

    generated_at = datetime.now(timezone.utc).strftime("%d-%m-%Y %H:%M UTC")

    return f"""

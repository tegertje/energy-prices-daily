import os
import ssl
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import requests


API_BASE_URL = "https://api.energy-charts.info"
BIDDING_ZONE = "BE"
TIMEOUT_SECONDS = 30
BELGIUM_TIMEZONE = ZoneInfo("Europe/Brussels")


def get_secret(name):
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(f"GitHub Secret ontbreekt of is leeg: {name}")

    return value


def request_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers={
            "Accept": "application/json",
            "User-Agent": "energy-prices-daily-github-action/1.0",
        },
        timeout=TIMEOUT_SECONDS,
    )

    print(f"URL: {response.url}")
    print(f"API-status: {response.status_code}")

    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").lower()

    if "application/json" not in content_type:
        raise RuntimeError(
            "Energy-Charts gaf geen JSON terug. "
            f"Ontvangen Content-Type: {content_type}"
        )

    data = response.json()

    if isinstance(data, dict):
        print(f"API-velden: {list(data.keys())}")

    return data


def get_prices_for_date(date_value):
    date_text = date_value.isoformat()

    print(f"Prijsdata downloaden voor: {date_text}")

    return request_json(
        f"{API_BASE_URL}/price",
        params={
            "bzn": BIDDING_ZONE,
            "start": date_text,
            "end": date_text,
        },
    )


def empty_price_data():
    return {
        "unix_seconds": [],
        "price": [],
    }


def get_tomorrow_prices(tomorrow_date):
    print(f"Prijsdata downloaden voor morgen: {tomorrow_date.isoformat()}")

    try:
        return request_json(
            f"{API_BASE_URL}/price_next_day",
            params={
                "bzn": BIDDING_ZONE,
            },
        )

    except requests.HTTPError as error:
        response = error.response

        if response is not None and response.status_code == 404:
            print(
                "Prijzen voor morgen zijn nog niet gepubliceerd. "
                "De e-mail wordt toch verstuurd."
            )

            return empty_price_data()

        raise


def get_series(data):
    if not isinstance(data, dict):
        raise ValueError("Onverwacht antwoordformaat van Energy-Charts.")

    timestamps = data.get("unix_seconds")

    if timestamps is None:
        timestamps = data.get("timestamps")

    if timestamps is None:
        timestamps = data.get("time")

    if timestamps is None:
        timestamps = []

    prices = data.get("price")

    if prices is None:
        prices = data.get("values")

    if prices is None:
        prices = data.get("data")

    if isinstance(prices, dict):
        prices = prices.get("price")

        if prices is None:
            prices = prices.get("values")

        if prices is None:
            prices = prices.get("data")

    if timestamps is None:
        timestamps = []

    if prices is None:
        prices = []

    if not isinstance(timestamps, list):
        timestamps = list(timestamps)

    if not isinstance(prices, list):
        prices = list(prices)

    print(f"Aantal timestamps: {len(timestamps)}")
    print(f"Aantal prijzen: {len(prices)}")

    return timestamps, prices


def format_timestamp(timestamp):
    try:
        timestamp_value = float(timestamp)

        if timestamp_value > 10_000_000_000:
            timestamp_value = timestamp_value / 1000

        local_time = datetime.fromtimestamp(
            timestamp_value,
            tz=BELGIUM_TIMEZONE,
        )

        return local_time.strftime("%d-%m-%Y %H:%M")

    except (TypeError, ValueError, OSError, OverflowError):
        return str(timestamp)


def format_price(price):
    if price is None:
        return "geen prijs"

    try:
        return f"EUR {float(price):.2f}/MWh"
    except (TypeError, ValueError):
        return str(price)


def create_text_report(title, data):
    timestamps, prices = get_series(data)

    lines = [
        title,
        "=" * len(title),
    ]

    numeric_prices = []
    row_count = min(len(timestamps), len(prices))

    if row_count == 0:
        lines.append("Geen prijsgegevens ontvangen.")
        return "\n".join(lines)

    for index in range(row_count):
        timestamp = format_timestamp(timestamps[index])
        raw_price = prices[index]

        try:
            price = float(raw_price)
            numeric_prices.append(price)
            price_text = format_price(price)
        except (TypeError, ValueError):
            price_text = format_price(raw_price)

        lines.append(f"{timestamp}: {price_text}")

    if not numeric_prices:
        lines.append("")
        lines.append("Geen bruikbare numerieke prijzen ontvangen.")
        return "\n".join(lines)

    average_price = sum(numeric_prices) / len(numeric_prices)

    lines.append("")
    lines.append(f"Aantal intervallen: {len(numeric_prices)}")
    lines.append(f"Minimum: {format_price(min(numeric_prices))}")
    lines.append(f"Maximum: {format_price(max(numeric_prices))}")
    lines.append(f"Gemiddelde: {format_price(average_price)}")

    return "\n".join(lines)


def send_email(subject, body):
    email_to = get_secret("EMAIL_TO")
    email_from = get_secret("EMAIL_FROM")
    smtp_server = get_secret("SMTP_SERVER")
    smtp_port = int(get_secret("SMTP_PORT"))
    smtp_user = get_secret("SMTP_USER")
    smtp_pass = get_secret("SMTP_PASS")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = email_from
    message["To"] = email_to
    message.set_content(body)

    ssl_context = ssl.create_default_context()

    print(f"E-mail versturen naar: {email_to}")
    print(f"SMTP-server: {smtp_server}:{smtp_port}")

    if smtp_port == 465:
        with smtplib.SMTP_SSL(
            smtp_server,
            smtp_port,
            context=ssl_context,
            timeout=30,
        ) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(message)
    else:
        with smtplib.SMTP(
            smtp_server,
            smtp_port,
            timeout=30,
        ) as server:
            server.ehlo()
            server.starttls(context=ssl_context)
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.send_message(message)

    print("E-mail succesvol verstuurd.")


def main():
    now = datetime.now(BELGIUM_TIMEZONE)
    today_date = now.date()
    tomorrow_date = today_date + timedelta(days=1)

    today_label = today_date.strftime("%d-%m-%Y")
    tomorrow_label = tomorrow_date.strftime("%d-%m-%Y")

    print("Start Energy-Charts prijsdata-download")
    print(f"Biedzone: {BIDDING_ZONE}")

    today_data = get_prices_for_date(today_date)
    tomorrow_data = get_tomorrow_prices(tomorrow_date)

    today_report = create_text_report(
        f"Elektriciteitsprijzen België - vandaag ({today_label})",
        today_data,
    )

    tomorrow_report = create_text_report(
        f"Elektriciteitsprijzen België - morgen ({tomorrow_label})",
        tomorrow_data,
    )

    generated_at = now.strftime("%d-%m-%Y %H:%M %Z")

    email_body = (
        "Dagelijkse day-ahead elektriciteitsprijzen voor België.\n"
        "Eenheid: EUR per MWh.\n\n"
        f"{today_report}\n\n"
        f"{tomorrow_report}\n\n"
        "Gegevensbron: Energy-Charts / Fraunhofer ISE.\n"
        f"Gegenereerd op: {generated_at}"
    )

    subject = f"Elektriciteitsprijzen België - {today_label}"

    send_email(subject, email_body)


if __name__ == "__main__":
    main()

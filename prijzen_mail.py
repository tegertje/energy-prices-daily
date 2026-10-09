import os
import ssl
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

import requests


API_BASE_URL = "https://api.energy-charts.info/v2"
BIDDING_ZONE = "BE"
TIMEOUT_SECONDS = 30
BELGIUM_TIMEZONE = ZoneInfo("Europe/Brussels")


def get_secret(name):
    value = os.getenv(name, "").strip()

    if not value:
        raise RuntimeError(f"GitHub Secret ontbreekt of is leeg: {name}")

    return value


def request_json(endpoint, params=None):
    url = f"{API_BASE_URL}/{endpoint}"

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

    return response.json()


def get_prices_for_date(date_value):
    date_text = date_value.isoformat()

    print(f"Prijsdata downloaden voor: {date_text}")

    return request_json(
        "price",
        params={
            "bzn": BIDDING_ZONE,
            "start": date_text,
            "end": date_text,
        },
    )


def get_tomorrow_prices():
    print("Day-ahead-prijzen voor morgen downloaden.")

    try:
        return request_json(
            "price_next_day",
            params={
                "bzn": BIDDING_ZONE,
            },
        )

    except requests.HTTPError as error:
        response = error.response

        if response is not None and response.status_code == 404:
            print(
                "Day-ahead-prijzen voor morgen zijn nog niet gepubliceerd."
            )
            return None

        raise


def get_series(api_response):
    """
    Energy-Charts v2 gebruikt een envelope met datarecords:
    {
        "data": [
            {
                "timestamp": "...",
                "values": {"price": 123.45}
            }
        ]
    }
    """
    if not isinstance(api_response, dict):
        raise ValueError("Onverwacht antwoordformaat van Energy-Charts.")

    records = api_response.get("data", [])

    if not isinstance(records, list):
        raise ValueError("Het veld 'data' is geen lijst.")

    timestamps = []
    prices = []

    for record in records:
        if not isinstance(record, dict):
            continue

        timestamp = record.get("timestamp")
        values = record.get("values", {})

        if timestamp is None or not isinstance(values, dict):
            continue

        price = values.get("price")

        # Gebruik een enige waardenreeks als de API-serienaam anders is.
        if price is None and len(values) == 1:
            price = next(iter(values.values()))

        if price is None:
            continue

        timestamps.append(timestamp)
        prices.append(price)

    print(f"Aantal prijsintervallen in API-respons: {len(prices)}")

    return timestamps, prices


def format_timestamp(timestamp):
    if isinstance(timestamp, str):
        try:
            parsed = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=BELGIUM_TIMEZONE)

            return parsed.astimezone(BELGIUM_TIMEZONE).strftime(
                "%d-%m-%Y %H:%M"
            )

        except ValueError:
            return timestamp

    try:
        value = float(timestamp)

        if value > 10_000_000_000:
            value /= 1000

        return datetime.fromtimestamp(
            value,
            tz=BELGIUM_TIMEZONE,
        ).strftime("%d-%m-%Y %H:%M")

    except (TypeError, ValueError, OSError, OverflowError):
        return str(timestamp)


def format_price(price):
    try:
        return f"EUR {float(price):.2f}/MWh"
    except (TypeError, ValueError):
        return "geen prijs"


def create_text_report(title, api_response):
    if api_response is None:
        return "\n".join(
            [
                title,
                "=" * len(title),
                "Day-ahead-prijzen voor morgen zijn nog niet beschikbaar.",
            ]
        )

    timestamps, prices = get_series(api_response)

    lines = [
        title,
        "=" * len(title),
    ]

    if not prices:
        lines.append("Geen prijsgegevens ontvangen.")
        return "\n".join(lines)

    numeric_prices = []

    for timestamp, raw_price in zip(timestamps, prices):
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            continue

        numeric_prices.append(price)
        lines.append(
            f"{format_timestamp(timestamp)}: {format_price(price)}"
        )

    if not numeric_prices:
        lines.append("Geen bruikbare numerieke prijzen ontvangen.")
        return "\n".join(lines)

    average_price = sum(numeric_prices) / len(numeric_prices)

    lines.extend(
        [
            "",
            f"Aantal intervallen: {len(numeric_prices)}",
            f"Minimum: {format_price(min(numeric_prices))}",
            f"Maximum: {format_price(max(numeric_prices))}",
            f"Gemiddelde: {format_price(average_price)}",
        ]
    )

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
    today = now.date()
    tomorrow = today + timedelta(days=1)

    today_label = today.strftime("%d-%m-%Y")
    tomorrow_label = tomorrow.strftime("%d-%m-%Y")

    print("Start Energy-Charts prijsdata-download")
    print(f"Biedzone: {BIDDING_ZONE}")
    print(
        "Workflow gestart om:",
        now.strftime("%d-%m-%Y %H:%M:%S %Z"),
    )

    today_data = get_prices_for_date(today)
    tomorrow_data = get_tomorrow_prices()

    today_report = create_text_report(
        f"Elektriciteitsprijzen België - vandaag ({today_label})",
        today_data,
    )

    tomorrow_report = create_text_report(
        f"Elektriciteitsprijzen België - morgen ({tomorrow_label})",
        tomorrow_data,
    )

    generated_at = datetime.now(BELGIUM_TIMEZONE).strftime(
        "%d-%m-%Y %H:%M %Z"
    )

    email_body = (
        "Dagelijkse day-ahead elektriciteitsprijzen voor België.\n"
        "Eenheid: EUR per MWh.\n\n"
        f"{today_report}\n\n"
        f"{tomorrow_report}\n\n"
        "Gegevensbron: Energy-Charts / Fraunhofer ISE.\n"
        "Licentie: Energy-Charts vermeldt per biedzone de toepasselijke "
        "licentie; controleer die voor herpublicatie.\n"
        f"Gegenereerd op: {generated_at}"
    )

    subject = f"Elektriciteitsprijzen België - {today_label}"

    print(
        "E-mail wordt verstuurd om:",
        datetime.now(BELGIUM_TIMEZONE).strftime(
            "%d-%m-%Y %H:%M:%S %Z"
        ),
    )

    send_email(subject, email_body)


if __name__ == "__main__":
    main()

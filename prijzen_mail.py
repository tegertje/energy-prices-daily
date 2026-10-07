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
        "User-Agent": "Mozilla/5.0",
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

    print(f"API-status: {response.status_code}")
    print(f"Content-Type: {response.headers.get('content-type', '')}")

    if "text/html" in response.headers.get("content-type", "").lower():
        print("De API gaf HTML terug in plaats van JSON.")
        print("Waarschijnlijk is de aanvraag door Cloudflare geblokkeerd.")
        raise RuntimeError(
            "euenergy.live retourneerde een Cloudflare-beveiligingspagina."
        )

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
    records = records_from_response(data)
    prices = []
    lines = [title, "-" * len(title)]

    for record in records:
        if not isinstance(record, dict):
            continue

        timestamp = get_time(record)
        price = get_price(record)

        if price is not None:
            prices.append(price)

        lines.append(f"{timestamp}: {format_price(price)}")

    if not prices:
        lines.append("")
        lines.append("Geen bruikbare prijsgegevens ontvangen.")
        return "\n".join(lines)

    average_price = sum(prices) / len(prices)

    summary = [
        "",
        f"Aantal uren: {len(prices)}",
        f"Minimum: {format_price(min(prices))}",
        f"Maximum: {format_price(max(prices))}",
        f"Gemiddelde: {format_price(average_price)}",
    ]

    return "\n".join(lines + summary)


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

    context = ssl.create_default_context()

    print(f"E-mail versturen naar: {email_to}")
    print(f"SMTP-server: {smtp_server}:{smtp_port}")

    if smtp_port == 465:
        with smtplib.SMTP_SSL(
            smtp_server,
            smtp_port,
            context=context,
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
            server.starttls(context=context)
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.send_message(message)

    print("E-mail succesvol verstuurd.")


def main():
    print("Start prijsdata-download")

    today_data = get_prices("today")
    tomorrow_data = get_prices("tomorrow")

    today_report = create_text_report("Elektriciteitsprijzen België - vandaag", today_data)
    tomorrow_report = create_text_report(
        "Elektriciteitsprijzen België - morgen",
        tomorrow_data,
    )

    created_at = datetime.now().strftime("%d-%m-%Y %H:%M")

    email_body = (
        "Dagelijkse elektriciteitsprijzen voor België (zone BE)\n\n"
        f"{today_report}\n\n"
        f"{tomorrow_report}\n\n"
        f"Gegevensbron: euenergy.live\n"
        f"Gegenereerd op: {created_at}"
    )

    subject = f"Elektriciteitsprijzen België - {datetime.now().strftime('%d-%m-%Y')}"

    send_email(subject, email_body)


if __name__ == "__main__":
    main()

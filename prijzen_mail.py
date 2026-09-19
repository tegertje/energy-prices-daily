import datetime as dt
import html
import os
import smtplib

import requests

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo


EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ["EMAIL_FROM"]
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]
EUENERGY_TOKEN = os.environ["EUENERGY_TOKEN"]

TIMEZONE = ZoneInfo("Europe/Brussels")
ZONE = "BE"
API_BASE = "https://euenergy.live/api/v1"


def get_prices(day_name):
    url = f"{API_BASE}/prices/{day_name}"
    response = requests.get(
        url,
        params={"zone": ZONE},
        headers={"Authorization": f"Bearer {EUENERGY_TOKEN}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = (
            data.get("prices")
            or data.get("data")
            or data.get("results")
            or data.get("items")
        )
    else:
        records = None

    if not isinstance(records, list):
        raise ValueError(
            f"Onverwacht antwoord van euenergy voor {day_name}: {data}"
        )

    return records


def get_datetime(record):
    value = (
        record.get("datetime")
        or record.get("timestamp")
        or record.get("start")
        or record.get("time")
        or record.get("date")
    )

    if value is None:
        raise ValueError(f"Geen tijdstip gevonden: {record}")

    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).astimezone(TIMEZONE)

    text = str(value).replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)

    return parsed.astimezone(TIMEZONE)


def get_price_eur_mwh(record):
    for key in (
        "price_eur_mwh",
        "priceEurMwh",
        "eur_mwh",
        "price",
        "value",
    ):
        if record.get(key) is not None:
            return float(record[key])

    raise ValueError(f"Geen prijs gevonden: {record}")


def normalize_prices(records):
    prices = []

    for record in records:
        timestamp = get_datetime(record)
        price_kwh = get_price_eur_mwh(record) / 1000
        prices.append((timestamp, price_kwh))

    return sorted(prices, key=lambda item: item[0])


def make_text_section(title, prices):
    lines = [
        title,
        "Uur                  | Prijs (€/kWh)",
        "---------------------|--------------",
    ]

    for timestamp, price_kwh in prices:
        lines.append(f"{timestamp.strftime('%Y-%m-%d %H:%M')} | {price_kwh:.4f}")

    return "\n".join(lines)


def make_html_section(title, prices):
    rows = []

    for timestamp, price_kwh in prices:
        rows.append(
            "<tr>"
            f"<td>{html.escape(timestamp.strftime('%Y-%m-%d %H:%M'))}</td>"
            f"<td>{price_kwh:.4f}</td>"
            "</tr>"
        )

    return f"""
    <h3>{html.escape(title)}</h3>
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse:collapse">
      <tr>
        <th>Uur</th>
        <th>Prijs (€/kWh)</th>
      </tr>
      {''.join(rows)}
    </table>
    """


def main():
    now = dt.datetime.now(TIMEZONE)

    today_prices = normalize_prices(get_prices("today"))
    tomorrow_prices = normalize_prices(get_prices("tomorrow"))

    text_body = "\n\n".join([
        "Dynamische stroomprijzen — België (EPEX Spot)",
        f"Opgehaald op {now.strftime('%Y-%m-%d %H:%M')} (Europe/Brussels)",
        "",
        make_text_section("VANDAAG", today_prices),
        make_text_section("MORGEN", tomorrow_prices),
        "",
        "Dit zijn EPEX Spot-marktprijzen, zonder Trevion-marge, btw, heffingen of nettarieven.",
    ])

    html_body = f"""
    <html>
      <body>
        <h2>Dynamische stroomprijzen — België (EPEX Spot)</h2>
        <p>Opgehaald op {now.strftime('%Y-%m-%d %H:%M')} (Europe/Brussels).</p>
        {make_html_section("Vandaag", today_prices)}
        {make_html_section("Morgen", tomorrow_prices)}
        <p><small>
          Dit zijn EPEX Spot-marktprijzen, zonder Trevion-marge, btw,
          heffingen of nettarieven.
        </small></p>
      </body>
    </html>
    """

    message = MIMEMultipart("alternative")
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO
    message["Subject"] = "Dynamische stroomprijzen België — vandaag en morgen"
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(message)


if __name__ == "__main__":
    main()

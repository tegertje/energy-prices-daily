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

LIFEPOWR_BELPEX_FACTOR = 0.10
LIFEPOWR_MARGIN_CENT_KWH = 1.30
VAT_FACTOR = 1.06

GREEN_ELECTRICITY_EUR_KWH = 0.01100
WKK_EUR_KWH = 0.00420


def get_prices(day_name):
    url = f"{API_BASE}/prices/{day_name}"

    response = requests.get(
        url,
        params={"zone": ZONE},
        headers={"Authorization": f"Bearer {EUENERGY_TOKEN}"},
        timeout=30,
    )

    if response.status_code == 425:
        return None, (
            "De prijzen voor morgen zijn nog niet gepubliceerd "
            "door euenergy.live."
        )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        return data, None

    if isinstance(data, dict):
        records = (
            data.get("prices")
            or data.get("data")
            or data.get("results")
            or data.get("items")
        )

        if isinstance(records, list):
            return records, None

        hours = data.get("hours")

        if isinstance(hours, list):
            return hours, None

    raise ValueError(
        f"Onverwacht antwoord van euenergy voor {day_name}: {data}"
    )


def get_datetime(record):
    value = (
        record.get("datetime")
        or record.get("timestamp")
        or record.get("start")
        or record.get("time")
        or record.get("date")
        or record.get("ts")
    )

    if value is None:
        raise ValueError(f"Geen tijdstip gevonden: {record}")

    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(
            value,
            tz=dt.timezone.utc,
        ).astimezone(TIMEZONE)

    text = str(value).replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)

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


def calculate_prices(spot_eur_mwh):
    spot_eur_kwh = spot_eur_mwh / 1000

    lifepowr_cent_kwh = (
        LIFEPOWR_BELPEX_FACTOR * spot_eur_mwh
        + LIFEPOWR_MARGIN_CENT_KWH
    ) * VAT_FACTOR

    lifepowr_eur_kwh = lifepowr_cent_kwh / 100

    green_wkk_eur_kwh = (
        GREEN_ELECTRICITY_EUR_KWH
        + WKK_EUR_KWH
    )

    subtotal_eur_kwh = (
        lifepowr_eur_kwh
        + green_wkk_eur_kwh
    )

    return (
        spot_eur_kwh,
        lifepowr_eur_kwh,
        green_wkk_eur_kwh,
        subtotal_eur_kwh,
    )


def normalize_prices(records):
    prices = []

    for record in records:
        timestamp = get_datetime(record)
        spot_eur_mwh = get_price_eur_mwh(record)

        (
            spot_eur_kwh,
            lifepowr_eur_kwh,
            green_wkk_eur_kwh,
            subtotal_eur_kwh,
        ) = calculate_prices(spot_eur_mwh)

        prices.append({
            "time": timestamp,
            "spot": spot_eur_kwh,
            "lifepowr": lifepowr_eur_kwh,
            "green_wkk": green_wkk_eur_kwh,
            "subtotal": subtotal_eur_kwh,
        })

    return sorted(prices, key=lambda item: item["time"])


def make_text_section(title, prices, message=None):
    if prices is None:
        return f"{title}\n{message}"

    lines = [
        title,
        "Uur                  | EPEX   | LIFEPOWR | Groen+WKK | Subtotaal",
        "---------------------|--------|----------|-----------|----------",
    ]

    for item in prices:
        timestamp = item["time"].strftime("%Y-%m-%d %H:%M")

        lines.append(
            f"{timestamp} | "
            f"{item['spot']:.4f} | "
            f"{item['lifepowr']:.4f} | "
            f"{item['green_wkk']:.4f} | "
            f"{item['subtotal']:.4f}"
        )

    return "\n".join(lines)


def make_html_section(title, prices, message=None):
    if prices is None:
        return (
            "<h3>"
            + html.escape(title)
            + "</h3><p>"
            + html.escape(message)
            + "</p>"
        )

    rows = []

    for item in prices:
        timestamp = item["time"].strftime("%Y-%m-%d %H:%M")

        row = (
            "<tr>"
            "<td>" + html.escape(timestamp) + "</td>"
            f"<td>{item['spot']:.4f}</td>"
            f"<td>{item['lifepowr']:.4f}</td>"
            f"<td>{item['green_wkk']:.4f}</td>"
            f"<td><b>{item['subtotal']:.4f}</b></td>"
            "</tr>"
        )

        rows.append(row)

    rows_text = "".join(rows)

    return (
        "<h3>"
        + html.escape(title)
        + "</h3>"
        + "<table border='1' cellpadding='5' cellspacing='0' "
        + "style='border-collapse:collapse;'>"
        + "<tr>"
        + "<th>Uur</th>"
        + "<th>EPEX Spot<br>(EUR/kWh)</th>"
        + "<th>LIFEPOWR energie<br>incl. 6% btw</th>"
        + "<th>Groene stroom<br>+ WKK</th>"
        + "<th>Subtotaal energie<br>(EUR/kWh)</th>"
        + "</tr>"
        + rows_text
        + "</table>"
    )


def main():
    print("Starting price-data download")

    now = dt.datetime.now(TIMEZONE)

    today_records, today_message = get_prices("today")
    tomorrow_records, tomorrow_message = get_prices("tomorrow")

    print("Price-data download completed")

    today_prices = None
    if today_records is not None:
        today_prices = normalize_prices(today_records)

    tomorrow_prices = None
    if tomorrow_records is not None:
        tomorrow_prices = normalize_prices(tomorrow_records)

    print("Price calculations completed")

    text_body_parts = [
        "Dynamische stroomprijzen Belgie",
        "LIFEPOWR by Trevion - prijsraming per uur",
        (
            "Opgehaald op "
            + now.strftime("%Y-%m-%d %H:%M")
            + " (Europe/Brussels)"
        ),
        "",
        make_text_section("VANDAAG", today_prices, today_message),
        "",
        make_text_section("MORGEN", tomorrow_prices, tomorrow_message),
        "",
        "LIFEPOWR-formule incl. 6% btw:",
        "(0.1 x Belpex 15 MTU + 1.3 cEUR/kWh) x 1.06",
        "",
        "Groene stroom + WKK: 0.0152 EUR/kWh.",
        (
            "Subtotaal energie = LIFEPOWR dynamische energieprijs "
            "+ groene stroom + WKK."
        ),
        (
            "Niet inbegrepen: Fluvius-netkosten, afnametarief, "
            "capaciteitstarief, vaste vergoeding, accijnzen, "
            "energiefonds en eventuele FlexiO-vergoeding."
        ),
        "Bron EPEX: euenergy.live (CC BY-4.0).",
    ]

    text_body = "\n".join(text_body_parts)

    today_html = make_html_section(
        "Vandaag",
        today_prices,
        today_message,
    )

    tomorrow_html = make_html_section(
        "Morgen",
        tomorrow_prices,
        tomorrow_message,
    )

    html_body_parts = [
        "<html><body>",
        "<h2>Dynamische stroomprijzen Belgie</h2>",
        "<p>",
        "<b>LIFEPOWR by Trevion - prijsraming per uur</b><br>",
        "Opgehaald op "
        + now.strftime("%Y-%m-%d %H:%M")
        + " (Europe/Brussels).",
        "</p>",
        today_html,
        tomorrow_html,
        "<p><small>",
        "<b>LIFEPOWR-formule incl. 6% btw:</b><br>",
        "(0.1 x Belpex 15 MTU + 1.3 cEUR/kWh) x 1.06.<br><br>",
        "<b>Groene stroom + WKK:</b> 0.0152 EUR/kWh.<br><br>",
        "<b>Subtotaal energie:</b> LIFEPOWR energieprijs ",
        "+ groene stroom + WKK.<br><br>",
        "Niet inbegrepen: Fluvius-netkosten, afnametarief, ",
        "capaciteitstarief, vaste vergoeding, accijnzen, ",
        "energiefonds en eventuele FlexiO-vergoeding.<br><br>",
        "Bron EPEX: ",
        "<a href='https://euenergy.live/'>euenergy.live</a> ",
        "(CC BY-4.0).",
        "</small></p>",
        "</body></html>",
    ]

    html_body = "".join(html_body_parts)

    message = MIMEMultipart("alternative")
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO
    message["Subject"] = (
        "LIFEPOWR by Trevion - dynamische prijzen vandaag en morgen"
    )

    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    print("Email message created")
    print("Starting SMTP delivery test")
    print("Attempting connection to Gmail SMTP")

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        print("Connected to Gmail SMTP")

        server.starttls()
        print("TLS connection established")

        server.login(SMTP_USER, SMTP_PASS)
        print("SMTP login accepted")

        server.send_message(message)
        print("Message accepted by Gmail SMTP")

    print("Email send operation completed")


if __name__ == "__main__":
    main()

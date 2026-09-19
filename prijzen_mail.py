import datetime as dt
import html
import os
import smtplib

import requests

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo


# ============================================================
# E-MAIL EN API-INSTELLINGEN
# Alle waarden komen uit GitHub Actions Secrets.
# ============================================================

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


# ============================================================
# LIFEPOWR BY TREVION - DYNAMISCHE ENERGIEFORMULE
#
# Officiële tariefkaart:
# (0,1 x Belpex 15 MTU + 1,3) x 1,06
#
# Belpex: EUR/MWh.
# Resultaat formule: cEUR/kWh.
# ============================================================

LIFEPOWR_BELPEX_FACTOR = 0.10
LIFEPOWR_MARGIN_CENT_KWH = 1.30
VAT_FACTOR = 1.06


# ============================================================
# COMPONENTEN UIT JOUW AUGUSTUS 2026-FACTUUR
#
# Groene stroom: 1,100 cEUR/kWh
# WKK:            0,420 cEUR/kWh
# ============================================================

GREEN_ELECTRICITY_EUR_KWH = 0.01100
WKK_EUR_KWH = 0.00420


def get_prices(day_name):
    """
    Haalt Belgische EPEX/Belpex-prijzen op voor vandaag of morgen.
    Status 425 betekent dat de data voor morgen nog niet beschikbaar is.
    """
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
    """
    Leest een API-tijdstip en zet het om naar Brussels tijd.
    euenergy gebruikt meestal het veld 'ts'.
    """
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
    """
    Leest de marktprijs in EUR/MWh uit de API-respons.
    """
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


def lifepowr_prices(spot_eur_mwh):
    """
    Berekent de LIFEPOWR-prijscomponenten per kWh.

    Officiële formule:
        (0,1 x Belpex 15 MTU + 1,3) x 1,06

    De formule geeft cent/kWh terug. Daarom delen we door 100
    om EUR/kWh te krijgen.
    """
    spot_eur_kwh = spot_eur_mwh / 1000

    lifepowr_energy_cent_kwh = (
        LIFEPOWR_BELPEX_FACTOR * spot_eur_mwh
        + LIFEPOWR_MARGIN_CENT_KWH
    ) * VAT_FACTOR

    lifepowr_energy_eur_kwh = (
        lifepowr_energy_cent_kwh / 100
    )

    green_and_wkk_eur_kwh = (
        GREEN_ELECTRICITY_EUR_KWH
        + WKK_EUR_KWH
    )

    energy_subtotal_eur_kwh = (
        lifepowr_energy_eur_kwh
        + green_and_wkk_eur_kwh
    )

    return (
        spot_eur_kwh,
        lifepowr_energy_eur_kwh,
        green_and_wkk_eur_kwh,
        energy_subtotal_eur_kwh,
    )


def normalize_prices(records):
    """
    Verwerkt de marktgegevens per uur.
    """
    prices = []

    for record in records:
        timestamp = get_datetime(record)
        spot_eur_mwh = get_price_eur_mwh(record)

        (
            spot_eur_kwh,
            lifepowr_energy_eur_kwh,
            green_and_wkk_eur_kwh,
            energy_subtotal_eur_kwh,
        ) = lifepowr_prices(spot_eur_mwh)

        prices.append((
            timestamp,
            spot_eur_kwh,
            lifepowr_energy_eur_kwh,
            green_and_wkk_eur_kwh,
            energy_subtotal_eur_kwh,
        ))

    return sorted(prices, key=lambda item: item[0])


def make_text_section(title, prices, message=None):
    """
    Bouwt de gewone tekstversie van de tabel.
    """
    if prices is None:
        return f"{title}\n{message}"

    lines = [
        title,
        (
            "Uur                  | EPEX Spot | LIFEPOWR energie | "
            "Groen+WKK | Subtotaal"
        ),
        (
            "---------------------|-----------|-------------------|"
            "-----------|----------"
        ),
    ]

    for timestamp, spot, lifepowr, green_wkk, subtotal in prices:
        lines.append(
            f"{timestamp.strftime('%Y-%m-%d %H:%M')} | "
            f"{spot:.4f} | "
            f"{lifepowr:.4f} | "
            f"{green_wkk:.4f} | "
            f"{subtotal:.4f}"
        )

    return "\n".join(lines)


def make_html_section(title, prices, message=None):
    """
    Bouwt de HTML-versie van de tabel voor Gmail.
    """
    if prices is None:
        return f"""
        <h3>{html.escape(title)}</h3>
        <p>{html.escape(message)}</p>
        """

    rows = []

    for timestamp, spot, lifepowr, green_wkk, subtotal in prices:
        rows.append(
            "<tr>"
            f"<td>{html.escape(timestamp.strftime('%Y-%m-%d %H:%M'))}</td>"
            f"<td>{spot:.4f}</td>"
            f"<td>{lifepowr:.4f}</td>"
            f"<td>{green_wkk:.4f}</td>"
            f"<td><b>{subtotal:.4f}</b></td>"
            "</tr>"
        )

    return f"""
    <h3>{html.escape(title)}</h3>
    <table border="1" cellpadding="5" cellspacing="0"
           style="border-collapse: collapse;">
      <tr>
        <th>Uur</th>
        <th>EPEX Spot<br>(EUR/kWh)</th>
        <th>LIFEPOWR energie<br>incl. 6% btw</th>
        <th>Groene stroom<br>+ WKK</th>
        <th>Subtotaal energie<br>(EUR/kWh)</th>
      </tr>
      {''.join(rows)}
    </table>
    """


def main():
    print("Starting price-data download")

    now = dt.datetime.now(TIMEZONE)

    today_records, today_message = get_prices("today")
    tomorrow_records, tomorrow_message = get_prices("tomorrow")

    print("Price-data download completed")

    today_prices = (
        normalize_prices(today_records)
        if today_records is not None
        else None
    )

    tomorrow_prices = (
        normalize_prices(tomorrow_records)
        if tomorrow_records is not None
        else None
    )

    print("Price calculations completed")

    text_body = "\n\n".join([
        "Dynamische stroomprijzen Belgie",
        "LIFEPOWR by Trevion - prijsraming per uur",
        f"Opgehaald op {now.strftime('%Y-%m-%d %H:%M')} (Europe/Brussels)",
        "",
        make_text_section("VANDAAG", today_prices, today_message),
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
    ])

    html_body = f"""
    <html>
      <body>
        <h2>Dynamische stroomprijzen Belgie</h2>
        <p>
          <b>LIFEPOWR by Trevion - prijsraming per uur</b><br>
          Opgehaald op {now.strftime('%Y-%m-%d %H:%M')}
          (Europe/Brussels).
        </p>

        {make_html_section("Vandaag", today_prices, today_message)}

        {make_html_section("Morgen", tomorrow_prices, tomorrow_message)}

        <p>
          <small>
            <b>LIFEPOWR-formule incl. 6% btw:</b><br>
            (0.1 x Belpex 15 MTU + 1.3 cEUR/kWh) x 1.06.<br><br>

            <b>Groene stroom + WKK:</b> 0.0152 EUR/kWh,
            op basis van je augustus 2026-factuur.<br><br>

            <b>Subtotaal energie:</b> LIFEPOWR energieprijs
            + groene stroom + WKK.<br>

            Niet inbegrepen: Fluvius-netkosten,

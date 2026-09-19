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

TIMEZONE = ZoneInfo("Europe/Brussels")
SUBJECT = "Dynamische stroomprijzen – België"

API_URL = "https://api.smartprice.be/api/prices"


def get_json(url):
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_prices(data):
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("prices", "hourly", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ValueError("Geen lijst met uurprijzen gevonden in de API-respons.")


def parse_datetime(item):
    value = (
        item.get("datetime")
        or item.get("date")
        or item.get("timestamp")
        or item.get("start")
        or item.get("time")
    )

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).astimezone(TIMEZONE)

    value = str(value).replace("Z", "+00:00")

    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TIMEZONE)

    return parsed.astimezone(TIMEZONE)


def parse_price_mwh(item):
    for key in (
        "price_eur_mwh",
        "price_mwh",
        "eur_mwh",
        "price",
        "value",
    ):
        value = item.get(key)
        if value is not None:
            return float(value)

    raise ValueError(f"Geen prijsveld gevonden in record: {item}")


def main():
    now = dt.datetime.now(TIMEZONE)
    start = now.replace(minute=0, second=0, microsecond=0)
    end = start + dt.timedelta(hours=24)

    data = get_json(API_URL)
    raw_prices = extract_prices(data)

    prices = []

    for item in raw_prices:
        if not isinstance(item, dict):
            continue

        timestamp = parse_datetime(item)
        if timestamp is None:
            continue

        if start <= timestamp < end:
            price_mwh = parse_price_mwh(item)
            prices.append((timestamp, price_mwh / 1000))

    prices.sort(key=lambda row: row[0])

    if not prices:
        raise ValueError(
            "De API leverde geen uurprijzen voor de komende 24 uur. "
            "Controleer het API-endpoint of de veldnamen."
        )

    lines = [
        f"Dynamische uurprijzen (EPEX Spot, België)",
        f"Opgehaald op {now.strftime('%Y-%m-%d %H:%M')} (Europe/Brussels)",
        "",
        "Prijs per uur (€/kWh):",
        "",
        "Uur                  | Prijs (€/kWh)",
        "---------------------|--------------",
    ]

    html_rows = []

    for timestamp, price_kwh in prices:
        label = timestamp.strftime("%Y-%m-%d %H:%M")
        lines.append(f"{label} | {price_kwh:.4f}")
        html_rows.append(
            f"<tr><td>{html.escape(label)}</td>"
            f"<td>{price_kwh:.4f}</td></tr>"
        )

    text_body = "\n".join(lines)

    html_body = f"""
    <html>
      <body>
        <p><b>Dynamische uurprijzen (EPEX Spot, België)</b></p>
        <p>Opgehaald op {now.strftime('%Y-%m-%d %H:%M')} "
        f"(Europe/Brussels)</p>
        <table border="1" cellpadding="5" cellspacing="0">
          <tr>
            <th>Uur</th>
            <th>Prijs (€/kWh)</th>
          </tr>
          {''.join(html_rows)}
        </table>
        <p><small>Dit zijn EPEX Spot-prijzen, zonder Trevion-marge,
        belastingen of nettarieven.</small></p>
      </body>
    </html>
    """

    message = MIMEMultipart("alternative")
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_TO
    message["Subject"] = SUBJECT

    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(message)


if __name__ == "__main__":
    main()

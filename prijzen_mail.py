import datetime as dt
import os
import smtplib
import requests

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

EMAIL_TO = os.environ["EMAIL_TO"]
EMAIL_FROM = os.environ["EMAIL_FROM"]
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASS = os.environ["SMTP_PASS"]

TIMEZONE = ZoneInfo("Europe/Brussels")
BASE_URL = "https://api.smartprice.be"

now = dt.datetime.now(TIMEZONE)
current_hour = now.replace(minute=0, second=0, microsecond=0)

response = requests.get(f"{BASE_URL}/api/current", timeout=30)
response.raise_for_status()
data = response.json()

current_price_mwh = float(data["current"]["price_eur_mwh"])
current_price_kwh = current_price_mwh / 1000

lines = [
    "Dynamische stroomprijzen (EPEX Spot, België)",
    f"Opgehaald op {now.strftime('%Y-%m-%d %H:%M')} (Europe/Brussels)",
    "",
    "Let op: dit is voorlopig alleen de actuele SmartPrice-prijs.",
    "De waarde wordt tijdelijk voor alle 24 uren herhaald.",
    "",
    "Uur                  | Prijs (€/kWh)",
    "---------------------|--------------",
]

for hour_number in range(24):
    timestamp = current_hour + dt.timedelta(hours=hour_number)
    lines.append(
        f"{timestamp.strftime('%Y-%m-%d %H:%M')} | {current_price_kwh:.4f}"
    )

body = "\n".join(lines)

message = MIMEMultipart()
message["From"] = EMAIL_FROM
message["To"] = EMAIL_TO
message["Subject"] = "Dynamische stroomprijzen – België"
message.attach(MIMEText(body, "plain", "utf-8"))

with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
    server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    server.send_message(message)

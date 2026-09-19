import datetime as dt
import requests
import pandas as pd
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# === CONFIG ===
EMAIL_TO = os.getenv("EMAIL_TO", "jij@voorbeeld.be")
EMAIL_FROM = os.getenv("EMAIL_FROM", "jij@voorbeeld.be")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_SUBJECT = "Dynamische stroomprijzen (EPEX Spot) – komende 24u"

BASE_URL = "https://api.smartprice.be"

# === DATA OPHALEN ===
r = requests.get(f"{BASE_URL}/api/current", timeout=10)
r.raise_for_status()
data = r.json()

current_price_mwh = data["current"]["price_eur_mwh"]

rows = []
now = dt.datetime.now().replace(minute=0, second=0, microsecond=0)
for h in range(24):
    hour_dt = now + dt.timedelta(hours=h)
    price_mwh = current_price_mwh
    price_kwh = price_mwh / 1000.0
    rows.append({
        "hour": hour_dt.strftime("%Y-%m-%d %H:00"),
        "price_eur_kwh": round(price_kwh, 4)
    })

df = pd.DataFrame(rows)

# === E-MAIL BODY MAKEN (met tabel) ===
lines = [
    f"Dynamische uurprijzen (EPEX Spot, België) – gegenereerd op {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} (CET).",
    "",
    "Prijs per uur (€/kWh):",
    "",
    "Uur                | Prijs (€/kWh)",
    "-------------------|-------------"
]
for _, row in df.iterrows():
    lines.append(f"{row['hour']} | {row['price_eur_kwh']:.4f}")

body = "\n".join(lines)

# === VERSTUREN VIA SMTP (Outlook/Office 365) ===
msg = MIMEMultipart()
msg["From"] = EMAIL_FROM
msg["To"] = EMAIL_TO
msg["Subject"] = EMAIL_SUBJECT
msg.attach(MIMEText(body, "plain", "utf-8"))

with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
    server.starttls()
    server.login(SMTP_USER, SMTP_PASS)
    server.send_message(msg)
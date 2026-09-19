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
# De invoer Belpex is EUR/MWh.
# Het resultaat van de formule is cEUR/kWh.
# ============================================================

LIFEPOWR_BELPEX_FACTOR = 0.10
LIFEPOWR_MARGIN_CENT_KWH = 1.30
VAT_FACTOR = 1.06


# ============================================================
# COMPONENTEN UIT DE AUGUSTUS 2026-FACTUUR
#
# Groene stroom: 1,100 cEUR/kWh
# WKK:            0,420 cEUR/kWh
# ============================================================

GREEN_ELECTRICITY_EUR_KWH = 0.01100
WKK_EUR_KWH = 0.00420


def get_prices(day_name):
    """
    Haalt Belgische EPEX/Belpex-prijzen op voor vandaag of morgen.
    HTTP 425 betekent dat morgen nog niet gepubliceerd is.
    """
    url = f"{API_BASE}/prices/{day_name}"

    response = requests.get(
        url,
        params={"zone": ZONE},
        headers={"Authorization": f"Bearer {EUENERGY_TOKEN}"},
        timeout=30,
    )

    if response.status_code == 425:
        return

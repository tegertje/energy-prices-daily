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
# Deze waarden komen uit GitHub Actions Secrets.
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
# (0,1 x Belpex 15 MTU + 1,3)

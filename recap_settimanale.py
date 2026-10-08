import os
import json
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials

TZ = ZoneInfo("Europe/Rome")
sheet_id = os.environ["GSHEET_ID"]

creds = Credentials.from_service_account_info(
    json.loads(os.environ["GCP_SERVICE_ACCOUNT_JSON"]),
    scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"],
)
rows = gspread.authorize(creds).open_by_key(sheet_id).sheet1.get_all_values()
intestazioni, dati = (rows[0], rows[1:]) if rows else ([], [])

limite = datetime.now(TZ) - timedelta(days=7)
lead = []
for r in dati:
    riga = dict(zip(intestazioni, r))
    try:
        quando = datetime.strptime(riga["Data"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except (KeyError, ValueError):
        continue
    if quando >= limite:
        lead.append(riga)

link = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
testo = [f"RECAP SETTIMANALE AGRISMART: {len(lead)} contatti negli ultimi 7 giorni", ""]
if not lead:
    testo.append("Nessun nuovo contatto questa settimana.")
    testo.append("")
for l in lead:
    avviso = "  <-- NON INVIATA, verificare" if l.get("Mail immediata") == "NO" else ""
    testo += [
        f"- {l.get('Data')} | {l.get('Nome')}",
        f"  Email: {l.get('Email') or '-'} | Tel: {l.get('Telefono') or '-'}",
        f"  Coltura: {l.get('Coltura') or '-'} | Località: {l.get('Localita') or '-'}",
        f"  Mail immediata: {l.get('Mail immediata')}{avviso}",
        "",
    ]
testo.append(f"Dialoghi completi nel foglio: {link}")

destinatari = [e.strip() for e in os.environ["RECAP_DESTINATARI"].split(",") if e.strip()]
msg = MIMEText("\n".join(testo), "plain", "utf-8")
msg["From"] = os.environ["SMTP_USER"]
msg["To"] = ", ".join(destinatari)
msg["Subject"] = f"Recap settimanale Agrismart: {len(lead)} contatti"

host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
if port == 465:
    server = smtplib.SMTP_SSL(host, port, timeout=20)
else:
    server = smtplib.SMTP(host, port, timeout=20)
    server.starttls()
server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
server.sendmail(os.environ["SMTP_USER"], destinatari, msg.as_string())
server.quit()
print(f"Recap inviato: {len(lead)} contatti.")

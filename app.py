import streamlit as st
import os
import csv
import smtplib
import gspread
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
from prompts import SYSTEM_PROMPT, TOOLS
from google.oauth2.service_account import Credentials
from zoneinfo import ZoneInfo

load_dotenv()

st.set_page_config(page_title="Grena Assistente Virtuale", page_icon="🌱", layout="centered")

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    st.error("⚠️ Chiave API di Anthropic non trovata! Inseriscila nel file .env")
    st.stop()

client = Anthropic(api_key=api_key)

# --- FUNZIONI DI SALVATAGGIO E INVIO EMAIL ---

def salva_contatto(nome, email, telefono, coltura, localita):
    """Salva i dati commerciali lasciati dall'utente su CSV"""
    file_exists = os.path.isfile("contatti.csv")
    with open("contatti.csv", mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Data", "Nome", "Email", "Telefono", "Coltura", "Località"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), nome, email, telefono, coltura, localita])

def salva_messaggio_chat(ruolo, messaggio):
    """Salva lo storico dei messaggi scambiati per controllo qualità"""
    file_exists = os.path.isfile("storico_chat.csv")
    with open("storico_chat.csv", mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Data", "Ruolo", "Messaggio"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ruolo, messaggio])

def salva_lead_su_sheet(contatto, cronologia_messaggi, email_inviata):
    """Archivia il lead su Google Sheets. Ritorna True se il salvataggio riesce."""
    try:
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        ws = gspread.authorize(creds).open_by_key(os.getenv("GSHEET_ID")).sheet1
        dialogo = "\n".join(
            f"[{'Cliente' if m['role'] == 'user' else 'Agrismart'}]: {m['content']}"
            for m in cronologia_messaggi
        )[:45000]  # limite di 50.000 caratteri per cella
        ws.append_row(
            [
                datetime.now(ZoneInfo("Europe/Rome")).strftime("%Y-%m-%d %H:%M"),
                contatto.get("nome", ""),
                contatto.get("email", ""),
                contatto.get("telefono", ""),
                contatto.get("coltura", ""),
                contatto.get("localita", ""),
                "SI" if email_inviata else "NO",
                dialogo,
            ],
            value_input_option="RAW",
        )
        return True
    except Exception as e:
        print(f"⚠️ Errore salvataggio su Google Sheets: {e}")
        return False

def invia_email_lead(contatto, cronologia_messaggi):
    """Invia un'email con i dati del contatto e il testo completo della conversazione"""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    destinatario = os.getenv("EMAIL_DESTINATARIO")

    if not all([smtp_host, smtp_user, smtp_password, destinatario]):
        print("⚠️ Configurazione SMTP incompleta: email non inviata.")
        return False

    corpo = f"""NUOVO CONTATTO DA AGRISMART (Assistente Grena.com)

--- DATI CLIENTE ---
Nome: {contatto.get('nome', 'Non fornito')}
Email: {contatto.get('email', 'Non fornita')}
Telefono: {contatto.get('telefono', 'Non fornito')}
Coltura di interesse: {contatto.get('coltura', 'Non specificata')}
Località: {contatto.get('localita', 'Non specificata')}
Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}

--- TESTO DELLA CONVERSAZIONE ---
"""
    for msg in cronologia_messaggi:
        ruolo = "Cliente" if msg["role"] == "user" else "Agrismart"
        corpo += f"\n[{ruolo}]: {msg['content']}\n"

    # Supporta più destinatari separati da virgola nei Secrets
    # (es. "commerciale@grena.com,mario@grena.com")
    lista_destinatari = [e.strip() for e in destinatario.split(",") if e.strip()]

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = ", ".join(lista_destinatari)
    msg["Subject"] = f"🌱 Nuovo contatto Agrismart: {contatto.get('nome', 'Cliente')}"
    msg.attach(MIMEText(corpo, "plain", "utf-8"))

    try:
        # Timeout esplicito di 10 secondi: se il server non risponde, falliamo
        # subito invece di restare bloccati indefinitamente.
        if smtp_port == 465:
            # Porta 465: SSL diretto fin dall'inizio (nessun STARTTLS)
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            # Porta 587 (o altre): connessione in chiaro, poi upgrade con STARTTLS
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            server.starttls()

        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, lista_destinatari, msg.as_string())
        server.quit()
        print("✅ Email inviata con successo.")
        return True
    except Exception as e:
        print(f"⚠️ Errore nell'invio email: {e}")
        st.session_state.ultimo_errore_email = str(e)
        return False

# --- INTERFACCIA GRAFICA ---

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": "🌱 **Ciao! Sono Agrismart Grena**, il tuo assistente virtuale personale.\n\nSono qui per aiutarti a conoscere al meglio i nostri concimi biologici e biostimolanti naturali, consigliarti le migliori soluzioni per le tue colture e indicarti le tempistiche corrette di utilizzo. Come posso esserti utile oggi?"
        }
    ]

if "email_lead_inviata" not in st.session_state:
    st.session_state.email_lead_inviata = False

# --- PANNELLO DI DEBUG PROTETTO DA PASSWORD ---
if "debug_sbloccato" not in st.session_state:
    st.session_state.debug_sbloccato = False

with st.sidebar:
    st.subheader("🔧 Debug")

    if not st.session_state.debug_sbloccato:
        password_inserita = st.text_input("Password admin", type="password", key="debug_pwd")
        if password_inserita:
            if password_inserita == os.getenv("DEBUG_PASSWORD"):
                st.session_state.debug_sbloccato = True
                st.rerun()
            else:
                st.error("Password errata")
    else:
        # Stato dell'ultimo lead, visibile anche dopo altri messaggi
        esito_lead = st.session_state.get("ultimo_esito")
        if esito_lead:
            st.caption(f"Ultimo lead alle {esito_lead['ora']}")
            st.write("✅ Email inviata" if esito_lead["email"] else "❌ Email NON inviata")
            if not esito_lead["email"] and st.session_state.get("ultimo_errore_email"):
                st.code(st.session_state.ultimo_errore_email)
            st.write("✅ Salvato su Google Sheets" if esito_lead["sheet"] else "❌ Google Sheets NON salvato")
        else:
            st.caption("Nessun lead gestito in questa sessione")

        st.link_button("📊 Apri Google Sheet", f"https://docs.google.com/spreadsheets/d/{os.getenv('GSHEET_ID')}")

        if st.button("🔄 Azzera chat di test"):
            for chiave in ("messages", "email_lead_inviata", "ultimo_esito", "ultimo_errore_email"):
                st.session_state.pop(chiave, None)
            st.rerun()

        if os.path.isfile("contatti.csv"):
            with open("contatti.csv", "rb") as f:
                st.download_button("📥 Scarica contatti.csv", f, file_name="contatti.csv")
        else:
            st.caption("contatti.csv non ancora creato in questa sessione")

        if os.path.isfile("storico_chat.csv"):
            with open("storico_chat.csv", "rb") as f:
                st.download_button("📥 Scarica storico_chat.csv", f, file_name="storico_chat.csv")
        else:
            st.caption("storico_chat.csv non ancora creato in questa sessione")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Come posso aiutarti con la tua coltura?"):
    with st.chat_message("user"):
        st.markdown(user_input)

    st.session_state.messages.append({"role": "user", "content": user_input})
    salva_messaggio_chat("Utente", user_input)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("*Sto pensando...*")

        try:
            # Prepariamo i messaggi nel formato richiesto dall'API
            messaggi_api = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state.messages
            ]

            # Ciclo agentico: continuiamo finché il modello richiama strumenti
            while True:
                response = client.messages.create(
                    model="claude-sonnet-5",
                    max_tokens=2000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messaggi_api
                )

                # Estraiamo eventuali blocchi di tipo tool_use e testo
                tool_use_blocks = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
                testo_risposta = "".join(
                    b.text for b in response.content if getattr(b, "type", None) == "text"
                )

                if not tool_use_blocks:
                    # Nessuno strumento richiamato: questa è la risposta finale
                    break

                # Aggiungiamo la risposta dell'assistente (con il tool_use) alla cronologia API
                messaggi_api.append({"role": "assistant", "content": response.content})

                # Eseguiamo ogni tool richiesto e prepariamo i risultati
                tool_results = []
                for block in tool_use_blocks:
                    if block.name == "salva_contatto_cliente":
                        contatto = block.input
                        salva_contatto(
                            contatto.get("nome", ""),
                            contatto.get("email", ""),
                            contatto.get("telefono", ""),
                            contatto.get("coltura", ""),
                            contatto.get("localita", "")
                        )
                        if not st.session_state.email_lead_inviata:
                            esito = invia_email_lead(contatto, st.session_state.messages)
                            salvato = salva_lead_su_sheet(contatto, st.session_state.messages, esito)
                            st.session_state.ultimo_esito = {
                                "email": esito,
                                "sheet": salvato,
                                "ora": datetime.now(ZoneInfo("Europe/Rome")).strftime("%H:%M:%S"),
                            }
                            # Il flag scatta se almeno uno dei due canali ha funzionato
                            if esito or salvato:
                                st.session_state.email_lead_inviata = True

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": "Contatto salvato e team commerciale avvisato con successo."
                        })

                # Rimandiamo i risultati al modello per farlo continuare la conversazione
                messaggi_api.append({"role": "user", "content": tool_results})

            if not testo_risposta:
                testo_risposta = "Scusa, non sono riuscito a generare una risposta testuale."

            message_placeholder.markdown(testo_risposta)
            st.session_state.messages.append({"role": "assistant", "content": testo_risposta})
            salva_messaggio_chat("Agrismart", testo_risposta)

        except Exception as e:
            message_placeholder.markdown(f"❌ Si è verificato un errore: {e}")

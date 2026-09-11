import streamlit as st
import os
import csv
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
from prompts import SYSTEM_PROMPT, TOOLS

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

def invia_email_lead(contatto, cronologia_messaggi):
    """Invia un'email con i dati del contatto e il testo completo della conversazione"""
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    destinatario = os.getenv("EMAIL_DESTINATARIO")

    if not all([smtp_host, smtp_user, smtp_password, destinatario]):
        # Configurazione mancante: non blocchiamo la chat, ma segnaliamo nei log
        print("⚠️ Configurazione SMTP incompleta: email non inviata.")
        return False

    # Corpo dell'email: prima i contatti, poi il dialogo completo
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

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = destinatario
    msg["Subject"] = f"🌱 Nuovo contatto Agrismart: {contatto.get('nome', 'Cliente')}"
    msg.attach(MIMEText(corpo, "plain", "utf-8"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, destinatario, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"⚠️ Errore nell'invio email: {e}")
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
                            invia_email_lead(contatto, st.session_state.messages)
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

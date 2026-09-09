import streamlit as st
import os
import csv
from datetime import datetime
from anthropic import Anthropic
from dotenv import load_dotenv
from prompts import SYSTEM_PROMPT

# Carica le variabili dal file .env
load_dotenv()

st.set_page_config(page_title="Grena Assistente Virtuale", page_icon="🌱", layout="centered")
st.title("🌱 Agrismart - Assistente Grena.com")

# Verifica Chiave API
api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    st.error("⚠️ Chiave API di Anthropic non trovata! Inseriscila nel file .env")
    st.stop()

client = Anthropic(api_key=api_key)

# --- FUNZIONI DI SALVATAGGIO DATI ---
def salva_contatto(nome, email, telefono, coltura):
    """Salva i dati commerciali lasciati dall'utente"""
    file_exists = os.path.isfile("contatti.csv")
    with open("contatti.csv", mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Data", "Nome", "Email", "Telefono", "Coltura"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M"), nome, email, telefono, coltura])

def salva_messaggio_chat(ruolo, messaggio):
    """Salva lo storico dei messaggi scambiati per controllo qualità"""
    file_exists = os.path.isfile("storico_chat.csv")
    with open("storico_chat.csv", mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Data", "Ruolo", "Messaggio"])
        writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ruolo, messaggio])


# --- INTERFACCIA GRAFICA ---

# Sidebar per la Lead Generation Manuale o visualizzazione log
with st.sidebar:
    st.header("📥 Modulo Contatto Diretto")
    st.write("Se preferisci, lascia qui i tuoi dati per ricevere un piano di concimazione via email.")
    with st.form("form_contatto", clear_on_submit=True):
        c_nome = st.text_input("Nome e Cognome")
        c_email = st.text_input("Email")
        c_tel = st.text_input("Telefono")
        c_coltura = st.text_input("Tipo di Coltura (es. Pescheto, Uliveto)")
        submit = st.form_submit_button("Invia i dati a Grena")
        
        if submit:
            if c_nome and (c_email or c_tel):
                salva_contatto(c_nome, c_email, c_tel, c_coltura)
                st.success("✅ Dati registrati! Ti ricontatteremo presto.")
            else:
                st.error("❌ Inserisci almeno il nome e un contatto (Email o Telefono).")

# Inizializza la cronologia della chat
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostra i messaggi precedenti
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Gestione dell'input utente nella chat
if user_input := st.chat_input("Come posso aiutarti con la tua coltura?"):
    with st.chat_message("user"):
        st.markdown(user_input)
    
    st.session_state.messages.append({"role": "user", "content": user_input})
    salva_messaggio_chat("Utente", user_input)  # <--- Salva su file

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("*Sto pensando...*")
        
        try:
            response = client.messages.create(
                model="claude-sonnet-5",
                max_tokens=2000, 
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                ]
            )
            
            assistant_response = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    assistant_response += block.text
            
            if not assistant_response:
                assistant_response = "Scusa, non sono riuscito a generare una response."

            message_placeholder.markdown(assistant_response)
            st.session_state.messages.append({"role": "assistant", "content": assistant_response})
            salva_messaggio_chat("Agrismart", assistant_response)  # <--- Salva su file
            
        except Exception as e:
            message_placeholder.markdown(f"❌ Si è verificato un errore: {e}")

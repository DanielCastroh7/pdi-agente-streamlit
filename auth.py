# auth.py
import bcrypt
import json
from pathlib import Path
import secrets
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import streamlit as st

# Importações do Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# Tenta importar as credenciais de e-mail do config.py para desenvolvimento local
try:
    from config import EMAIL_SENDER, EMAIL_PASSWORD
except ImportError:
    EMAIL_SENDER = None
    EMAIL_PASSWORD = None

# --- INICIALIZAÇÃO DO FIREBASE (PARA PRODUÇÃO E DESENVOLVIMENTO) ---

def initialize_firebase():
    """
    Inicializa o app do Firebase. Em produção (Streamlit Cloud), usa st.secrets.
    Em desenvolvimento local, usa o arquivo firebase_service_account.json.
    """
    if not firebase_admin._apps:
        try:
            # Tenta usar o Streamlit Secrets (para o ambiente online)
            creds_json = {
                "type": st.secrets["firebase"]["type"],
                "project_id": st.secrets["firebase"]["project_id"],
                "private_key_id": st.secrets["firebase"]["private_key_id"],
                # **CORREÇÃO CRÍTICA:** Substitui os caracteres de escape \n por quebras de linha reais.
                "private_key": st.secrets["firebase"]["private_key"].replace('\\n', '\n'),
                "client_email": st.secrets["firebase"]["client_email"],
                "client_id": st.secrets["firebase"]["client_id"],
                "auth_uri": st.secrets["firebase"]["auth_uri"],
                "token_uri": st.secrets["firebase"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
                "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"]
            }
            cred = credentials.Certificate(creds_json)
            print("Firebase App inicializado via Streamlit Secrets.")
        except (AttributeError, KeyError, FileNotFoundError):
            # Se st.secrets falhar, tenta usar o arquivo local (para desenvolvimento)
            SERVICE_ACCOUNT_FILE = Path(__file__).parent / "firebase_service_account.json"
            if SERVICE_ACCOUNT_FILE.exists():
                cred = credentials.Certificate(str(SERVICE_ACCOUNT_FILE))
                print("Firebase App inicializado via arquivo local.")
            else:
                print("ERRO: Credenciais do Firebase não encontradas no Streamlit Secrets nem como arquivo local.")
                st.error("As credenciais do Firebase não estão configuradas. A aplicação não pode se conectar ao banco de dados.")
                return

        firebase_admin.initialize_app(cred)

# Chama a inicialização
initialize_firebase()

# --- FUNÇÕES DE AUTENTICAÇÃO E DADOS COM FIRESTORE ---

def get_db():
    """Retorna uma instância do cliente Firestore."""
    return firestore.client()

def hash_password(password: str) -> str:
    """Gera um hash seguro para a senha usando bcrypt."""
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed_password.decode('utf-8')

def check_password(password: str, hashed_password: str) -> bool:
    """Verifica se a senha fornecida corresponde ao hash armazenado."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

def send_reset_email(recipient_email: str, token: str):
    """
    Envia um e-mail de redefinição de senha usando o SMTP do Outlook.
    Usa st.secrets em produção ou config.py em desenvolvimento.
    """
    smtp_server = "smtp.office365.com"
    smtp_port = 587
    
    try:
        sender_email = st.secrets["email_sender"]
        password = st.secrets["email_password"]
    except (FileNotFoundError, KeyError):
        sender_email = EMAIL_SENDER
        password = EMAIL_PASSWORD

    if not sender_email or not password:
        print("ERRO: Credenciais de e-mail não configuradas em st.secrets ou config.py")
        return False

    message = MIMEMultipart("alternative")
    message["Subject"] = "PDI Agente - Redefinição de Senha"
    message["From"] = sender_email
    message["To"] = recipient_email

    text = f"""
    Olá,
    Você solicitou a redefinição de sua senha na plataforma PDI Agente.
    Use o seguinte token para criar uma nova senha:
    {token}
    Se você não solicitou isso, por favor, ignore este e-mail.
    """
    html = f"""
    <html>
      <body>
        <h2>PDI Agente - Redefinição de Senha</h2>
        <p>Olá,</p>
        <p>Você solicitou a redefinição de sua senha na plataforma PDI Agente.</p>
        <p>Use o seguinte token para criar uma nova senha na aplicação:</p>
        <p style="font-size: 1.5em; font-weight: bold; letter-spacing: 2px; background-color: #f0f0f0; padding: 10px; border-radius: 5px;">{token}</p>
        <p>Se você não solicitou isso, por favor, ignore este e-mail.</p>
        <br>
        <p>Atenciosamente,</p>
        <p>Equipe PDI Agente</p>
      </body>
    </html>
    """

    part1 = MIMEText(text, "plain")
    part2 = MIMEText(html, "html")
    message.attach(part1)
    message.attach(part2)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, password)
            server.sendmail(sender_email, recipient_email, message.as_string())
        print(f"E-mail de redefinição enviado com sucesso para {recipient_email}")
        return True
    except Exception as e:
        print(f"Falha ao enviar e-mail: {e}")
        return False

def register_user(email: str, password: str, name: str) -> bool:
    """Registra um novo usuário no Firestore."""
    db = get_db()
    user_ref = db.collection('pdi_users').document(email)
    
    if user_ref.get().exists:
        return False # Usuário já existe

    hashed_pw = hash_password(password)
    
    new_user_data = {
        "profile": {
            "nome": name,
            "email": email,
            "habilidades_atuais": [],
            "pontos_a_melhorar": [],
            "resumo_profissional": ""
        },
        "security": {
            "password_hash": hashed_pw
        },
        "pdi_plan": {
            "objetivo_final": "",
            "metas_temporais": {}
        }
    }
    
    user_ref.set(new_user_data)
    return True

def login_user(email: str, password: str) -> bool:
    """Autentica um usuário com base nos dados do Firestore."""
    db = get_db()
    user_ref = db.collection('pdi_users').document(email)
    doc = user_ref.get()

    if not doc.exists:
        return False

    data = doc.to_dict()
    hashed_pw = data.get("security", {}).get("password_hash")
    if not hashed_pw:
        return False

    return check_password(password, hashed_pw)

def set_password_reset_token(email: str) -> bool:
    """Gera um token, armazena no Firestore e envia por e-mail."""
    db = get_db()
    user_ref = db.collection('pdi_users').document(email)
    doc = user_ref.get()

    if not doc.exists:
        return False

    token = secrets.token_urlsafe(20)
    expiry_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    
    user_ref.update({
        'security.reset_token': token,
        'security.reset_token_expiry': expiry_time.isoformat()
    })
    
    return send_reset_email(email, token)

def reset_password_with_token(token: str, new_password: str) -> tuple[bool, str]:
    """Redefine a senha de um usuário no Firestore se o token for válido."""
    db = get_db()
    users_ref = db.collection('pdi_users').where('security.reset_token', '==', token).limit(1)
    docs = users_ref.stream()
    
    user_doc = next(docs, None)
    if not user_doc:
        return False, "Token inválido."

    data = user_doc.to_dict()
    expiry_time = datetime.datetime.fromisoformat(data['security']['reset_token_expiry'])
    if datetime.datetime.now(datetime.timezone.utc) > expiry_time:
        return False, "Token expirado. Por favor, solicite um novo."

    user_doc.reference.update({
        'security.password_hash': hash_password(new_password),
        'security.reset_token': None,
        'security.reset_token_expiry': None
    })
    return True, "Senha redefinida com sucesso! Você já pode fazer o login."

# --- FUNÇÕES DE DADOS DO PDI ---
def load_pdi_data_from_firestore(email: str):
    """Carrega todos os dados de um usuário do Firestore."""
    db = get_db()
    user_ref = db.collection('pdi_users').document(email)
    doc = user_ref.get()
    if doc.exists:
        return doc.to_dict()
    return {"profile": {}, "pdi_plan": {"metas_temporais": {}}}

def save_pdi_data_to_firestore(email: str, data: dict):
    """Salva/Atualiza os dados de um usuário no Firestore."""
    db = get_db()
    user_ref = db.collection('pdi_users').document(email)
    user_ref.set(data, merge=True)

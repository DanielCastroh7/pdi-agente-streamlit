# app.py
import streamlit as st
import json
from pathlib import Path
import time
import multiprocessing
import queue
from fpdf import FPDF
import os
import firebase_admin
import textwrap
import re
from firebase_admin import credentials

# Importa as funções de autenticação e análise
from auth import (
    register_user, 
    login_user, 
    set_password_reset_token, 
    reset_password_with_token,
    load_pdi_data_from_firestore,
    save_pdi_data_to_firestore
)
from pdi_analyzer import run_full_analysis_process

# --- CONFIGURAÇÃO INICIAL E FUNÇÕES AUXILIARES ---
# **NOVO:** A função de inicialização agora mora aqui.
# def initialize_firebase():
#     """
#     Inicializa o app do Firebase. Em produção (Streamlit Cloud), usa st.secrets.
#     Em desenvolvimento local, usa o arquivo firebase_service_account.json.
#     """
#     if not firebase_admin._apps:
#         try:
#             # **CORREÇÃO DEFINITIVA:** Lendo os segredos como uma tabela TOML
#             creds_dict = {
#                 "type": st.secrets["firebase"]["type"],
#                 "project_id": st.secrets["firebase"]["project_id"],
#                 "private_key_id": st.secrets["firebase"]["private_key_id"],
#                 "private_key": st.secrets["firebase"]["private_key"].replace('\\n', '\n'),
#                 "client_email": st.secrets["firebase"]["client_email"],
#                 "client_id": st.secrets["firebase"]["client_id"],
#                 "auth_uri": st.secrets["firebase"]["auth_uri"],
#                 "token_uri": st.secrets["firebase"]["token_uri"],
#                 "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
#                 "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"]
#             }
#             cred = credentials.Certificate(creds_dict)
#             print("Firebase App inicializado via Streamlit Secrets (Tabela TOML).")
#         except (AttributeError, KeyError, FileNotFoundError):
#             # Fallback for local development
#             SERVICE_ACCOUNT_FILE = Path(__file__).parent / "firebase_service_account.json"
#             if SERVICE_ACCOUNT_FILE.exists():
#                 cred = credentials.Certificate(str(SERVICE_ACCOUNT_FILE))
#                 print("Firebase App inicializado via arquivo local.")
#             else:
#                 print("ERRO: Credenciais do Firebase não encontradas.")
#                 return False
        
#         try:
#             firebase_admin.initialize_app(cred)
#         except ValueError as e:
#             st.error(f"Erro ao inicializar o Firebase. Verifique a formatação das credenciais. Detalhe: {e}")
#             return False
            
#     return True


DATA_PATH = Path("data_pdi")
DATA_PATH.mkdir(parents=True, exist_ok=True)

def save_pdi_data(user_id, data):
    """Salva todos os dados do PDI do usuário no Firestore."""
    save_pdi_data_to_firestore(user_id, data)

def load_pdi_data(user_id):
    """Carrega os dados do PDI de um arquivo JSON, se ele existir."""
    return load_pdi_data_from_firestore(user_id)

# --- FUNÇÃO GERADORA DE PDF (CORRIGIDA E APRIMORADA) ---
def generate_pdi_pdf(pdi_data):
    """Cria um PDF formatado com o diagnóstico completo do PDI (robusto a UTF-8 e tokens longos)."""
    analysis = pdi_data.get("ai_analysis", {}) or {}
    profile = pdi_data.get("profile", {}) or {}

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Fonte com suporte a UTF-8 ---
    font_path = os.path.join(os.path.dirname(__file__), "fonts", "DejaVuSans.ttf")
    if not os.path.exists(font_path):
        raise FileNotFoundError(
            f"Fonte não encontrada em {font_path}. Baixe DejaVuSans.ttf e coloque em /fonts"
        )
    #pdf.add_font("DejaVu", "", font_path, uni=True)
    pdf.add_font("DejaVu", "", font_path)
    pdf.set_font("DejaVu", "", 16)

    # --- Helpers ---

    def clean_text(text):
        """Garante string; preserva UTF-8."""
        if text is None:
            return ""
        if not isinstance(text, str):
            text = str(text)
        # Normaliza quebras de linha (evita \r solto)
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def split_long_token(token: str, max_w: float) -> str:
        """
        Quebra 'token' em pedaços menores que caibam em 'max_w' usando a métrica da fonte atual.
        Usa heurisca proporcional para não ficar O(n^2).
        """
        out = []
        while token:
            # se já cabe, fim
            if pdf.get_string_width(token) <= max_w:
                out.append(token)
                break

            # estima quantos caracteres cabem proporcionalmente
            width_token = pdf.get_string_width(token)
            ratio = max_w / width_token if width_token > 0 else 0.5
            # pega ~95% do estimado pra garantir
            take = max(1, int(len(token) * ratio * 0.95))
            out.append(token[:take])
            out.append("\n")  # força próxima linha
            token = token[take:]
        return "".join(out)

    def force_wrap_to_width(text: str) -> str:
        """
        Garante que nenhuma 'palavra' (sequência sem espaços) ultrapasse a largura útil.
        Mantém os espaços originais; quebra internamente quando necessário.
        """
        # largura útil = página - margens
        usable_w = pdf.w - pdf.l_margin - pdf.r_margin
        # Se por algum motivo estiver inválida, define um fallback
        if usable_w <= 1:
            usable_w = 180  # mm, valor típico A4 com margens

        # Quebra por linhas primeiro, pra preservar parágrafos
        lines = text.split("\n")
        fixed_lines = []
        for line in lines:
            if not line:
                fixed_lines.append("")
                continue

            # Separa preservando espaços intercalados
            parts = re.split(r"(\s+)", line)
            rebuilt = []
            for part in parts:
                if not part or part.isspace():
                    rebuilt.append(part)
                    continue

                # Parte "sem espaço": pode ser url/token gigante — quebrar se preciso
                if pdf.get_string_width(part) > usable_w:
                    rebuilt.append(split_long_token(part, usable_w))
                else:
                    rebuilt.append(part)

            fixed_lines.append("".join(rebuilt))

        return "\n".join(fixed_lines)

    def safe_multicell(text: str, h=5):
        """
        Multicell protegida:
        - Move o cursor pro LMARGIN antes de escrever
        - Força wrap de tokens longos baseado na largura real
        """
        if text is None:
            return
        pdf.set_x(pdf.l_margin)
        txt = force_wrap_to_width(clean_text(text))
        pdf.multi_cell(0, h, txt)

    def write_section(title, content):
        if not content:
            return
        pdf.set_font("DejaVu", "", 12)
        safe_multicell(title, h=7)
        pdf.set_font("DejaVu", "", 10)
        safe_multicell(content, h=5)
        pdf.ln(2)

    # --- Cabeçalho ---
    safe_multicell(f"PDI Agente: Diagnóstico de Carreira para {profile.get('nome', 'Usuário')}", h=10)
    pdf.ln(5)

    # --- Conteúdo principal ---

    # 1) Análise geral
    write_section("Análise Geral da IA", analysis.get("analise_geral", "N/A"))

    # 2) Perfil de empresa ideal (dict ou string)
    empresa_ideal = analysis.get("tipo_empresa_ideal", {})
    if isinstance(empresa_ideal, dict):
        empresa_ideal_text = ""
        for key, value in empresa_ideal.items():
            empresa_ideal_text += f"{key.capitalize()}: {value}\n"
        write_section("Perfil de Empresa Ideal", empresa_ideal_text.strip())
    else:
        write_section("Perfil de Empresa Ideal", empresa_ideal)

    # 3) Plano SMART (1 ano)
    pdf.set_font("DejaVu", "", 12)
    safe_multicell("Plano SMART (Próximo Ano)", h=7)
    smart_plan = analysis.get("plano_smart_1_ano", {}) or {}

    if isinstance(smart_plan, dict):
        for key in ["S", "M", "A", "R", "T"]:
            value = smart_plan.get(key)
            if not value:
                continue

            pdf.set_font("DejaVu", "", 10)
            safe_multicell(f"  - {key.upper()}:")

            # M: lista de objetivos (detalhe + métrica)
            if key == "M" and isinstance(value, list):
                for idx, item in enumerate(value, start=1):
                    if isinstance(item, dict):
                        detalhe = item.get("detalhe", "")
                        metrica = item.get("metrica", "")
                        detalhe_text = detalhe if detalhe else json.dumps(item, ensure_ascii=False)
                        if metrica:
                            safe_multicell(f"    {idx}. {detalhe_text}\n       (Métrica: {metrica})")
                        else:
                            safe_multicell(f"    {idx}. {detalhe_text}")
                    else:
                        safe_multicell(f"    {idx}. {item}")
                continue

            # T: cronograma/datas (dict|list|string)
            if key == "T":
                if isinstance(value, dict):
                    data_limite = (
                        value.get("Data limite") or value.get("data limite") or
                        value.get("Data_limite") or value.get("data_limite") or
                        value.get("data")
                    )
                    if data_limite:
                        safe_multicell(f"    Data limite: {data_limite}")

                    cronograma = (
                        value.get("Cronograma") or value.get("cronograma") or
                        value.get("Cronogramas") or value.get("Trimestres")
                    )
                    if isinstance(cronograma, list):
                        for trimestre in cronograma:
                            if isinstance(trimestre, dict):
                                tr_nome = (
                                    trimestre.get("Trimestre") or trimestre.get("trimestre") or
                                    trimestre.get("periodo") or ""
                                )
                                foco = trimestre.get("Foco") or trimestre.get("foco") or ""
                                if tr_nome or foco:
                                    trim_info = tr_nome.strip()
                                    if foco:
                                        trim_info += f" - Foco: {foco}"
                                    safe_multicell(f"    {trim_info}")
                                acoes = (
                                    trimestre.get("Acoes") or trimestre.get("acoes") or
                                    trimestre.get("Ação") or trimestre.get("acoes_list")
                                )
                                if isinstance(acoes, list):
                                    for acao in acoes:
                                        safe_multicell(f"       - {acao}")
                                elif acoes:
                                    safe_multicell(f"       - {acoes}")
                            else:
                                safe_multicell(f"    - {trimestre}")
                    elif isinstance(cronograma, dict):
                        for tr_key, tr_val in cronograma.items():
                            foco = ""
                            acoes = []
                            if isinstance(tr_val, dict):
                                foco = tr_val.get("Foco") or tr_val.get("foco") or ""
                                acoes = tr_val.get("Acoes") or tr_val.get("acoes") or []
                            else:
                                acoes = tr_val if isinstance(tr_val, list) else [tr_val]
                            trim_info = f"{tr_key}"
                            if foco:
                                trim_info += f" - Foco: {foco}"
                            safe_multicell(f"    {trim_info}")
                            for acao in acoes:
                                safe_multicell(f"       - {acao}")
                    else:
                        # fallback: imprime o dict inteiro formatado
                        if isinstance(value, dict):
                            safe_multicell(f"    {json.dumps(value, ensure_ascii=False)}")
                    continue

            # Padrão: S, A, R ou outros formatos
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, list):
                        sub_value_text = ""
                        for item in sub_value:
                            if isinstance(item, dict):
                                for k, v in item.items():
                                    sub_value_text += f"      - {k.capitalize()}: {v}\n"
                            else:
                                sub_value_text += f"      - {item}\n"
                    else:
                        sub_value_text = str(sub_value)
                    safe_multicell(f"    * {sub_key.replace('_', ' ').capitalize()}:\n{sub_value_text}")
            else:
                safe_multicell(str(value))

    # 4) Recomendações focadas
    recomendacoes = analysis.get("recomendacoes_focadas", [])
    if isinstance(recomendacoes, list) and recomendacoes:
        recomendacoes_text = "\n".join(
            f"- {rec.get('foco')}: {rec.get('recomendacao')}" for rec in recomendacoes
        )
        write_section("Recomendações Focadas", recomendacoes_text)

    # 5) Próximos passos
    write_section(
        "Próximos Passos (3 Meses)",
        "\n".join(f"- {step}" for step in analysis.get("proximos_passos", [])),
    )

    # 6) Cargos similares
    write_section(
        "Cargos Similares Sugeridos",
        "\n".join(f"- {job}" for job in analysis.get("sugestao_cargos_similares", [])),
    )

    # 7) Plano de ação IA
    plano_ia = analysis.get("plano_de_acao_ia", {}) or {}
    if isinstance(plano_ia, dict):
        for periodo in ["1_ano", "3_anos", "5_anos", "10_anos", "15_anos"]:
            itens = plano_ia.get(periodo)
            if itens:
                write_section(
                    f"Plano de Ação para {periodo.replace('_', ' ')}",
                    "\n".join(f"- {item}" for item in itens),
                )

    return bytes(pdf.output())

# --- FUNÇÃO PRINCIPAL DO APP ---
def main():
    st.set_page_config(page_title="PDI Agente", layout="wide", initial_sidebar_state="auto")

    #firebase_initialized = initialize_firebase()
    
    # --- INICIALIZAÇÃO DO ESTADO DA SESSÃO ---
    if 'logged_in_user' not in st.session_state: st.session_state.logged_in_user = None
    if 'page' not in st.session_state: st.session_state.page = "Login"
    if 'analysis_process' not in st.session_state: st.session_state.analysis_process = None
    if 'q_from_process' not in st.session_state: st.session_state.q_from_process = None
    if 'last_status' not in st.session_state: st.session_state.last_status = None

    # --- LÓGICA DE AUTENTICAÇÃO ---
    if not st.session_state.logged_in_user:
        st.title("Bem-vindo ao PDI Agente 👨‍🚀")
        
        #if not firebase_initialized:
        #    st.error("Falha na conexão com o banco de dados. Verifique as credenciais do Firebase no Streamlit Cloud Secrets.")
        #    return
        
        login_tab, register_tab, forgot_tab = st.tabs(["Login", "Registrar", "Esqueci a Senha"])

        with login_tab:
            st.subheader("Login")
            with st.form("login_form"):
                email = st.text_input("E-mail")
                password = st.text_input("Senha", type="password")
                if st.form_submit_button("Entrar"):
                    if login_user(email, password):
                        st.session_state.logged_in_user = email
                        st.rerun()
                    else:
                        st.error("E-mail ou senha inválidos.")
        
        with register_tab:
            st.subheader("Criar Nova Conta")
            with st.form("register_form"):
                name = st.text_input("Nome Completo")
                email = st.text_input("E-mail para login")
                password = st.text_input("Crie uma senha", type="password")
                if st.form_submit_button("Registrar"):
                    if register_user(email, password, name):
                        st.success("Usuário registrado com sucesso! Faça o login para continuar.")
                    else:
                        st.error("Este e-mail já está em uso.")

        with forgot_tab:
            st.subheader("Recuperar Senha")
            with st.form("forgot_form"):
                email = st.text_input("Digite o e-mail da sua conta")
                if st.form_submit_button("Enviar E-mail de Recuperação"):
                    if set_password_reset_token(email):
                        st.success("Se este e-mail estiver cadastrado, um e-mail de recuperação foi enviado. Verifique sua caixa de entrada e spam.")
                    else:
                        st.success("Se este e-mail estiver cadastrado, um e-mail de recuperação foi enviado. Verifique sua caixa de entrada e spam.")
            
            st.markdown("---")
            with st.form("reset_form"):
                token_input = st.text_input("Cole o token recebido por e-mail aqui")
                new_password = st.text_input("Digite sua nova senha", type="password")
                if st.form_submit_button("Redefinir Senha"):
                    success, message = reset_password_with_token(token_input, new_password)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
        return

    # --- APLICAÇÃO PRINCIPAL (SÓ APARECE SE ESTIVER LOGADO) ---
    user_email = st.session_state.logged_in_user
    pdi_data = load_pdi_data(user_email)

    st.sidebar.title("Menu de Navegação")
    st.sidebar.info(f"**Usuário:** {user_email}")
    page = st.sidebar.radio("Escolha uma seção:", ["👤 Meu Perfil", "🚀 Meu Plano de Carreira", "📊 Meu Diagnóstico"])
    if st.sidebar.button("Logout"):
        st.session_state.logged_in_user = None
        st.rerun()

    st.title("👨‍🚀 PDI Agente")

    if page == "👤 Meu Perfil":
        st.header("👤 Meu Perfil")
        st.markdown("Informações essenciais para que a IA entenda seu contexto profissional.")
        with st.form("profile_form"):
            nome = st.text_input("Nome Completo", value=pdi_data["profile"].get("nome", ""))
            linkedin_url = st.text_input("URL do seu Perfil no LinkedIn", value=pdi_data["profile"].get("linkedin_url", ""))
            habilidades_input = st.text_input("Suas Principais Habilidades (separadas por vírgula)", value=", ".join(pdi_data["profile"].get("habilidades_atuais", [])))
            melhorar_input = st.text_input("Seus pontos a melhorar (separadas por vírgula)", value=", ".join(pdi_data["profile"].get("pontos_a_melhorar", [])))
            resumo_profissional = st.text_area("Resumo Profissional", height=150, value=pdi_data["profile"].get("resumo_profissional", ""))
            if st.form_submit_button("Salvar Perfil"):
                pdi_data["profile"]["nome"] = nome
                pdi_data["profile"]["linkedin_url"] = linkedin_url
                pdi_data["profile"]["habilidades_atuais"] = [h.strip() for h in habilidades_input.split(',') if h.strip()]
                pdi_data["profile"]["pontos_a_melhorar"] = [p.strip() for p in melhorar_input.split(',') if p.strip()]
                pdi_data["profile"]["resumo_profissional"] = resumo_profissional
                save_pdi_data(user_email, pdi_data)
                st.success("Perfil salvo com sucesso!")

    elif page == "🚀 Meu Plano de Carreira":
        st.header("🚀 Meu Plano de Carreira")
        st.markdown("Defina suas metas de longo prazo. Seja ambicioso! A IA ajudará a traçar o caminho.")
        with st.form("pdi_plan_form"):
            objetivo_final = st.text_input("🎯 Qual é o seu grande objetivo final de carreira?", value=pdi_data["pdi_plan"].get("objetivo_final", ""))
            st.subheader("Metas Intermediárias")
            col1, col2 = st.columns(2)
            with col1:
                with st.container(border=True):
                    st.markdown("**Em 1 Ano**")
                    meta_1_ano_cargo = st.text_input("Cargo Alvo (1 Ano)", value=pdi_data["pdi_plan"]["metas_temporais"].get("1_ano", {}).get("cargo_alvo", ""))
                    meta_1_ano_foco = st.text_area("Foco Principal (1 Ano)", height=100, value=pdi_data["pdi_plan"]["metas_temporais"].get("1_ano", {}).get("foco_principal", ""))
                with st.container(border=True):
                    st.markdown("**Em 5 Anos**")
                    meta_5_anos_cargo = st.text_input("Cargo Alvo (5 Anos)", value=pdi_data["pdi_plan"]["metas_temporais"].get("5_anos", {}).get("cargo_alvo", ""))
                    meta_5_anos_foco = st.text_area("Foco Principal (5 Anos)", height=100, value=pdi_data["pdi_plan"]["metas_temporais"].get("5_anos", {}).get("foco_principal", ""))
                with st.container(border=True):
                    st.markdown("**Em 15 Anos**")
                    meta_15_anos_cargo = st.text_input("Cargo Alvo (15 Anos)", value=pdi_data["pdi_plan"]["metas_temporais"].get("15_anos", {}).get("cargo_alvo", ""))
                    meta_15_anos_foco = st.text_area("Foco Principal (15 Anos)", height=100, value=pdi_data["pdi_plan"]["metas_temporais"].get("15_anos", {}).get("foco_principal", ""))
            with col2:
                with st.container(border=True):
                    st.markdown("**Em 3 Anos**")
                    meta_3_anos_cargo = st.text_input("Cargo Alvo (3 Anos)", value=pdi_data["pdi_plan"]["metas_temporais"].get("3_anos", {}).get("cargo_alvo", ""))
                    meta_3_anos_foco = st.text_area("Foco Principal (3 Anos)", height=100, value=pdi_data["pdi_plan"]["metas_temporais"].get("3_anos", {}).get("foco_principal", ""))
                with st.container(border=True):
                    st.markdown("**Em 10 Anos**")
                    meta_10_anos_cargo = st.text_input("Cargo Alvo (10 Anos)", value=pdi_data["pdi_plan"]["metas_temporais"].get("10_anos", {}).get("cargo_alvo", ""))
                    meta_10_anos_foco = st.text_area("Foco Principal (10 Anos)", height=100, value=pdi_data["pdi_plan"]["metas_temporais"].get("10_anos", {}).get("foco_principal", ""))
            if st.form_submit_button("Salvar Plano de Carreira", type="primary"):
                pdi_data["pdi_plan"]["objetivo_final"] = objetivo_final
                pdi_data["pdi_plan"]["metas_temporais"]["1_ano"] = {"cargo_alvo": meta_1_ano_cargo, "foco_principal": meta_1_ano_foco}
                pdi_data["pdi_plan"]["metas_temporais"]["3_anos"] = {"cargo_alvo": meta_3_anos_cargo, "foco_principal": meta_3_anos_foco}
                pdi_data["pdi_plan"]["metas_temporais"]["5_anos"] = {"cargo_alvo": meta_5_anos_cargo, "foco_principal": meta_5_anos_foco}
                pdi_data["pdi_plan"]["metas_temporais"]["10_anos"] = {"cargo_alvo": meta_10_anos_cargo, "foco_principal": meta_10_anos_foco}
                pdi_data["pdi_plan"]["metas_temporais"]["15_anos"] = {"cargo_alvo": meta_15_anos_cargo, "foco_principal": meta_15_anos_foco}
                save_pdi_data(user_email, pdi_data)
                st.success("Seu plano de carreira foi salvo!")

    elif page == "📊 Meu Diagnóstico":
        st.header("📊 Meu Diagnóstico de Carreira")
        st.markdown("Receba uma análise completa da IA sobre seu plano.")

        # --- INÍCIO DA MODIFICAÇÃO DE LOCK ---
        LOCK_FILE = Path("analysis.lock")

        # Verifica se uma análise já está em andamento no servidor
        if LOCK_FILE.exists():
            st.warning("⚠️ Um processo de análise já está em andamento no servidor. Por favor, aguarde alguns minutos e tente novamente.")
            st.info("Isso garante que cada análise receba os recursos necessários para ser concluída com sucesso.")
        
    elif st.session_state.analysis_process is None:
        if st.button("Analisar meu PDI com a IA", type="primary"):
            if not pdi_data.get("profile", {}).get("linkedin_url"):
                st.error("Por favor, insira a URL do seu LinkedIn em 'Meu Perfil'.")
            else:
                # Cria o arquivo de lock ANTES de iniciar o processo
                LOCK_FILE.touch()
                
                q = multiprocessing.Manager().Queue()
                # Passamos o caminho do lock file para o processo filho
                proc = multiprocessing.Process(target=run_full_analysis_process, args=(q, user_email, str(LOCK_FILE)), daemon=True)
                st.session_state.q_from_process = q
                st.session_state.analysis_process = proc
                proc.start()
                st.rerun()
        
        if st.session_state.analysis_process is not None:
            status_placeholder = st.empty()
            try:
                msg = st.session_state.q_from_process.get_nowait()
                st.session_state.last_status = msg
                if isinstance(msg, dict):
                    if msg.get("status") == "complete":
                        st.success("Análise concluída!")
                        st.balloons()
                        save_pdi_data(user_email, msg.get("data"))
                        st.session_state.analysis_process = None
                        st.rerun()
                    elif msg.get("status") == "error":
                        st.error(f"Erro: {msg.get('message')}")
                        st.session_state.analysis_process = None
                        st.rerun()
            except (queue.Empty, EOFError): pass
            if st.session_state.last_status and isinstance(st.session_state.last_status, dict):
                if st.session_state.last_status.get("status") == "info":
                    status_placeholder.info(st.session_state.last_status.get("message"))
            if st.session_state.analysis_process and st.session_state.analysis_process.is_alive():
                time.sleep(1)
                st.rerun()

        if "ai_analysis" in pdi_data and pdi_data["ai_analysis"]:
            analysis = pdi_data["ai_analysis"]
            
            st.download_button(
                label="📥 Baixar Diagnóstico em PDF",
                data=generate_pdi_pdf(pdi_data),
                file_name=f"PDI_Diagnostico_{user_email.split('@')[0]}.pdf",
                mime="application/pdf"
            )

            st.markdown("---")
            st.subheader("💡 Análise Geral da IA")
            st.info(analysis.get("analise_geral", "N/A"))
            
            st.subheader("🏢 Perfil de Empresa Ideal")
            empresa_ideal = analysis.get("tipo_empresa_ideal", {})
            if isinstance(empresa_ideal, dict):
                with st.container(border=True):
                    for key, value in empresa_ideal.items():
                        st.markdown(f"**{key.capitalize()}:** {value}")
            else:
                st.success(empresa_ideal)
            
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("🎯 Plano SMART (Próximo Ano)")
                with st.container(border=True):
                    smart_plan = analysis.get("plano_smart_1_ano", {})
                    if isinstance(smart_plan, dict):
                        for key in ['S', 'M', 'A', 'R', 'T']:
                            value = smart_plan.get(key)
                            if not value: continue
                            
                            st.markdown(f"**{key.upper()}:**")
                            # Tratamento M no Streamlit (lista de dicts com detalhe + metrica)
                            if key == "M":
                                if isinstance(value, list):
                                    for idx, item in enumerate(value, start=1):
                                        if isinstance(item, dict):
                                            detalhe = item.get("detalhe", "")
                                            metrica = item.get("metrica", "")
                                            if metrica:
                                                st.markdown(f"{idx}. {detalhe}  \n*(Métrica: {metrica})*")
                                            else:
                                                st.markdown(f"{idx}. {detalhe}")
                                        else:
                                            st.markdown(f"- {item}")
                                    continue
                                # se não for lista, cairá no fluxo padrão abaixo

                            # Tratamento T no Streamlit (data limite + cronograma)
                            if key == "T":
                                if isinstance(value, dict):
                                    data_limite = value.get("Data limite") or value.get("Data_limite") or value.get("data limite") or value.get("data_limite") or value.get("data")
                                    if data_limite:
                                        st.write(f"**Data limite:** {data_limite}")
                                    cronograma = value.get("Cronograma") or value.get("cronograma") or value.get("Trimestre") or value.get("trimestres") or value.get("Trimestres")
                                    # Cronograma como lista
                                    if isinstance(cronograma, list):
                                        for trimestre in cronograma:
                                            if isinstance(trimestre, dict):
                                                tr_nome = trimestre.get("Trimestre") or trimestre.get("trimestre") or ""
                                                foco = trimestre.get("Foco") or trimestre.get("foco") or ""
                                                if tr_nome or foco:
                                                    st.markdown(f"**{tr_nome}** — Foco: {foco}")
                                                acoes = trimestre.get("Acoes") or trimestre.get("acoes") or []
                                                for acao in acoes:
                                                    st.markdown(f"- {acao}")
                                            else:
                                                st.markdown(f"- {trimestre}")
                                        continue
                                    elif isinstance(cronograma, dict):
                                        for tr_key, tr_val in cronograma.items():
                                            foco = ""
                                            acoes = []
                                            if isinstance(tr_val, dict):
                                                foco = tr_val.get("Foco") or tr_val.get("foco") or ""
                                                acoes = tr_val.get("Acoes") or tr_val.get("acoes") or []
                                            else:
                                                if isinstance(tr_val, list):
                                                    acoes = tr_val
                                                else:
                                                    acoes = [tr_val]
                                            if foco:
                                                st.markdown(f"**{tr_key}** — Foco: {foco}")
                                            else:
                                                st.markdown(f"**{tr_key}**")
                                            for acao in acoes:
                                                st.markdown(f"- {acao}")
                                        continue
                                    else:
                                        # fallback: imprime o dict inteiro de forma legível
                                        for sub_k, sub_v in value.items():
                                            # ignora campos já mostrados
                                            if sub_k in ("Data limite", "Data_limite", "Cronograma", "cronograma"):
                                                continue
                                            st.markdown(f"*{sub_k}*")
                                            if isinstance(sub_v, list):
                                                for item in sub_v:
                                                    st.markdown(f"- {item}")
                                            else:
                                                st.write(sub_v)
                                        continue
                                elif isinstance(value, list):
                                    for item in value:
                                        if isinstance(item, dict):
                                            tr_nome = item.get("Trimestre") or item.get("trimestre") or ""
                                            foco = item.get("Foco") or item.get("foco") or ""
                                            if tr_nome or foco:
                                                st.markdown(f"**{tr_nome}** — Foco: {foco}")
                                            acoes = item.get("Acoes") or item.get("acoes") or []
                                            for acao in acoes:
                                                st.markdown(f"- {acao}")
                                        else:
                                            st.markdown(f"- {item}")
                                    continue
                                else:
                                    st.write(value)
                                    continue

                            # Fluxo genérico (S, A, R ou outros formatos)
                            if isinstance(value, dict):
                                for sub_key, sub_value in value.items():
                                    sub_key_formatted = sub_key.replace('_', ' ').capitalize()
                                    st.markdown(f"*{sub_key_formatted}*")
                                    if isinstance(sub_value, list):
                                        for item in sub_value:
                                            if isinstance(item, dict):
                                                for k, v in item.items():
                                                    st.markdown(f"- **{k.capitalize()}:** {v}")
                                            else:
                                                st.markdown(f"- {item}")
                                    else:
                                        st.write(sub_value)
                            else:
                                st.write(value)
                    else:
                        st.write(smart_plan)

            with col2:
                st.subheader("🗺️ Próximos Passos (3 Meses)")
                with st.container(border=True):
                    for step in analysis.get("proximos_passos", []):
                        st.checkbox(step)
                st.subheader("🤔 Cargos Similares Sugeridos")
                with st.container(border=True):
                    for job in analysis.get("sugestao_cargos_similares", []):
                        st.markdown(f"- {job}")

            st.markdown("---")
            st.subheader("⭐ Recomendações Focadas")
            recomendacoes = analysis.get("recomendacoes_focadas", [])
            if isinstance(recomendacoes, list) and recomendacoes:
                for rec in recomendacoes:
                    with st.container(border=True):
                        st.markdown(f"**Foco:** {rec.get('foco', 'N/A')}")
                        st.write(rec.get('recomendacao', 'N/A'))
            else:
                st.warning("Nenhuma recomendação específica foi gerada.")

            st.markdown("---")
            st.subheader("🗺️ Plano de Ação Detalhado (Sugerido pela IA)")
            plano_ia = analysis.get("plano_de_acao_ia", {})
            c1, c2 = st.columns(2)
            with c1:
                with st.expander("**Plano para 1 Ano**", expanded=True):
                    for item in plano_ia.get("1_ano", ["N/A"]):
                        st.checkbox(item, key=f"1_ano_{item}")
                with st.expander("**Plano para 5 Anos**"):
                    for item in plano_ia.get("5_anos", ["N/A"]):
                        st.checkbox(item, key=f"5_anos_{item}")
                with st.expander("**Plano para 15 Anos**"):
                    for item in plano_ia.get("15_anos", ["N/A"]):
                        st.checkbox(item, key=f"15_anos_{item}")
            with c2:
                with st.expander("**Plano para 3 Anos**"):
                    for item in plano_ia.get("3_anos", ["N/A"]):
                        st.checkbox(item, key=f"3_anos_{item}")
                with st.expander("**Plano para 10 Anos**"):
                    for item in plano_ia.get("10_anos", ["N/A"]):
                        st.checkbox(item, key=f"10_anos_{item}")
        
        elif st.session_state.analysis_process is None:
            st.info("Nenhuma análise foi realizada ainda.")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

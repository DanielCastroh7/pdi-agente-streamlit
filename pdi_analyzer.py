# pdi_analyzer.py
import google.generativeai as genai
import json
from pathlib import Path
import traceback
from datetime import date, timedelta
import subprocess
import os

# Importa a função de scraping
from linkedin_scraper import scrape_linkedin_profile
# Importa as funções de dados do auth.py
from auth import load_pdi_data_from_firestore

# Tenta importar a chave de API do config.py para desenvolvimento local
try:
    from config import GEMINI_API_KEY
except ImportError:
    GEMINI_API_KEY = None

# --- CONFIGURAÇÃO DA IA GEMINI ---
# Usa st.secrets em produção ou config.py em desenvolvimento.
try:
    # Modo Produção (Streamlit Cloud)
    import streamlit as st
    genai.configure(api_key=st.secrets["gemini_api_key"])
except (AttributeError, KeyError, FileNotFoundError, ImportError):
    # Modo Desenvolvimento Local
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
    else:
        print("AVISO: Chave da API do Gemini não configurada em st.secrets ou config.py.")
        pass

model = genai.GenerativeModel('gemini-2.5-pro')

# --- FUNÇÕES DE ANÁLISE DA IA (SEPARADAS) ---

def call_gemini_api(prompt, response_key):
    """Função genérica para chamar a API e extrair a resposta."""
    try:
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "")
        result = json.loads(cleaned_response)
        return result.get(response_key)
    except Exception as e:
        print(f"Erro na chamada da API para '{response_key}': {e}")
        return f"Erro ao gerar esta seção: {e}"

def get_analise_geral(profile, plan):
    prompt = f"""
    Baseado no perfil e plano de carreira abaixo, escreva uma análise geral concisa (3-4 frases) sobre a coerência, ambição e realismo do plano.
    PERFIL: {json.dumps(profile)}
    PLANO: {json.dumps(plan)}
    Responda APENAS com um objeto JSON com a chave "analise_geral".
    """
    return call_gemini_api(prompt, "analise_geral")

def get_tipo_empresa_ideal(profile, plan):
    prompt = f"""
    Com base no objetivo final de '{plan.get('objetivo_final')}' e no perfil abaixo, descreva o tipo de empresa (cultura, setor, tamanho) onde este profissional teria mais chances de prosperar.
    PERFIL: {json.dumps(profile)}
    Responda APENAS com um objeto JSON com a chave "tipo_empresa_ideal" contendo as chaves "cultura", "setor" e "tamanho".
    """
    return call_gemini_api(prompt, "tipo_empresa_ideal")

def get_sugestao_cargos_similares(profile, plan):
    prompt = f"""
    Analisando o perfil e o objetivo de '{plan.get('objetivo_final')}', sugira uma lista de 2 a 3 títulos de cargos alternativos ou complementares.
    PERFIL: {json.dumps(profile)}
    Responda APENAS com um objeto JSON com a chave "sugestao_cargos_similares" contendo uma lista de strings.
    """
    return call_gemini_api(prompt, "sugestao_cargos_similares")

def get_plano_smart(profile, plan):
    today = date.today()
    target_date = today + timedelta(days=365)
    today_str = today.strftime("%d/%m/%Y")
    target_date_str = target_date.strftime("%d/%m/%Y")

    prompt = f"""
    A data de hoje é {today_str}. Crie um plano de ação SMART detalhado para a meta de 1 ano: '{plan.get('metas_temporais', {}).get('1_ano', {})}'.
    Responda APENAS com um objeto JSON com a chave "plano_smart_1_ano" contendo as chaves "S", "M", "A", "R", "T".
    Para "S" e "R", gere um texto simples.
    Para "M", gere uma lista de dicionários, cada um com as chaves "metrica" e "detalhe".
    Para "A", gere um dicionário com as chaves "Acoes_Especificas" e "Recursos_Necessarios", ambas contendo listas de strings.
    Para "T", gere um dicionário com as chaves "cronograma" (uma lista de dicionários, cada um com "trimestre", "foco" e "acoes" [lista de strings]) e "data_limite" (com o valor **{target_date_str}**).
    PERFIL: {json.dumps(profile)}
    """
    return call_gemini_api(prompt, "plano_smart_1_ano")

def get_proximos_passos(profile, plan):
    prompt = f"""
    Com base no plano de carreira, liste de 3 a 5 ações práticas e imediatas que este profissional deve tomar nos próximos 3 meses.
    PLANO: {json.dumps(plan)}
    Responda APENAS com um objeto JSON com a chave "proximos_passos" contendo uma lista de strings.
    """
    return call_gemini_api(prompt, "proximos_passos")

def get_recomendacoes_focadas(profile, plan):
    prompt = f"""
    Com base nos 'Pontos a Melhorar' ({profile.get('pontos_a_melhorar', [])}) e no objetivo de carreira, forneça 2 ou 3 recomendações diretas sobre como o profissional pode trabalhar nesses pontos para acelerar seus objetivos.
    Responda APENAS com um objeto JSON com a chave "recomendacoes_focadas" contendo uma lista de dicionários (com chaves "foco" e "recomendacao").
    """
    return call_gemini_api(prompt, "recomendacoes_focadas")

def get_plano_de_acao_ia(profile, plan):
    prompt = f"""
    Para cada período do plano de carreira abaixo, crie uma lista de 3 a 5 ações/marcos concretos que o profissional deve alcançar para se manter na trilha certa.
    PLANO: {json.dumps(plan)}
    Responda APENAS com um objeto JSON com a chave "plano_de_acao_ia" contendo as chaves "1_ano", "3_anos", "5_anos", "10_anos", "15_anos", cada uma com uma lista de strings.
    """
    return call_gemini_api(prompt, "plano_de_acao_ia")

# --- FUNÇÃO PRINCIPAL DO PROCESSO ---
def run_full_analysis_process(q_to_ui, user_email):
    """
    Função alvo para o multiprocessing. Executa o scraping e a análise em um processo separado.
    """
    try:
        # --- INÍCIO DA MODIFICAÇÃO ---
        # Adicionamos este bloco para instalar o Playwright e suas dependências no ambiente da nuvem.
        q_to_ui.put({"status": "info", "message": "Inicializando análise... Verificando dependências do navegador..."})
        try:
            # O comando "--with-deps" ajuda a instalar bibliotecas do sistema necessárias
            # O timeout evita que o processo fique preso indefinidamente.
            subprocess.run(["playwright", "install", "--with-deps"], check=True, timeout=180)
            q_to_ui.put({"status": "info", "message": "Dependências prontas."})
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            # Se o comando falhar, envia uma mensagem de erro clara e interrompe o processo.
            error_message = f"Falha crítica ao instalar dependências do navegador com Playwright: {e}. Isso pode ocorrer em ambientes sem permissão. Tente reiniciar o app."
            print(error_message) # Log no terminal
            q_to_ui.put({"status": "error", "message": error_message})
            return # Interrompe a execução
        # --- FIM DA MODIFICAÇÃO ---

        q_to_ui.put({"status": "info", "message": "Passo 1/8: Lendo seu perfil no LinkedIn..."})
        pdi_data = load_pdi_data_from_firestore(user_email)
        
        linkedin_url = pdi_data.get("profile", {}).get("linkedin_url")
        if not linkedin_url: raise ValueError("URL do LinkedIn não encontrada no perfil.")
            
        full_text = scrape_linkedin_profile(linkedin_url)
        pdi_data["profile"]["full_linkedin_text"] = full_text

        profile = pdi_data["profile"]
        plan = pdi_data["pdi_plan"]
        ai_analysis = {}

        q_to_ui.put({"status": "info", "message": "Passo 2/8: Gerando Análise Geral..."})
        ai_analysis["analise_geral"] = get_analise_geral(profile, plan)
        
        q_to_ui.put({"status": "info", "message": "Passo 3/8: Definindo Perfil de Empresa Ideal..."})
        ai_analysis["tipo_empresa_ideal"] = get_tipo_empresa_ideal(profile, plan)

        q_to_ui.put({"status": "info", "message": "Passo 4/8: Sugerindo Cargos Similares..."})
        ai_analysis["sugestao_cargos_similares"] = get_sugestao_cargos_similares(profile, plan)

        q_to_ui.put({"status": "info", "message": "Passo 5/8: Criando seu Plano SMART..."})
        ai_analysis["plano_smart_1_ano"] = get_plano_smart(profile, plan)

        q_to_ui.put({"status": "info", "message": "Passo 6/8: Listando Próximos Passos..."})
        ai_analysis["proximos_passos"] = get_proximos_passos(profile, plan)

        q_to_ui.put({"status": "info", "message": "Passo 7/8: Gerando Recomendações Focadas..."})
        ai_analysis["recomendacoes_focadas"] = get_recomendacoes_focadas(profile, plan)

        q_to_ui.put({"status": "info", "message": "Passo 8/8: Construindo Plano de Ação Detalhado..."})
        ai_analysis["plano_de_acao_ia"] = get_plano_de_acao_ia(profile, plan)

        pdi_data["ai_analysis"] = ai_analysis
        q_to_ui.put({"status": "complete", "data": pdi_data})

    except Exception as e:
        tb_str = traceback.format_exc()
        print(f"ERRO NO PROCESSO: {e}\n{tb_str}")
        q_to_ui.put({"status": "error", "message": f"Ocorreu um erro no processo: {e}"})

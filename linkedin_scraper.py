# linkedin_scraper.py
import time
from playwright.sync_api import sync_playwright, TimeoutError

def scrape_linkedin_profile(url: str) -> str:
    """
    Acessa uma URL do LinkedIn de forma mais robusta, esperando o conteúdo carregar
    e simulando um navegador real para extrair o texto visível.
    """
    full_text = ""
    browser = None # Inicializa a variável do browser
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            
            # 1. Simular um navegador de verdade com um User-Agent comum
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # 2. Navegar para a URL de forma paciente
            #    wait_until="networkidle" espera a página e seus scripts terminarem de carregar
            print("Acessando a URL do LinkedIn e aguardando o carregamento completo...")
            page.goto(url, wait_until="networkidle", timeout=60000) # Timeout de 60s

            # 3. Esperar por um elemento chave do perfil aparecer na tela
            #    Em vez de pegar o 'body' inteiro, esperamos pelo container principal do perfil
            print("Página carregada. Aguardando o conteúdo principal do perfil...")
            main_content_selector = "main" # O elemento <main> geralmente contém o perfil
            page.wait_for_selector(main_content_selector, state="visible", timeout=30000)

            # 4. Pausa extra para garantir que todos os scripts finais rodem
            time.sleep(1.5)

            # 5. Agora sim, extrair o texto do conteúdo principal
            print("Extraindo texto do perfil...")
            full_text = page.locator(main_content_selector).first.inner_text()

            print("Scraping concluído com sucesso.")
            return full_text

    except Exception as e:
        print(f"ERRO DURANTE O SCRAPING: {e}")
        # Se um erro ocorrer, é útil saber qual texto foi extraído (se houver)
        if full_text:
            print("Texto parcial extraído antes do erro:", full_text[:200])
        # A exceção será capturada pela função principal em pdi_analyzer.py
        raise e
        
    finally:
        # 6. Garantir que o navegador seja sempre fechado
        if browser:
            browser.close()

# def scrape_linkedin_profile(profile_url: str) -> str:
#     """
#     Navega até um perfil público do LinkedIn e extrai todo o texto visível.

#     Args:
#         profile_url: A URL completa do perfil público do LinkedIn.

#     Returns:
#         Uma string contendo todo o texto extraído do perfil, ou uma mensagem de erro.
#     """
#     print(f"Iniciando scraping para a URL: {profile_url}")
    
#     full_text = ""

#     with sync_playwright() as p:
#         try:
#             browser = p.chromium.launch(headless=True) # headless=True para rodar em segundo plano
#             page = browser.new_page()
#             page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)

#             print("Página carregada. Iniciando rolagem para carregar todo o conteúdo...")

#             # Rola a página para baixo para garantir que todo o conteúdo dinâmico seja carregado
#             last_height = page.evaluate("document.body.scrollHeight")
#             while True:
#                 page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
#                 time.sleep(2) # Espera o conteúdo carregar
#                 new_height = page.evaluate("document.body.scrollHeight")
#                 if new_height == last_height:
#                     break
#                 last_height = new_height
            
#             print("Rolagem completa. Extraindo texto...")

#             # Extrai o texto do contêiner principal do perfil
#             # Este seletor é mais genérico e tende a funcionar mesmo com mudanças no layout
#             main_content = page.locator("main.scaffold-layout__main").first
#             if main_content.is_visible():
#                 full_text = main_content.inner_text()
#                 print("Texto extraído com sucesso.")
#             else:
#                 full_text = "Erro: Não foi possível encontrar o contêiner principal do perfil."
#                 print(full_text)

#             browser.close()

#         except TimeoutError:
#             error_message = f"Erro: A página '{profile_url}' demorou muito para carregar ou é inválida."
#             print(error_message)
#             return error_message
#         except Exception as e:
#             error_message = f"Ocorreu um erro inesperado durante o scraping: {e}"
#             print(error_message)
#             return error_message
            
#     return full_text

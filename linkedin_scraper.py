# linkedin_scraper.py
import time
from playwright.sync_api import sync_playwright, TimeoutError

### VERSÃO 2
# def scrape_linkedin_profile(url: str) -> str:
#     """
#     Scraper robusto com gerenciamento de ciclo de vida corrigido,
#     deixando o contexto 'with' responsável por todo o encerramento.
#     """
#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         try:
#             context = browser.new_context(
#                 user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
#             )
#             page = context.new_page()

#             print("Acessando a URL e aguardando a rede...")
#             page.goto(url, wait_until="networkidle", timeout=60000)

#             page_title = page.title()
#             print(f"Título da página carregada: '{page_title}'")
#             if "Sign In" in page_title or "Entrar" in page_title or "Security" in page_title:
#                 raise Exception(f"Página de login ou verificação de segurança detectada. Título: '{page_title}'. O scraping não pode continuar sem autenticação.")

#             main_content_selector = "main"
#             print("Aguardando pelo seletor principal do perfil...")
#             page.wait_for_selector(main_content_selector, state="visible", timeout=30000)
            
#             print("Extraindo texto...")
#             full_text = page.locator(main_content_selector).first.inner_text()

#             if not full_text.strip():
#                  raise Exception("Conteúdo do perfil extraído está vazio. A página pode ter carregado incorretamente.")

#             print("Scraping concluído com sucesso.")
#             return full_text

#         except TimeoutError:
#             print("ERRO DE TIMEOUT: O elemento esperado (perfil principal) não apareceu a tempo.")
#             page.screenshot(path="debug_timeout.png")
#             raise Exception("Tempo de espera esgotado. O LinkedIn provavelmente apresentou uma página inesperada (login/CAPTCHA).")

#         except Exception as e:
#             print(f"ERRO INESPERADO DURANTE O SCRAPING: {e}")
#             if 'page' in locals():
#                 page.screenshot(path="debug_error.png")
#             raise e

### VERSÃO 1
def scrape_linkedin_profile(profile_url: str) -> str:
    """
    Navega até um perfil público do LinkedIn e extrai todo o texto visível.

    Args:
        profile_url: A URL completa do perfil público do LinkedIn.

    Returns:
        Uma string contendo todo o texto extraído do perfil, ou uma mensagem de erro.
    """
    print(f"Iniciando scraping para a URL: {profile_url}")
    
    full_text = ""

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True) # headless=True para rodar em segundo plano
            page = browser.new_page()
            page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)

            print("Página carregada. Iniciando rolagem para carregar todo o conteúdo...")

            # Rola a página para baixo para garantir que todo o conteúdo dinâmico seja carregado
            last_height = page.evaluate("document.body.scrollHeight")
            while True:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(2) # Espera o conteúdo carregar
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height
            
            print("Rolagem completa. Extraindo texto...")

            # Extrai o texto do contêiner principal do perfil
            # Este seletor é mais genérico e tende a funcionar mesmo com mudanças no layout
            main_content = page.locator("main.scaffold-layout__main").first
            if main_content.is_visible():
                full_text = main_content.inner_text()
                print("Texto extraído com sucesso.")
            else:
                full_text = "Erro: Não foi possível encontrar o contêiner principal do perfil."
                print(full_text)

            browser.close()

        except TimeoutError:
            error_message = f"Erro: A página '{profile_url}' demorou muito para carregar ou é inválida."
            print(error_message)
            return error_message
        except Exception as e:
            error_message = f"Ocorreu um erro inesperado durante o scraping: {e}"
            print(error_message)
            return error_message
            
    return full_text


### VERSÃO 3
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
#             print("ERRO DE TIMEOUT...")
#             # --- MODIFICAÇÃO ---
#             timestamp = int(time.time())
#             screenshot_path = f"debug_timeout_{timestamp}.png"
#             page.screenshot(path=screenshot_path)
#             # ...
#             raise Exception("Tempo de espera esgotado...")

#         except Exception as e:
#             print(f"ERRO INESPERADO...")
#             if 'page' in locals():
#                 # --- MODIFICAÇÃO ---
#                 timestamp = int(time.time())
#                 screenshot_path = f"debug_error_{timestamp}.png"
#                 page.screenshot(path=screenshot_path)
#             raise e
            
#     return full_text
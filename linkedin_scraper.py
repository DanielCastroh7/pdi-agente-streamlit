# linkedin_scraper.py
import time
from playwright.sync_api import sync_playwright, TimeoutError

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

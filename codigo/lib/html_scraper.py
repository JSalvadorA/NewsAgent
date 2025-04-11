# codigo/lib/html_scraper.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
import re
import time
import random
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager # Gestiona driver

# Importar utilidades locales
from .cache_utils import get_cache_key, load_from_cache, save_to_cache
from .file_manager import save_to_json # Para guardar progreso
from .request_utils import get_session # Importar sistema centralizado de sesiones

logger = logging.getLogger(__name__)

# --- Funciones de ayuda ---

def normalize_text(text):
    """Limpia y normaliza el texto extraído."""
    if not text:
        return ""
    # Reemplaza múltiples espacios/saltos de línea con un solo espacio
    text = re.sub(r'\s+', ' ', text)
    # Elimina espacios al principio/final
    return text.strip()

def calculate_relevance(text, keywords):
    """Calcula una puntuación de relevancia simple basada en palabras clave."""
    if not text or not keywords:
        return 0.0
    text_lower = text.lower()
    score = 0.0
    # Ponderación simple, SUNASS más importante
    weights = {kw.lower(): (0.5 if kw.lower() == "sunass" else 0.2) for kw in keywords}

    found_keywords = set()
    for keyword, weight in weights.items():
        if keyword in text_lower:
             # Contar solo una vez por palabra clave única
            if keyword not in found_keywords:
                 score += weight
                 found_keywords.add(keyword)


    # Normalizar score para que esté entre 0 y 1 (aproximadamente)
    # Podría ser > 1 si hay muchas palabras clave, limitar a 1.
    return min(score, 1.0)


def setup_selenium_driver():
     """Configura e inicializa un driver de Selenium headless."""
     options = Options()
     options.add_argument("--headless")
     options.add_argument("--disable-gpu") # A veces necesario en headless
     options.add_argument("--window-size=1920x1080") # Definir tamaño ventana
     options.add_argument("--no-sandbox") # Necesario en algunos entornos Linux/Docker
     options.add_argument("--disable-dev-shm-usage") # Necesario en algunos entornos Linux/Docker
     # Evitar detección de bot (básico)
     options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36") # Usar el user-agent solicitado
     options.add_experimental_option('excludeSwitches', ['enable-logging']) # Limpiar output consola


     try:
        # Usa webdriver-manager para descargar/gestionar el chromedriver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        logger.info("Driver de Selenium (Chrome) inicializado correctamente.")
        return driver
     except Exception as e:
        logger.error(f"Error inicializando Selenium WebDriver: {e}")
        logger.error("Asegúrate de que Chrome esté instalado y accesible.")
        logger.error("O verifica problemas con webdriver-manager (puede requerir conexión a internet la primera vez).")
        return None


def scrape_with_selenium(url, driver):
    """Realiza scraping usando una instancia existente de Selenium WebDriver."""
    if not driver:
         logger.error("Intento de scrape con Selenium sin driver válido.")
         return {"error": "Selenium driver not initialized"}

    try:
        logger.debug(f"Scrapeando con Selenium: {url}")
        driver.get(url)
        # Espera inteligente podría ser mejor, pero simple sleep por ahora
        time.sleep(random.uniform(3, 5)) # Espera para carga JS

        page_source = driver.page_source
        current_url = driver.current_url
        title = driver.title

        soup = BeautifulSoup(page_source, "html.parser")

        # Eliminar tags no deseados (scripts, estilos, etc.)
        for tag in soup(["script", "style", "header", "footer", "nav", "aside", "form"]):
            tag.decompose()

        text = normalize_text(soup.get_text(separator=' ', strip=True))

        content = {
            "metadata": {"title": title, "url": current_url},
            "text": text,
            "content_type": "text/html (selenium)"
        }
        return content

    except Exception as e:
        logger.warning(f"Error scrapeando {url} con Selenium: {e}")
        return {"error": f"Selenium scrape failed: {str(e)}"}


# --- Clase principal del Scraper ---

class HTMLScraper:
    def __init__(self, config):
        self.config = config
        self.session = get_session()  # Usar sesión global compartida
        self.headers = config.get('headers', {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124'}) # Usa User-Agent de config
        self.cache_dir = config.get('paths', {}).get('cache_dir')
        self.cache_expiry = config.get('cache_expiry')
        self.keywords = config.get('keywords', [])
        self.selenium_driver = None # Inicializar driver solo si se necesita

    def _get_selenium_driver(self):
         """Obtiene o inicializa el driver de Selenium."""
         try:
             # Verificar si el driver existente está activo
             if self.selenium_driver is not None:
                 try:
                     # Intentar una acción simple para verificar si el driver está activo
                     self.selenium_driver.current_url
                     return self.selenium_driver
                 except Exception:
                     logger.warning("Driver de Selenium existente no responde. Reinicializando...")
                     try:
                         self.selenium_driver.quit()
                     except:
                         pass
                     self.selenium_driver = None
             
             # Inicializar nuevo driver
             self.selenium_driver = setup_selenium_driver()
             return self.selenium_driver
         except Exception as e:
             logger.error(f"Error inicializando driver de Selenium: {e}")
             return None

    def close_selenium_driver(self):
         """Cierra el driver de Selenium si está abierto."""
         if self.selenium_driver:
             try:
                 self.selenium_driver.quit()
                 logger.info("Driver de Selenium cerrado.")
             except Exception as e:
                 logger.warning(f"Error cerrando driver Selenium: {e}")
             finally:
                 self.selenium_driver = None


    def scrape_single_url(self, url_info):
        """
        Realiza el scraping de una única URL (diccionario con 'URL', 'Context', 'Page').
        Gestiona caché y decide si usar Requests o Selenium.
        Implementa reintentos adaptativos para problemas de conexión.
        """
        url = url_info.get("URL")
        context = url_info.get("Context", "")
        page = url_info.get("Page", None)

        if not url:
            return url, {"error": "URL vacía", "context": context, "page": page}

        cache_key = get_cache_key(url)
        if self.cache_dir and self.cache_expiry is not None:
            cached_result = load_from_cache(self.cache_dir, cache_key, self.cache_expiry)
            if cached_result:
                logger.debug(f"Usando caché para {url}")
                # Añadir contexto y página al resultado cacheado si no lo tiene
                if 'context' not in cached_result: cached_result['context'] = context
                if 'page' not in cached_result: cached_result['page'] = page
                return url, cached_result

        # Decidir si usar Selenium (para sitios dinámicos o problemáticos)
        use_selenium = False
        if any(domain in url.lower() for domain in [
                'facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com',
                'javascript', 'dynamic', 'react', 'angular', 'vue'
            ]):
             use_selenium = True
             logger.info(f"Usando Selenium para: {url}")

        # Configuración de reintentos
        max_retries = 3  # Número máximo de intentos
        retry_delays = [2, 5, 10]  # Segundos de espera entre reintentos (aumenta progresivamente)
        retry_count = 0
        result = {}
        last_error = None
        
        # Bucle de reintentos
        while retry_count <= max_retries:
            try:
                if use_selenium:
                    driver = self._get_selenium_driver()
                    if driver:
                         content = scrape_with_selenium(url, driver)
                    else:
                         content = {"error": "Selenium driver failed to initialize"}
                         # No tiene sentido reintentar si el driver falló
                         break
                else:
                    # Usar Requests
                    logger.debug(f"Scrapeando con Requests{' (reintento '+str(retry_count)+')' if retry_count > 0 else ''}: {url}")
                    response = self.session.get(url, headers=self.headers, timeout=30 if retry_count > 0 else 20, allow_redirects=True)
                    response.raise_for_status() # Error si no es 2xx

                    content_type = response.headers.get('Content-Type', '').lower()
                    if 'text/html' not in content_type:
                        logger.info(f"Contenido no es HTML para {url} ({content_type}). Omitiendo body.")
                        content = {"content_type": content_type, "message": "No HTML content", "metadata": {"url": response.url}} # Guardar URL final
                    else:
                        # Asegurar codificación correcta
                        response.encoding = response.apparent_encoding if response.apparent_encoding else 'utf-8'
                        soup = BeautifulSoup(response.text, "html.parser")

                        # Extraer metadatos
                        title_tag = soup.find("title")
                        title = title_tag.string.strip() if title_tag else ""
                        description_tag = soup.find("meta", attrs={"name": re.compile(r"description", re.I)})
                        description = description_tag["content"].strip() if description_tag and description_tag.get("content") else ""

                        metadata = {"title": title, "description": description, "url": response.url} # Guardar URL final

                        # Limpiar HTML antes de extraer texto
                        for tag in soup(["script", "style", "header", "footer", "nav", "aside", "form"]):
                             tag.decompose()

                        text = normalize_text(soup.get_text(separator=' ', strip=True))
                        content = {"metadata": metadata, "text": text, "content_type": "text/html"}

                # Añadir contexto, página y calcular relevancia a cualquier resultado exitoso (no error)
                if "error" not in content:
                    full_text_for_relevance = f"{content.get('metadata', {}).get('title', '')} {content.get('metadata', {}).get('description', '')} {content.get('text', '')}"
                    content["relevance"] = calculate_relevance(full_text_for_relevance, self.keywords)

                # Añadir siempre contexto y página al resultado final
                content["context"] = context
                content["page"] = page
                result = content

                # Guardar en caché si fue exitoso (sin error) y el caché está habilitado
                if "error" not in result and self.cache_dir:
                    save_to_cache(self.cache_dir, cache_key, result)

                # Si llegamos aquí sin errores, salimos del bucle de reintentos
                break

            except requests.exceptions.Timeout:
                last_error = "Timeout"
                logger.warning(f"Timeout scrapeando {url}{' (intento '+str(retry_count+1)+'/'+str(max_retries+1)+')' if retry_count < max_retries else ''}")
            except requests.exceptions.HTTPError as e:
                last_error = f"HTTP Error: {e.response.status_code}"
                status_code = e.response.status_code
                # No reintentar para errores 4xx (excepto 429 Too Many Requests)
                if status_code // 100 == 4 and status_code != 429:
                    logger.warning(f"Error HTTP {status_code} scrapeando {url} (no se reintentará): {e}")
                    result = {"error": last_error, "status_code": status_code, "context": context, "page": page}
                    break
                logger.warning(f"Error HTTP {status_code} scrapeando {url}{' (intento '+str(retry_count+1)+'/'+str(max_retries+1)+')' if retry_count < max_retries else ''}: {e}")
            except requests.exceptions.RequestException as e:
                last_error = f"Network Error: {str(e)}"
                logger.warning(f"Error de red scrapeando {url}{' (intento '+str(retry_count+1)+'/'+str(max_retries+1)+')' if retry_count < max_retries else ''}: {e}")
            except Exception as e:
                last_error = f"Unexpected Error: {str(e)}"
                logger.error(f"Error inesperado scrapeando {url}{' (intento '+str(retry_count+1)+'/'+str(max_retries+1)+')' if retry_count < max_retries else ''}: {e}", exc_info=True)
                # Para errores inesperados, solo reintentar una vez
                if retry_count >= 1:
                    break
            
            # Incrementar contador de reintentos
            retry_count += 1
            
            # Si hemos alcanzado el máximo de reintentos, registramos el error
            if retry_count > max_retries:
                result = {"error": last_error, "context": context, "page": page, "retries": retry_count}
                break
            
            # Pausa antes del siguiente reintento (con backoff exponencial)
            retry_delay = retry_delays[min(retry_count-1, len(retry_delays)-1)]
            logger.info(f"Reintentando {url} en {retry_delay} segundos... (intento {retry_count+1}/{max_retries+1})")
            time.sleep(retry_delay)
            
        # Pausa aleatoria para no sobrecargar servidores (después de éxito o agotamiento de reintentos)
        time.sleep(random.uniform(0.5, 1.5))

        return url, result


    def scrape_urls_parallel(self, url_infos, output_json_path):
        """
        Realiza scraping de una lista de URLs (diccionarios) en paralelo.
        Guarda los resultados en un archivo JSON.
        """
        scraped_data = {}
        total_urls = len(url_infos)
        processed_count = 0
        start_time = time.time()

        logger.info(f"Iniciando scraping paralelo de {total_urls} URLs...")

        # Usar context manager para asegurar limpieza del driver Selenium si se usa
        try:
            with ThreadPoolExecutor(max_workers=self.config.get("max_workers", 5)) as executor:
                # Crear futuros
                future_to_url_info = {executor.submit(self.scrape_single_url, url_info): url_info for url_info in url_infos}

                for future in as_completed(future_to_url_info):
                    url_info_orig = future_to_url_info[future]
                    url_orig = url_info_orig.get("URL")
                    processed_count += 1
                    try:
                        url_processed, content = future.result()
                        scraped_data[url_orig] = content # Usar URL original como clave
                        if "error" in content:
                             logger.warning(f"Error procesando {url_orig}: {content['error']}")
                        else:
                             logger.debug(f"Procesada {url_orig} exitosamente.")

                    except Exception as e:
                        logger.error(f"Error procesando futuro para {url_orig}: {e}", exc_info=True)
                        scraped_data[url_orig] = {"error": f"Future processing failed: {str(e)}", "context": url_info_orig.get("Context"), "page": url_info_orig.get("Page")}

                    if processed_count % 20 == 0 or processed_count == total_urls: # Log/Save cada 20 o al final
                         elapsed_time = time.time() - start_time
                         logger.info(f"Progreso: {processed_count}/{total_urls} URLs procesadas en {elapsed_time:.2f} seg.")
                         # Guardar progreso intermedio (opcional, sobrescribe)
                         # save_to_json(scraped_data, output_json_path)

        finally:
            self.close_selenium_driver() # Asegura cerrar el driver

        # Guardado final
        save_to_json(scraped_data, output_json_path)
        end_time = time.time()
        logger.info(f"Scraping completado para {processed_count}/{total_urls} URLs en {end_time - start_time:.2f} segundos.")
        logger.info(f"Resultados guardados en: {output_json_path}")

        return scraped_data
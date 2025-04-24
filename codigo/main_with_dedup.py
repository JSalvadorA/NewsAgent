# codigo/main_with_dedup.py
# Versión de main.py que utiliza FacebookProcessorWithDedup para reducir PDFs duplicados
import os
import sys
import logging
from datetime import datetime
import time
import json
import glob
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import concurrent.futures

# Asegurarse de que el directorio 'lib' esté en el path para imports
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Crear directorio de logs si no existe ANTES de configurar logging
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, 'scraper_dedup.log')

# Configuración de logging global (ANTES de importar módulos que lo usen)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("main_with_dedup")

# Silenciar logs verbosos (después de la configuración básica)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)
logging.getLogger("webdriver_manager").setLevel(logging.WARNING)

# Importar módulos de la biblioteca 'lib' (DESPUÉS de configurar logging y sys.path)
from lib.config_unified import get_config
from lib.file_manager import save_to_csv, save_to_json, save_stats
from lib.pdf_processor import extract_links_from_pdf
from lib.url_manager import classify_urls
from lib.history_tracker import HistoryTracker
from lib.html_scraper import HTMLScraper
from process_pending_images import EnhancedImageProcessor
from lib.text_extractor import extract_and_save_pdf_text
from lib.facebook_processor_dedup_improved import FacebookProcessorWithDedup
from lib.history_tracker import HistoryTracker
from lib.config_manager import get_paths

# -------------------------------
# Función principal de orquestación
# -------------------------------
def run_pipeline(custom_date_str=None):
    """
    Ejecuta el pipeline completo de extracción y procesamiento con deduplicación de Facebook.
    """
    start_time_pipeline = time.time()
    today_date_for_filename = custom_date_str if custom_date_str else datetime.today().strftime('%d%m%Y')
    logger.info("==================================================")
    logger.info("INICIANDO PIPELINE DE SCRAPING (CON DEDUPLICACIÓN FACEBOOK)")
    logger.info(f"Usando fecha: {today_date_for_filename}")
    logger.info("==================================================")

    # --- 1. Cargar Configuración y Rutas ---
    try:
        config_manager = get_config(project_root)
        config = config_manager.config
        
        # Importar get_paths directamente ya que es una función independiente
        paths = get_paths(config, custom_date=today_date_for_filename)
        
        # Añadir configuración de deduplicación si no existe
        if "facebook_dedup" not in config:
            config["facebook_dedup"] = {
                "enable_deduplication": True,
                "similarity_threshold": 0.85,
                "min_content_length": 100,
                "normalize_urls": True,
                "store_mapping": True
            }
        
        logger.info("Configuración y rutas cargadas.")
        logger.debug(f"PDF de entrada: {paths['pdf_input']}")
        logger.debug(f"Directorio de caché: {paths['cache_dir']}")
        logger.debug(f"Archivo de historial: {paths['history_file']}")
    except Exception as e:
        logger.critical(f"Error fatal cargando configuración o rutas: {e}", exc_info=True)
        return

    # --- 2. Inicializar Componentes ---
    try:
        # Pasar config completo, ya que incluye 'paths' y otras configs necesarias
        full_config_for_components = {'paths': paths, **config}
        history_tracker = HistoryTracker(paths['history_file'])
        html_scraper = HTMLScraper(full_config_for_components)
        image_processor = EnhancedImageProcessor(config)
        # Usar procesador de Facebook con deduplicación
        facebook_processor = FacebookProcessorWithDedup(full_config_for_components)
        logger.info("Componentes inicializados (History, Scraper, ImageProcessor, FacebookProcessor).")
    except Exception as e:
         logger.critical(f"Error fatal inicializando componentes: {e}", exc_info=True)
         if 'html_scraper' in locals() and hasattr(html_scraper, 'close_selenium_driver'):
             html_scraper.close_selenium_driver()
         return

    processed_data = {
        "html": {},
        "images_api": [],
        "facebook": {},
        "stats": {}
    }
    all_links = []
    downloaded_image_metadata = {}  # Inicializar como diccionario vacío
    img_down_duration = 0
    html_scrap_duration = 0
    img_api_duration = 0
    facebook_duration = 0

    try:
        # --- 3. Extracción de Enlaces y Texto del PDF ---
        logger.info("--- Paso 1: Extrayendo enlaces del PDF ---")
        pdf_start_time = time.time()
        all_links = extract_links_from_pdf(paths['pdf_input'])
        pdf_duration = time.time() - pdf_start_time
        if not all_links:
            logger.warning(f"No se encontraron enlaces en {paths['pdf_input']}. Terminando proceso para esta fecha.")
            # Guardar estadísticas vacías si no hay enlaces? Opcional.
            stats = {
                 "run_timestamp": datetime.now().isoformat(),
                 "date_processed": today_date_for_filename,
                 "total_urls_in_pdf": 0,
                 "error": "No links found in PDF"
            }
            save_stats(stats, paths['processing_stats_json'])
            return
        logger.info(f"PDF procesado en {pdf_duration:.2f} seg. Enlaces encontrados: {len(all_links)}")
        save_to_csv(all_links, paths['links_extracted_csv'])
        
        # --- 3.1 Extracción de Texto del PDF por secciones ---
        logger.info("--- Paso 1.1: Extrayendo texto del PDF por secciones ---")
        pdf_text_start_time = time.time()
        pdf_text_success, pdf_text_file = extract_and_save_pdf_text(paths['pdf_input'], today_date_for_filename)
        pdf_text_duration = time.time() - pdf_text_start_time
        if pdf_text_success:
            logger.info(f"Texto del PDF extraído en {pdf_text_duration:.2f} seg. Guardado en: {pdf_text_file}")
        else:
            logger.warning(f"No se pudo extraer texto del PDF {paths['pdf_input']}")

        # --- 4. Filtrar URLs ya procesadas ---
        logger.info("--- Paso 2: Filtrando URLs por historial ---")
        links_to_process = history_tracker.get_unprocessed_links(all_links)
        logger.info(f"URLs nuevas para procesar: {len(links_to_process)} (de {len(all_links)} total)")
        if not links_to_process:
             logger.info("No hay URLs nuevas para procesar en esta ejecución.")
             # Guardar estadísticas indicando que no hubo URLs nuevas
             stats = {
                 "run_timestamp": datetime.now().isoformat(),
                 "date_processed": today_date_for_filename,
                 "total_urls_in_pdf": len(all_links),
                 "new_urls_processed_count": 0,
                 "history_total_urls": history_tracker.get_history_count(),
                 "info": "No new URLs to process in this run."
             }
             save_stats(stats, paths['processing_stats_json'])
             return

        # --- 5. Clasificar URLs ---
        logger.info("--- Paso 3: Clasificando URLs ---")
        categories = classify_urls(links_to_process)
        # Guardar listas de enlaces por categoría (útil para debug)
        if categories.get('images'):
             save_to_json(categories['images'], paths['image_links_json'].replace('.json', '_unprocessed.json'))
        if categories.get('social'):
             save_to_json(categories['social'], paths['social_links_json'].replace('.json', '_unprocessed.json'))
        if categories.get('other'):
             save_to_json(categories['other'], paths['links_extracted_csv'].replace('.csv', '_other_unprocessed.json'))

        # --- 6. Procesar Imágenes (Descarga) ---
        logger.info("--- Paso 4: Procesando Imágenes (Descarga) ---")
        image_links = categories.get('images', [])
        if image_links:
            img_down_start = time.time()
            downloaded_image_metadata = image_processor.download_images_parallel(image_links, today_date_for_filename)
            img_down_duration = time.time() - img_down_start
            logger.info(f"Descarga de imágenes completada en {img_down_duration:.2f} seg.")
            # *** CORRECCIÓN AQUÍ: Convertir dict_keys a list ***
            if downloaded_image_metadata:
                 history_tracker.add_processed_urls(list(downloaded_image_metadata.keys()))
        else:
            logger.info("No hay nuevas URLs de imágenes para descargar.")

        # --- 7. Procesar HTML (Scraping) ---
        logger.info("--- Paso 5: Procesando HTML (Scraping) ---")
        html_urls = categories.get('html', [])
        if html_urls:
            html_scrap_start = time.time()
            processed_data["html"] = html_scraper.scrape_urls_parallel(html_urls, paths['scraped_texts_json'])
            html_scrap_duration = time.time() - html_scrap_start
            logger.info(f"Scraping HTML completado en {html_scrap_duration:.2f} seg.")
            # *** CORRECCIÓN AQUÍ: Convertir dict_keys a list ***
            if processed_data["html"]:
                 history_tracker.add_processed_urls(list(processed_data["html"].keys()))
        else:
            logger.info("No hay nuevas URLs HTML para scrapear.")
        
        # --- 8. Procesar Imágenes Descargadas (API) ---
        logger.info("--- Paso 6: Procesando Imágenes Descargadas (API) ---")
        
        # Verificar si hay imágenes para procesar, ya sea nuevas o existentes
        if downloaded_image_metadata:
            # Verificar primero si hay alguna imagen descargada correctamente
            valid_images = [meta for meta in downloaded_image_metadata.values() 
                           if "error" not in meta and meta.get("filepath") and os.path.exists(meta.get("filepath"))]
            
            if valid_images:
                # Si hay nuevas imágenes descargadas válidas, procesarlas
                logger.info(f"Procesando {len(valid_images)} imágenes recién descargadas")
                
                # Crear un directorio específico para esta fecha si no existe
                date_image_dir = paths.get('image_download_dir')
                if date_image_dir and not os.path.exists(date_image_dir):
                    os.makedirs(date_image_dir, exist_ok=True)
                    logger.info(f"Creado directorio para imágenes: {date_image_dir}")
                
                # Usar process_pending_images que ya maneja todo internamente
                img_api_start = time.time()
                image_processor.process_pending_images([today_date_for_filename])
                img_api_duration = time.time() - img_api_start
                
                # Cargar resultados para estadísticas
                try:
                    image_api_results_json = paths.get('image_api_results_json')
                    if os.path.exists(image_api_results_json):
                        with open(image_api_results_json, 'r', encoding='utf-8') as f:
                            processed_data["images_api"] = json.load(f)
                        logger.info(f"Resultados de imágenes cargados de {image_api_results_json}: {len(processed_data['images_api'])} imágenes")
                except Exception as e:
                    logger.warning(f"No se pudieron cargar resultados de imágenes: {e}")
                    
                logger.info(f"Procesamiento API de imágenes completado en {img_api_duration:.2f} seg.")
            else:
                logger.warning("Ninguna imagen se descargó correctamente, no hay nada que procesar.")
        else:
            # No hay imágenes nuevas, verificar si hay existentes sin procesar
            logger.info("No hay imágenes nuevas descargadas, verificando existentes...")
            
            # El procesador mejorado buscará imágenes en el directorio correcto y las procesará
            img_api_start = time.time()
            image_processor.process_pending_images([today_date_for_filename])
            img_api_duration = time.time() - img_api_start
            
            # Cargar resultados si existen
            try:
                image_api_results_json = paths.get('image_api_results_json')
                if os.path.exists(image_api_results_json):
                    with open(image_api_results_json, 'r', encoding='utf-8') as f:
                        processed_data["images_api"] = json.load(f)
                    if processed_data["images_api"]:
                        logger.info(f"Cargados {len(processed_data['images_api'])} resultados de imágenes existentes")
            except Exception as e:
                logger.warning(f"No se pudieron cargar resultados de imágenes: {e}")
            
            logger.info(f"Verificación y procesamiento de imágenes existentes completado en {img_api_duration:.2f} seg.")
        
        # --- 9. Procesar URLs de Facebook ---
        logger.info("--- Paso 7: Procesando URLs de Facebook (CON DEDUPLICACIÓN) ---")
        
        # Búsqueda de URLs de Facebook en archivos sociales
        facebook_links = []
        
        # 1. URLs de la clasificación actual
        social_links = categories.get('social', [])
        for link in social_links:
            if "facebook.com" in link.get("URL", "").lower() or "fb.com" in link.get("URL", "").lower():
                facebook_links.append(link)
        
        # Limitar el número de URLs de Facebook para evitar congelamientos
        max_facebook_urls = 5  # Procesar máximo 5 URLs de Facebook a la vez
        if len(facebook_links) > max_facebook_urls:
            logger.warning(f"Limitando procesamiento a {max_facebook_urls} URLs de Facebook para evitar congelamientos")
            facebook_links = facebook_links[:max_facebook_urls]
        
        if facebook_links:
            logger.info(f"Encontradas {len(facebook_links)} URLs de Facebook para procesar")
            facebook_start = time.time()
            
            # Crear directorio de fecha en 'base' si no existe
            base_date_dir = os.path.join(project_root, 'base', today_date_for_filename)
            try:
                if not os.path.exists(base_date_dir):
                    os.makedirs(base_date_dir, exist_ok=True)
                    logger.info(f"Creado directorio para PDFs: {base_date_dir}")
            except Exception as e:
                logger.error(f"Error creando directorio para PDFs: {e}")
            
            # Extraer solo las URLs de los diccionarios
            fb_urls = [link["URL"] for link in facebook_links]
            
            # Verificar conexión a internet antes de procesar Facebook
            internet_available = check_internet_connection()
            if not internet_available:
                logger.error("No hay conexión a internet disponible. Saltando procesamiento de Facebook.")
                processed_data["facebook"] = {}
                facebook_duration = 0
                return
            
            # Establecer un timeout para evitar congelamientos
            try:
                # CAMBIO AQUÍ: Usamos el procesador con deduplicación con timeout más corto
                with ThreadPoolExecutor(max_workers=2) as executor:
                    future = executor.submit(facebook_processor.process_facebook_urls_parallel, fb_urls, today_date_for_filename)
                    try:
                        # Timeout más corto: 2 minutos por URL, máximo 10 minutos total
                        timeout_seconds = min(600, 120 * len(fb_urls))
                        logger.info(f"Procesando URLs de Facebook con timeout de {timeout_seconds} segundos")
                        processed_data["facebook"] = future.result(timeout=timeout_seconds)
                    except concurrent.futures.TimeoutError:
                        logger.error(f"Timeout después de {timeout_seconds} segundos procesando URLs de Facebook")
                        processed_data["facebook"] = {}
            except Exception as e:
                logger.error(f"Error procesando URLs de Facebook: {e}")
                processed_data["facebook"] = {}
                
            facebook_duration = time.time() - facebook_start
            
            # Mostrar estadísticas de deduplicación
            total_urls = len(fb_urls)
            unique_urls = sum(1 for result in processed_data["facebook"].values() if not result.get('is_duplicate') and not result.get('is_content_duplicate', False))
            duplicate_urls = total_urls - unique_urls
            
            logger.info(f"Procesamiento de URLs de Facebook completado en {facebook_duration:.2f} seg.")
            logger.info(f"URLs de Facebook: Total={total_urls}, Únicas={unique_urls}, Duplicadas={duplicate_urls}")
            
            # Añadir URLs procesadas al historial (solo las procesadas realmente)
            if processed_data["facebook"]:
                # Solo añadir URLs que no son duplicados 
                facebook_processed_urls = [url for url, result in processed_data["facebook"].items() 
                                          if result.get('success') and not result.get('is_duplicate')]
                if facebook_processed_urls:
                    history_tracker.add_processed_urls(facebook_processed_urls)
        else:
            logger.info("No hay URLs de Facebook para procesar.")

        # --- 10. Extraer Texto de PDFs de Facebook ---
        logger.info("--- Paso 9: Extrayendo Texto de PDFs de Facebook ---")
        facebook_pdf_texts = {}
        
        if processed_data["facebook"]:
            pdf_text_start = time.time()
            facebook_pdf_texts = facebook_processor.extract_text_from_all_pdfs(processed_data["facebook"])
            pdf_text_duration = time.time() - pdf_text_start
            logger.info(f"Extracción de texto de PDFs de Facebook completada en {pdf_text_duration:.2f} seg.")
            logger.info(f"Texto extraído de {len(facebook_pdf_texts)} PDFs de Facebook")
        else:
            logger.info("No hay PDFs de Facebook para extraer texto.")
        
        # Guardar los textos extraídos en un archivo separado
        if facebook_pdf_texts:
            pdf_texts_path = os.path.join(project_root, 'output', f"facebook_texts_dedup_{today_date_for_filename}.json")
            try:
                save_to_json(facebook_pdf_texts, pdf_texts_path)
                logger.info(f"Textos de PDFs de Facebook guardados en: {pdf_texts_path}")
            except Exception as e:
                logger.error(f"Error al guardar textos de PDFs de Facebook: {e}")
        
        # --- 11. Generar Estadísticas y Consolidar ---
        logger.info("--- Paso 10: Generando Estadísticas y Consolidando ---")
        stats_start_time = time.time()
        # Cálculos de estadísticas (sin cambios aquí, parecen correctos)
        total_html_processed = len(processed_data["html"])
        successful_html = sum(1 for data in processed_data["html"].values() if "error" not in data)
        relevant_html_count = sum(1 for data in processed_data["html"].values() if "error" not in data and data.get("relevance", 0) >= 0.3)
        total_relevance_score = sum(data.get("relevance", 0) for data in processed_data["html"].values() if "error" not in data)
        total_images_attempted = len(categories.get('images', []))
        successful_downloads = sum(1 for meta in downloaded_image_metadata.values() if "error" not in meta and meta.get("filepath"))
        successful_api_calls = sum(1 for res in processed_data["images_api"] if not res.get("error"))
        
        # Estadísticas Facebook
        total_facebook_urls = len(facebook_links) if 'facebook_links' in locals() else 0
        successful_facebook = sum(1 for result in processed_data["facebook"].values() if result.get("success", False)) if processed_data["facebook"] else 0
        facebook_text_count = len(facebook_pdf_texts) if 'facebook_pdf_texts' in locals() else 0
        
        # Estadísticas adicionales de deduplicación de Facebook
        facebook_duplicates = sum(1 for result in processed_data["facebook"].values() 
                                if result.get('is_duplicate') or result.get('is_content_duplicate', False)) if processed_data["facebook"] else 0
        facebook_unique = total_facebook_urls - facebook_duplicates if total_facebook_urls > 0 else 0

        stats = {
            "run_timestamp": datetime.now().isoformat(),
            "date_processed": today_date_for_filename,
            "total_urls_in_pdf": len(all_links),
            "new_urls_processed_count": len(links_to_process),
            "history_total_urls": history_tracker.get_history_count(),
            "categories": {cat: len(items) for cat, items in categories.items() if items}, # Solo mostrar categorías con items
            "html_processing": {
                "attempted": len(html_urls),
                "processed": total_html_processed, # Cuántos futuros retornaron
                "successful": successful_html, # Cuántos no tuvieron error
                "relevant (>=0.3)": relevant_html_count,
                "average_relevance": (total_relevance_score / successful_html) if successful_html > 0 else 0,
            },
             "image_processing": {
                 "attempted_download": total_images_attempted,
                 "successful_download": successful_downloads,
                 "attempted_api": successful_downloads,
                 "successful_api": successful_api_calls,
             },
             "facebook_processing": {
                 "attempted": total_facebook_urls,
                 "successful": successful_facebook,
                 "unique": facebook_unique,
                 "duplicates": facebook_duplicates,
                 "duplicate_percentage": round((facebook_duplicates / total_facebook_urls) * 100, 2) if total_facebook_urls > 0 else 0,
                 "extracted_texts": facebook_text_count,
             },
            "timings_seconds": {
                 "pdf_extraction": round(pdf_duration, 2),
                 "pdf_text_extraction": round(pdf_text_duration if 'pdf_text_duration' in locals() else 0, 2), 
                 "image_download": round(img_down_duration, 2),
                 "html_scraping": round(html_scrap_duration, 2),
                 "image_api": round(img_api_duration, 2),
                 "facebook_processing": round(facebook_duration, 2),
                 "facebook_text_extraction": round(pdf_text_duration if 'pdf_text_duration' in locals() else 0, 2),
                 "stats_consolidation": 0 # Se calculará al final de este bloque
            }
        }
        stats_duration = time.time() - stats_start_time
        stats["timings_seconds"]["stats_consolidation"] = round(stats_duration, 2)

        processed_data["stats"] = stats
        # Cambiar nombre del archivo de stats para diferenciarlo del original
        dedup_stats_path = paths['processing_stats_json'].replace('.json', '_dedup.json')
        save_stats(stats, dedup_stats_path)
        logger.info(f"Estadísticas generadas y guardadas en {stats_duration:.2f} seg.")

        # --- 10. Verificar contenido HTML y de imágenes existente para incluir en consolidado ---
        logger.info("--- Paso 9: Verificando contenido HTML e imágenes existentes ---")
        
        # Si processed_data["html"] está vacío, intentar cargar desde archivo si existe
        if not processed_data["html"] and os.path.exists(paths['scraped_texts_json']):
            try:
                with open(paths['scraped_texts_json'], 'r', encoding='utf-8') as f:
                    html_data = json.load(f)
                    if html_data:
                        logger.info(f"Cargando contenido HTML de archivo existente: {paths['scraped_texts_json']}")
                        processed_data["html"] = html_data
            except Exception as e:
                logger.warning(f"Error cargando datos HTML desde archivo: {e}")
        
        # Si processed_data["images_api"] está vacío, intentar cargar desde archivo si existe
        # CAMBIO: Usar la ruta estandarizada para el archivo de resultados
        image_api_results_json = paths.get('image_api_results_json')
        if not processed_data["images_api"] and os.path.exists(image_api_results_json):
            try:
                with open(image_api_results_json, 'r', encoding='utf-8') as f:
                    image_data = json.load(f)
                    if image_data:
                        logger.info(f"Cargando contenido de imágenes de archivo existente: {image_api_results_json}")
                        processed_data["images_api"] = image_data
            except Exception as e:
                logger.warning(f"Error cargando datos de imágenes desde archivo: {e}")
        
        # --- 11. Consolidación Final (Opcional) ---
        consolidated_output_path = os.path.join(project_root, 'output', f'consolidated_dedup_{today_date_for_filename}.json')
        try:
             # Intentar cargar el texto extraído del PDF si existe
             pdf_text_json_path = os.path.join(project_root, 'input', 'Out', f'scraped_pdf_{today_date_for_filename}', f'pdf_text_{today_date_for_filename}.json')
             pdf_paragraphs = {}
             if os.path.exists(pdf_text_json_path):
                 try:
                     with open(pdf_text_json_path, 'r', encoding='utf-8') as f:
                         pdf_paragraphs = json.load(f)
                     logger.info(f"Texto del PDF cargado para consolidación desde: {pdf_text_json_path}")
                 except Exception as e:
                     logger.warning(f"Error cargando texto del PDF para consolidación: {e}")
             
             consolidation_data = {
                 "metadata": {
                     "source_pdf": os.path.basename(paths['pdf_input']),
                     "processing_date": stats["run_timestamp"],
                     "stats_summary": stats
                 },
                 "extracted_content": {
                     "pdf_paragraphs": pdf_paragraphs,
                     "html_pages": processed_data["html"],
                     "image_texts": processed_data["images_api"],
                     #"facebook_results": processed_data["facebook"],
                     "facebook_texts": facebook_pdf_texts
                 }
             }
             # Asegurar que el directorio 'output' exista
             os.makedirs(os.path.dirname(consolidated_output_path), exist_ok=True)
             save_to_json(consolidation_data, consolidated_output_path, indent=2)
             logger.info(f"Resultados consolidados guardados en: {consolidated_output_path}")
        except Exception as e:
            logger.error(f"Error al guardar resultados consolidados: {e}", exc_info=True)


    except KeyboardInterrupt:
         logger.warning("Proceso interrumpido por el usuario (Ctrl+C).")
         if 'history_tracker' in locals():
             urls_processed_so_far = set()
             if 'downloaded_image_metadata' in locals():
                 urls_processed_so_far.update(downloaded_image_metadata.keys())
             if 'processed_data' in locals() and processed_data.get('html'):
                  urls_processed_so_far.update(processed_data['html'].keys())
             if 'processed_data' in locals() and processed_data.get('facebook'):
                  urls_processed_so_far.update(processed_data['facebook'].keys())
             if urls_processed_so_far:
                  logger.info("Actualizando historial con URLs procesadas hasta la interrupción...")
                  history_tracker.add_processed_urls(list(urls_processed_so_far)) # Convertir a lista

         # Guardar progreso parcial si es posible
         if 'processed_data' in locals() and processed_data.get("html"):
             logger.info("Guardando progreso HTML parcial...")
             partial_path = paths['scraped_texts_json'].replace('.json', '_interrupted.json')
             save_to_json(processed_data["html"], partial_path)
         if 'processed_data' in locals() and processed_data.get("images_api"):
             logger.info("Guardando progreso API imágenes parcial...")
             partial_path_api = paths.get("image_api_results_json", "").replace('.json', '_interrupted.json')
             if partial_path_api:
                 save_to_json(processed_data["images_api"], partial_path_api)
         
         if 'processed_data' in locals() and processed_data.get("facebook"):
             logger.info("Guardando progreso Facebook parcial...")
             partial_path_fb = os.path.join(project_root, 'output', f"facebook_results_dedup_{today_date_for_filename}_interrupted.json")
             save_to_json(processed_data["facebook"], partial_path_fb)


    except Exception as e:
        logger.critical(f"Error inesperado en el pipeline principal: {e}", exc_info=True)

    finally:
        # --- Limpieza ---
        logger.info("--- Limpieza Final ---")
        if 'html_scraper' in locals() and hasattr(html_scraper, 'close_selenium_driver'):
            html_scraper.close_selenium_driver()

        end_time_pipeline = time.time()
        total_duration = end_time_pipeline - start_time_pipeline
        logger.info("==================================================")
        logger.info(f"PIPELINE FINALIZADO en {total_duration:.2f} segundos.")
        logger.info("==================================================")


# -------------------------------
# Punto de entrada
# -------------------------------
if __name__ == "__main__":
    date_arg = None
    if len(sys.argv) > 1:
        date_arg = sys.argv[1]
        try:
            datetime.strptime(date_arg, '%d%m%Y')
            logger.info(f"Se usará la fecha proporcionada: {date_arg}")
        except ValueError:
            logger.error(f"Formato de fecha inválido: '{date_arg}'. Debe ser ddmmyyyy. Usando fecha actual.")
            date_arg = None

    run_pipeline(custom_date_str=date_arg)

# -------------------------------
# Funciones auxiliares
# -------------------------------
def save_to_json(data, output_path, indent=4):
    """Guarda datos en un archivo JSON"""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
    except Exception as e:
        logger.error(f"Error guardando JSON en {output_path}: {e}")

def save_stats(stats_dict, output_path):
    """Guarda estadísticas en un archivo JSON"""
    save_to_json(stats_dict, output_path)
    logger.info(f"Estadísticas guardadas en {output_path}")

def check_internet_connection():
    """
    Verifica si hay conexión a internet disponible usando un ping a Google.
    
    Returns:
        bool: True si hay conexión, False si no hay
    """
    import socket
    try:
        # Intenta conectar a Google DNS para verificar conexión
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        try:
            # Segundo intento a Cloudflare
            socket.create_connection(("1.1.1.1", 53), timeout=3)
            return True
        except OSError:
            return False
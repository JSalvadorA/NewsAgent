# codigo/main.py
import os
import sys
import logging
from datetime import datetime
import time
import json

# Asegurarse de que el directorio 'lib' esté en el path para imports
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
project_root = os.path.abspath(os.path.join(current_dir, '..')) # Mover definición de project_root aquí
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Crear directorio de logs si no existe ANTES de configurar logging
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, 'scraper.log')

# Configuración de logging global (ANTES de importar módulos que lo usen)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("main_orchestrator")

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
from lib.image_processor import ImageProcessor
from lib.facebook_processor import FacebookProcessor
from lib.text_extractor import extract_and_save_pdf_text

# -------------------------------
# Función principal de orquestación
# -------------------------------
def run_pipeline(custom_date_str=None):
    """
    Ejecuta el pipeline completo de extracción y procesamiento.
    """
    start_time_pipeline = time.time()
    today_date_for_filename = custom_date_str if custom_date_str else datetime.today().strftime('%d%m%Y')
    logger.info("==================================================")
    logger.info("INICIANDO PIPELINE DE SCRAPING")
    logger.info(f"Usando fecha: {today_date_for_filename}")
    logger.info("==================================================")

    # --- 1. Cargar Configuración y Rutas ---
    try:
        config_manager = get_config(project_root)
        paths = config_manager.generate_paths(custom_date=today_date_for_filename) # Pasar la fecha correcta
        config = config_manager.config
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
        image_processor = ImageProcessor(full_config_for_components)
        facebook_processor = FacebookProcessor(full_config_for_components)
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
    downloaded_image_metadata = {} # Definir fuera del try para el finally
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
        
        # Comprobar si hay imágenes descargadas, ya sea de la ejecución actual o existentes
        if downloaded_image_metadata:
            # Imágenes descargadas en esta ejecución
            img_api_start = time.time()
            processed_data["images_api"] = image_processor.process_downloaded_images_with_api(downloaded_image_metadata)
            img_api_duration = time.time() - img_api_start
            logger.info(f"Procesamiento API de imágenes completado en {img_api_duration:.2f} seg.")
        else:
            # Verificar si hay imágenes existentes en la carpeta de descargas
            images_dir = paths.get('image_download_dir')
            if images_dir and os.path.exists(images_dir):
                # Listar archivos de imagen en la carpeta de fecha (puede haber subcarpetas)
                image_files = []
                for root, dirs, files in os.walk(images_dir):
                    for file in files:
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            image_files.append(os.path.join(root, file))
                
                # Si hay un archivo de texto de imágenes pero está vacío o no existe
                output_json_path = os.path.join(images_dir, "texto_imagenes_api.json")
                process_images = bool(image_files) and (not os.path.exists(output_json_path) or os.path.getsize(output_json_path) == 0)
                
                if process_images:
                    logger.info(f"Encontradas {len(image_files)} imágenes existentes sin procesar en {images_dir}")
                    # Crear metadata similar a la que genera image_processor.download_images_parallel
                    existing_metadata = {}
                    for idx, img_path in enumerate(image_files, 1):
                        img_file = os.path.basename(img_path)
                        img_url = f"file://{img_path}"  # URL ficticia para identificación
                        existing_metadata[img_url] = {
                            "filepath": img_path,
                            "filename": img_file,
                            "content_type": "image/jpeg",  # Asumimos JPEG por defecto
                            "downloaded_from_cache": True
                        }
                    
                    # Procesar con la API
                    img_api_start = time.time()
                    processed_data["images_api"] = image_processor.process_downloaded_images_with_api(existing_metadata)
                    img_api_duration = time.time() - img_api_start
                    logger.info(f"Procesamiento API de imágenes existentes completado en {img_api_duration:.2f} seg.")
                else:
                    logger.info("No hubo imágenes descargadas o ya están procesadas.")
            else:
                logger.info("No hubo imágenes descargadas para procesar con la API.")
        
        # --- 9. Procesar URLs de Facebook ---
        logger.info("--- Paso 7: Procesando URLs de Facebook ---")
        
        # Búsqueda de URLs de Facebook en archivos sociales
        facebook_links = []
        
        # 1. URLs de la clasificación actual
        social_links = categories.get('social', [])
        for link in social_links:
            if "facebook.com" in link.get("URL", "").lower() or "fb.com" in link.get("URL", "").lower():
                facebook_links.append(link)
        
        # 2. Adicionalmente buscar en archivos sociales guardados (_unprocessed.json)
        social_dir = os.path.join(project_root, 'input', 'Social')
        if os.path.exists(social_dir):
            try:
                # Encontrar todos los archivos JSON _unprocessed
                social_files = [f for f in os.listdir(social_dir) if f.endswith('_unprocessed.json')]
                
                for social_file in social_files:
                    # Saltar el archivo actual ya procesado
                    if social_file == f"social_links_{today_date_for_filename}_unprocessed.json":
                        continue
                        
                    try:
                        social_file_path = os.path.join(social_dir, social_file)
                        logger.info(f"Leyendo archivo social adicional: {social_file}")
                        
                        with open(social_file_path, 'r', encoding='utf-8') as f:
                            file_links = json.load(f)
                        
                        for link in file_links:
                            url = link.get("URL", "")
                            if ("facebook.com" in url.lower() or "fb.com" in url.lower()) and \
                               not any(l.get("URL") == url for l in facebook_links):
                                # Verificar si ya ha sido procesada esta URL
                                if not history_tracker.is_url_processed(url):
                                    facebook_links.append(link)
                                    logger.info(f"Añadida URL de Facebook de archivo {social_file}: {url}")
                    except Exception as e:
                        logger.warning(f"Error procesando archivo social {social_file}: {e}")
            except Exception as e:
                logger.warning(f"Error al buscar archivos sociales: {e}")
        
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
            processed_data["facebook"] = facebook_processor.process_facebook_urls_parallel(fb_urls, today_date_for_filename)
            facebook_duration = time.time() - facebook_start
            logger.info(f"Procesamiento de URLs de Facebook completado en {facebook_duration:.2f} seg.")
            
            # Añadir URLs procesadas al historial
            if processed_data["facebook"]:
                facebook_processed_urls = list(processed_data["facebook"].keys())
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
            pdf_texts_path = os.path.join(project_root, 'output', f"facebook_texts_{today_date_for_filename}.json")
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
        save_stats(stats, paths['processing_stats_json'])
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
        image_api_results_json = os.path.join(paths.get('image_download_dir', ''), "texto_imagenes_api.json")
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
        consolidated_output_path = os.path.join(project_root, 'output', f'consolidated_{today_date_for_filename}.json')
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
                     "facebook_results": processed_data["facebook"],
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
             partial_path_fb = os.path.join(project_root, 'output', f"facebook_results_{today_date_for_filename}_interrupted.json")
             save_to_json(processed_data["facebook"], partial_path_fb)


    except Exception as e:
        logger.critical(f"Error inesperado en el pipeline principal: {e}", exc_info=True)

    finally:
        # --- Limpieza ---
        logger.info("--- Limpieza Final ---")
        if 'html_scraper' in locals() and hasattr(html_scraper, 'close_selenium_driver'):
            html_scraper.close_selenium_driver()
        # No necesitamos limpiar facebook_processor porque los drivers se cierran en cada procesamiento

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
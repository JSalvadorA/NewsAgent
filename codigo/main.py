# codigo/main.py
import os
import sys
import logging
from datetime import datetime
import time
import json
import requests
import subprocess

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
from lib.config_manager import load_config, get_paths
from lib.file_manager import save_to_csv, save_to_json, save_stats
from lib.pdf_processor import extract_links_from_pdf
from lib.url_manager import classify_urls
from lib.history_tracker import HistoryTracker
from lib.html_scraper import HTMLScraper
from lib.image_processor import ImageProcessor
from lib.audio_processor import AudioProcessor
from lib.facebook_processor import FacebookProcessor
from lib.text_extractor import extract_and_save_pdf_text, extract_text_with_ocr
from lib.text_similarity import consolidate_pdf_texts, get_unprocessed_urls

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
        config = load_config(project_root)
        paths = get_paths(config, custom_date=today_date_for_filename) # Pasar la fecha correcta
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
        audio_processor = AudioProcessor(full_config_for_components)
        facebook_processor = FacebookProcessor(full_config_for_components)
        logger.info("Componentes inicializados (History, Scraper, ImageProcessor, AudioProcessor, FacebookProcessor).")
    except Exception as e:
        logger.critical(f"Error fatal inicializando componentes: {e}", exc_info=True)
        if 'html_scraper' in locals() and hasattr(html_scraper, 'close_selenium_driver'):
            html_scraper.close_selenium_driver()
        return

    processed_data = {
        "html": {},
        "images_api": [],
        "audio": {},
        "audio_transcriptions": [],
        "facebook": {},
        "stats": {}
    }
    all_links = []
    downloaded_image_metadata = {} # Definir fuera del try para el finally
    downloaded_audio_metadata = {} # Metadatos de audio descargados
    img_down_duration = 0
    html_scrap_duration = 0
    img_api_duration = 0
    audio_down_duration = 0
    audio_transcription_duration = 0
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
        links_to_process = history_tracker.get_unprocessed_links(all_links, today_date_for_filename)
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
        logger.info("El sistema utilizará procesamiento adaptativo con reintentos para imágenes.")
        
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
                
                # Nueva lógica para verificar si hay resultados válidos o solo errores de API
                process_images = True  # Por defecto procesar las imágenes
                
                if os.path.exists(output_json_path) and os.path.getsize(output_json_path) > 0:
                    try:
                        # Cargar el archivo existente para verificar si contiene solo errores
                        with open(output_json_path, 'r', encoding='utf-8') as f:
                            existing_results = json.load(f)
                        
                        # Verificar si hay resultados exitosos (sin errores API)
                        successful_results = [res for res in existing_results if not res.get('error') and res.get('extracted_text')]
                        
                        # Solo procesar si no hay resultados exitosos
                        if successful_results:
                            process_images = False
                            logger.info(f"Se encontraron {len(successful_results)} imágenes ya procesadas correctamente.")
                        else:
                            # Verificar si hay errores específicos de API key
                            api_key_errors = [res for res in existing_results if "API key not valid" in str(res.get('error', ''))]
                            if api_key_errors:
                                logger.warning(f"Se detectaron {len(api_key_errors)} imágenes con errores de clave API. Intentando reprocesar.")
                            else:
                                logger.warning(f"Se encontraron {len(existing_results)} imágenes con errores. Intentando reprocesar.")
                    except Exception as e:
                        logger.warning(f"Error analizando archivo de resultados de imágenes: {e}. Se reprocesarán las imágenes.")
                
                if process_images:
                    logger.info(f"Encontradas {len(image_files)} imágenes existentes para procesar en {images_dir}")
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
                    logger.info("No hay imágenes pendientes para procesar (ya procesadas correctamente).")
            else:
                logger.info("No se encontraron imágenes para procesar con la API.")
        
        # --- 9. Procesar archivos de audio ---
        logger.info("--- Paso 7: Procesando archivos de audio ---")
        
        # Obtener enlaces de audio de la clasificación
        audio_links = categories.get('audio', [])
        if audio_links:
            # Descargar archivos de audio
            audio_down_start = time.time()
            logger.info(f"Descargando {len(audio_links)} archivos de audio")
            downloaded_audio_metadata = audio_processor.download_audio_parallel(audio_links, today_date_for_filename)
            audio_down_duration = time.time() - audio_down_start
            logger.info(f"Descarga de archivos de audio completada en {audio_down_duration:.2f} seg.")
            
            # Registrar URLs procesadas
            if downloaded_audio_metadata:
                history_tracker.add_processed_urls(list(downloaded_audio_metadata.keys()))
                
            # Transcribir archivos de audio (máx 12 minutos)
            if downloaded_audio_metadata:
                audio_trans_start = time.time()
                logger.info(f"Transcribiendo archivos de audio...")
                processed_data["audio"] = downloaded_audio_metadata
                processed_data["audio_transcriptions"] = audio_processor.transcribe_audio(
                    downloaded_audio_metadata, 
                    today_date_for_filename, 
                    max_duration_minutes=12
                )
                audio_transcription_duration = time.time() - audio_trans_start
                logger.info(f"Transcripción de audio completada en {audio_transcription_duration:.2f} seg.")
        else:
            logger.info("No hay archivos de audio para procesar.")
        
        # --- 10. Procesar URLs de Facebook ---
        logger.info("--- Paso 8: Procesando URLs de Facebook ---")
        
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


        # --- 11. Extraer Texto de PDFs de Facebook ---
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
        
        # Verificar PDFs específicos (28032025-39.pdf y 28032025-40.pdf) por nombre
        if today_date_for_filename == "28032025":
            specific_pdfs = ["28032025-39.pdf", "28032025-40.pdf"]
            for specific_pdf in specific_pdfs:
                pdf_path = os.path.join(project_root, "base", today_date_for_filename, specific_pdf)
                if os.path.exists(pdf_path):
                    logger.info(f"Verificando extracción de texto para PDF específico: {specific_pdf}")
                    
                    # Intentar extraer texto con OCR utilizando la nueva API con verificación de dependencias
                    try:
                        # Crear ruta de salida para el texto OCR
                        output_dir = os.path.join(project_root, "output", "ocr", today_date_for_filename)
                        os.makedirs(output_dir, exist_ok=True)
                        output_path = os.path.join(output_dir, f"{os.path.splitext(specific_pdf)[0]}_ocr.json")
                        
                        # Ejecutar OCR con la nueva API
                        ocr_result = extract_text_with_ocr(
                            pdf_path=pdf_path,
                            output_path=output_path,
                            dpi=300,
                            language='spa',
                            use_gpu=False
                        )
                        
                        # Verificar si la extracción fue exitosa
                        if ocr_result["success"] and ocr_result["sections"]:
                            # Crear nombre descriptivo para este PDF específico
                            pdf_name = os.path.splitext(specific_pdf)[0]
                            
                            # Añadir a facebook_pdf_texts para que aparezca en el consolidado
                            if 'facebook_pdf_texts' not in locals():
                                facebook_pdf_texts = {}
                            
                            facebook_pdf_texts[pdf_name] = {
                                "metadata": {
                                    "source": specific_pdf,
                                    "processed_with": "OCR",
                                    "pages_processed": ocr_result["metadata"]["pages_processed"]
                                },
                                "content": ocr_result["sections"]
                            }
                            
                            logger.info(f"Texto extraído con OCR para {specific_pdf}: {len(ocr_result['sections'])} secciones")
                        else:
                            error_msg = ocr_result.get("error", "Razón desconocida")
                            logger.warning(f"No se pudo extraer texto con OCR para {specific_pdf}: {error_msg}")
                    except Exception as e:
                        logger.error(f"Error procesando PDF específico {specific_pdf}: {e}", exc_info=True)

        # Verificar PDFs generales para procesarlos con OCR si es necesario
        if os.path.exists(project_root):
            logger.info("Buscando PDFs en el directorio base para procesarlos con OCR si es necesario")
            # Crear directorio para resultados OCR si no existe
            ocr_output_dir = os.path.join(project_root, "output", "ocr", today_date_for_filename)
            os.makedirs(ocr_output_dir, exist_ok=True)
            
            # Importar las funciones necesarias
            from lib.pdf_processor import has_text_layer
            from lib.text_extractor import extract_text_with_ocr
            
            # Verificar si Tesseract está instalado
            try:
                import pytesseract
                tesseract_installed = True
            except ImportError:
                tesseract_installed = False
                logger.warning("Pytesseract no está instalado. No se podrá usar OCR para PDFs escaneados.")
            
            # Buscar todos los PDFs en el directorio base (solo archivos, no subdirectorios)
            all_pdfs = [f for f in os.listdir(project_root) if f.lower().endswith('.pdf') and os.path.isfile(os.path.join(project_root, f))]
            logger.info(f"Se encontraron {len(all_pdfs)} archivos PDF en el directorio base")
            
            # Procesar cada PDF
            for pdf_file in all_pdfs:
                pdf_path = os.path.join(project_root, pdf_file)
                logger.info(f"Verificando si el PDF {pdf_file} necesita OCR")
                
                # Verificar si el PDF ya tiene capa de texto
                if not has_text_layer(pdf_path):
                    if not tesseract_installed:
                        logger.warning(f"El PDF {pdf_file} necesita OCR, pero Tesseract no está instalado")
                        continue
                    
                    logger.info(f"El PDF {pdf_file} no tiene capa de texto. Procesando con OCR...")
                    try:
                        # Ruta de salida para el archivo JSON con el texto extraído
                        ocr_output_file = os.path.join(ocr_output_dir, f"{os.path.splitext(pdf_file)[0]}_ocr.json")
                        
                        # Procesar con OCR
                        ocr_result = extract_text_with_ocr(
                            pdf_path=pdf_path,
                            output_path=ocr_output_file,
                            dpi=300,
                            language='spa'
                        )
                        
                        # Verificar si la extracción fue exitosa
                        if ocr_result.get("success") and ocr_result.get("sections"):
                            # Crear nombre descriptivo para este PDF
                            pdf_name = os.path.splitext(pdf_file)[0]
                            
                            # Añadir a general_pdf_texts para que aparezca en el consolidado
                            if 'general_pdf_texts' not in locals():
                                general_pdf_texts = {}
                            
                            general_pdf_texts[pdf_name] = {
                                "metadata": {
                                    "source": pdf_file,
                                    "processed_with": "OCR",
                                    "pages_processed": ocr_result.get("metadata", {}).get("pages_processed", 0)
                                },
                                "content": ocr_result.get("sections", {})
                            }
                            
                            logger.info(f"Texto extraído con OCR para {pdf_file}: {len(ocr_result.get('sections', {}))} secciones")
                        else:
                            error_msg = ocr_result.get("error", "Razón desconocida")
                            logger.warning(f"No se pudo extraer texto con OCR para {pdf_file}: {error_msg}")
                    except Exception as e:
                        logger.error(f"Error al procesar {pdf_file} con OCR: {e}", exc_info=True)
                else:
                    logger.info(f"El PDF {pdf_file} ya tiene capa de texto. No se necesita OCR.")
        
        # --- 12. Generar Estadísticas y Consolidar ---
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

        # --- 13. Verificar contenido HTML y de imágenes existente para incluir en consolidado ---
        logger.info("--- Paso 11: Verificando contenido HTML e imágenes existentes ---")
        
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
                        # Verificar si hay al menos un resultado exitoso
                        successful_results = [res for res in image_data if not res.get('error') and res.get('extracted_text')]
                        if successful_results:
                            logger.info(f"Cargando contenido de imágenes de archivo existente: {image_api_results_json}")
                            processed_data["images_api"] = image_data
                        else:
                            logger.warning(f"El archivo {image_api_results_json} contiene solo errores, no será incluido como procesado.")
            except Exception as e:
                logger.warning(f"Error cargando datos de imágenes desde archivo: {e}")
        
        # Verificar si hay transcripciones de audio que no se hayan incluido
        audio_transcriptions_path = os.path.join(project_root, "audio", f"audio_transcriptions_{today_date_for_filename}.json")
        if not processed_data.get("audio_transcriptions") and os.path.exists(audio_transcriptions_path):
            try:
                with open(audio_transcriptions_path, 'r', encoding='utf-8') as f:
                    transcription_data = json.load(f)
                    if transcription_data:
                        logger.info(f"Cargando transcripciones de audio de archivo existente: {audio_transcriptions_path}")
                        processed_data["audio_transcriptions"] = transcription_data
            except Exception as e:
                logger.warning(f"Error cargando transcripciones de audio desde archivo: {e}")
        
        # Verificar PDFs específicos (28032025-39.pdf y 28032025-40.pdf) por nombre
        if today_date_for_filename == "28032025":
            specific_pdfs = ["28032025-39.pdf", "28032025-40.pdf"]
            for specific_pdf in specific_pdfs:
                pdf_path = os.path.join(project_root, "base", today_date_for_filename, specific_pdf)
                if os.path.exists(pdf_path):
                    logger.info(f"Verificando extracción de texto para PDF específico: {specific_pdf}")
                    
                    # Intentar extraer texto con OCR utilizando la nueva API con verificación de dependencias
                    try:
                        # Crear ruta de salida para el texto OCR
                        output_dir = os.path.join(project_root, "output", "ocr", today_date_for_filename)
                        os.makedirs(output_dir, exist_ok=True)
                        output_path = os.path.join(output_dir, f"{os.path.splitext(specific_pdf)[0]}_ocr.json")
                        
                        # Ejecutar OCR con la nueva API
                        ocr_result = extract_text_with_ocr(
                            pdf_path=pdf_path,
                            output_path=output_path,
                            dpi=300,
                            language='spa',
                            use_gpu=False
                        )
                        
                        # Verificar si la extracción fue exitosa
                        if ocr_result["success"] and ocr_result["sections"]:
                            # Crear nombre descriptivo para este PDF específico
                            pdf_name = os.path.splitext(specific_pdf)[0]
                            
                            # Añadir a facebook_pdf_texts para que aparezca en el consolidado
                            if 'facebook_pdf_texts' not in locals():
                                facebook_pdf_texts = {}
                            
                            facebook_pdf_texts[pdf_name] = {
                                "metadata": {
                                    "source": specific_pdf,
                                    "processed_with": "OCR",
                                    "pages_processed": ocr_result["metadata"]["pages_processed"]
                                },
                                "content": ocr_result["sections"]
                            }
                            
                            logger.info(f"Texto extraído con OCR para {specific_pdf}: {len(ocr_result['sections'])} secciones")
                        else:
                            error_msg = ocr_result.get("error", "Razón desconocida")
                            logger.warning(f"No se pudo extraer texto con OCR para {specific_pdf}: {error_msg}")
                    except Exception as e:
                        logger.error(f"Error procesando PDF específico {specific_pdf}: {e}", exc_info=True)
        
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
             
             # Verificar directorios específicos para PDFs
             pdf_date_dir = os.path.join(project_root, 'base', today_date_for_filename)
             pdf_files = []
             
             if os.path.exists(pdf_date_dir):
                 # Listar todos los PDFs en este directorio
                 pdf_files = [f for f in os.listdir(pdf_date_dir) if f.endswith('.pdf')]
                 logger.info(f"Se encontraron {len(pdf_files)} archivos PDF en {pdf_date_dir}")

             # NUEVO: Consolidar textos de Facebook para eliminar duplicados
             if 'facebook_pdf_texts' in locals() and facebook_pdf_texts:
                 logger.info(f"Consolidando {len(facebook_pdf_texts)} textos de PDFs de Facebook...")
                 original_count = len(facebook_pdf_texts)
                 facebook_pdf_texts = consolidate_pdf_texts(facebook_pdf_texts, similarity_threshold=0.85)
                 logger.info(f"Consolidación completada: {original_count} textos de PDFs reducidos a {len(facebook_pdf_texts)}")
             
             consolidation_data = {
                     "metadata": {
                         "source_pdf": os.path.basename(paths['pdf_input']),
                         "processing_date": stats["run_timestamp"],
                         "stats_summary": stats,
                         "available_pdfs": pdf_files
                     },
                     "extracted_content": {
                         "pdf_paragraphs": pdf_paragraphs if pdf_paragraphs else {},
                         "html_pages": processed_data["html"],
                         "image_texts": processed_data["images_api"],
                         "facebook_results": processed_data["facebook"],
                         "facebook_texts": facebook_pdf_texts if 'facebook_pdf_texts' in locals() else {},
                         "audio_metadata": processed_data.get("audio", {}),
                         "audio_transcriptions": processed_data.get("audio_transcriptions", [])
                     }
             }
             # Asegurar que el directorio 'output' exista
             os.makedirs(os.path.dirname(consolidated_output_path), exist_ok=True)
             save_to_json(consolidation_data, consolidated_output_path, indent=2)
             logger.info(f"Resultados consolidados guardados en: {consolidated_output_path}")

             # NUEVO: Generar y guardar lista de URLs no procesadas
             unprocessed_urls = get_unprocessed_urls(all_links, processed_data)
             if unprocessed_urls:
                 unprocessed_output_path = os.path.join(project_root, 'output', f'unprocessed_urls_{today_date_for_filename}.json')
                 save_to_json(unprocessed_urls, unprocessed_output_path, indent=2)
                 logger.info(f"URLs no procesadas guardadas en: {unprocessed_output_path} ({sum(len(urls) for urls in unprocessed_urls.values())} URLs)")
             else:
                 logger.info("No hay URLs sin procesar.")
                 
        except Exception as e:
            logger.error(f"Error al guardar resultados consolidados: {e}", exc_info=True)

        # Ejecutar script de conversión a Markdown
        logger.info("Ejecutando conversión de archivos consolidados a Markdown...")
        try:
            subprocess.run(['python', 'consolidado_to_markdown.py'])
            logger.info("Conversión a Markdown completada.")
        except Exception as e:
            logger.error(f"Error al ejecutar conversión a Markdown: {e}")

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

def download_audio(url, output_dir):
    """
    Descarga un archivo de audio desde una URL y lo guarda en el directorio especificado.
    
    Args:
        url (str): URL del archivo de audio o video.
        output_dir (str): Directorio donde se guardará el archivo.
    
    Returns:
        str: Ruta del archivo descargado o None si falla.
    """
    try:
        os.makedirs(output_dir, exist_ok=True)
        filename = url.split('/')[-1]
        output_path = os.path.join(output_dir, filename)
        
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            
            # Verificar si es un video y extraer audio con ffmpeg si está disponible
            if not output_path.endswith(('.mp3', '.wav', '.ogg')):
                audio_path = output_path.rsplit('.', 1)[0] + '.mp3'
                if subprocess.run(['ffmpeg', '-i', output_path, '-vn', '-acodec', 'copy', audio_path]).returncode == 0:
                    os.remove(output_path)
                    output_path = audio_path
            
            return output_path
        else:
            logger.error(f"Error al descargar {url}: Status code {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error al descargar {url}: {e}")
        return None

def load_audio_urls(file_path):
    """
    Carga las URLs de audio desde un archivo JSON.
    
    Args:
        file_path (str): Ruta al archivo JSON con las URLs de audio.
    
    Returns:
        list: Lista de URLs de audio.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return list(data.keys())
    except Exception as e:
        logger.error(f"Error al cargar URLs de audio desde {file_path}: {e}")
        return []
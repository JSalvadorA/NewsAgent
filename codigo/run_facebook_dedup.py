#!/usr/bin/env python3
"""
Script independiente para procesar URLs de Facebook con deduplicación.
Soluciona problemas de errores en main_with_dedup.py relacionados con la función check_internet_connection.
"""

import os
import sys
import logging
import json
import time
from datetime import datetime
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

# Asegurarse de que el directorio 'lib' esté en el path para imports
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Configuración de logging
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, 'facebook_dedup.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("facebook_dedup")

# Silenciar logs verbosos
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)
logging.getLogger("webdriver_manager").setLevel(logging.WARNING)

# Imports específicos
from lib.config_unified import get_config
from lib.config_manager import get_paths
from lib.facebook_processor_dedup_improved import FacebookProcessorWithDedup
from lib.history_tracker import HistoryTracker

# Función para verificar conexión a internet
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

def save_to_json(data, output_path, indent=4):
    """Guarda datos en un archivo JSON"""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
    except Exception as e:
        logger.error(f"Error guardando JSON en {output_path}: {e}")

def process_facebook_urls(date_str, fb_urls=None):
    """
    Procesa URLs de Facebook con deduplicación
    
    Args:
        date_str: Fecha en formato ddmmyyyy
        fb_urls: Lista de URLs de Facebook a procesar (opcional)
    
    Returns:
        dict: Resultados del procesamiento
    """
    # Cargar configuración
    config_manager = get_config(project_root)
    config = config_manager.config
    paths = get_paths(config, custom_date=date_str)
    
    # Añadir configuración de deduplicación
    if "facebook_dedup" not in config:
        config["facebook_dedup"] = {
            "enable_deduplication": True,
            "similarity_threshold": 0.85,
            "min_content_length": 100,
            "normalize_urls": True,
            "store_mapping": True
        }
    
    # Inicializar el procesador y el historial
    full_config = {'paths': paths, **config}
    facebook_processor = FacebookProcessorWithDedup(full_config)
    history_tracker = HistoryTracker(paths['history_file'])
    
    # Si no se proporcionaron URLs, cargar de archivo si existe
    if not fb_urls:
        social_file = os.path.join(project_root, 'input', 'Social', f'social_links_{date_str}.json')
        if os.path.exists(social_file):
            try:
                with open(social_file, 'r', encoding='utf-8') as f:
                    social_links = json.load(f)
                fb_urls = []
                for link in social_links:
                    url = link.get("URL", "")
                    if "facebook.com" in url.lower() or "fb.com" in url.lower():
                        fb_urls.append(url)
                logger.info(f"Cargadas {len(fb_urls)} URLs de Facebook desde {social_file}")
            except Exception as e:
                logger.error(f"Error cargando URLs: {e}")
        
        # Si no hay URLs, salir
        if not fb_urls:
            logger.warning("No se encontraron URLs de Facebook para procesar")
            return {}
    
    # Limitar el número de URLs para evitar congelamientos
    max_facebook_urls = 5
    if len(fb_urls) > max_facebook_urls:
        logger.warning(f"Limitando procesamiento a {max_facebook_urls} URLs de Facebook para evitar congelamientos")
        fb_urls = fb_urls[:max_facebook_urls]
    
    logger.info(f"Procesando {len(fb_urls)} URLs de Facebook")
    
    # Crear directorio de fecha en 'base' si no existe
    base_date_dir = os.path.join(project_root, 'base', date_str)
    os.makedirs(base_date_dir, exist_ok=True)
    
    # Verificar conexión a internet
    internet_available = check_internet_connection()
    if not internet_available:
        logger.error("No hay conexión a internet disponible. Saltando procesamiento de Facebook.")
        return {}
    
    # Procesar URLs con timeout
    facebook_start = time.time()
    results = {}
    
    try:
        # Usar ThreadPoolExecutor para aplicar timeout
        with ThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(facebook_processor.process_facebook_urls_parallel, fb_urls, date_str)
            try:
                # Timeout de 2 minutos por URL, máximo 10 minutos
                timeout_seconds = min(600, 120 * len(fb_urls))
                logger.info(f"Procesando URLs con timeout de {timeout_seconds} segundos")
                results = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                logger.error(f"Timeout después de {timeout_seconds} segundos")
                results = {}
    except Exception as e:
        logger.error(f"Error procesando URLs: {e}")
        results = {}
    
    # Calcular duración
    facebook_duration = time.time() - facebook_start
    logger.info(f"Procesamiento completado en {facebook_duration:.2f} segundos")
    
    # Mostrar estadísticas de deduplicación
    total_urls = len(fb_urls)
    unique_urls = sum(1 for result in results.values() if not result.get('is_duplicate') and not result.get('is_content_duplicate', False))
    duplicate_urls = total_urls - unique_urls
    
    logger.info(f"URLs: Total={total_urls}, Únicas={unique_urls}, Duplicadas={duplicate_urls}")
    
    # Guardar resultados
    results_file = os.path.join(project_root, 'output', f"facebook_results_dedup_{date_str}.json")
    save_to_json(results, results_file)
    logger.info(f"Resultados guardados en {results_file}")
    
    # Extraer texto de PDFs si hay resultados
    if results:
        # Añadir URLs al historial (solo las no duplicadas)
        facebook_processed_urls = [url for url, result in results.items() 
                                  if result.get('success') and not result.get('is_duplicate')]
        if facebook_processed_urls:
            history_tracker.add_processed_urls(facebook_processed_urls)
        
        # Extraer texto de PDFs
        logger.info("Extrayendo texto de PDFs...")
        pdf_text_start = time.time()
        facebook_pdf_texts = facebook_processor.extract_text_from_all_pdfs(results)
        pdf_text_duration = time.time() - pdf_text_start
        
        # Guardar textos extraídos
        pdf_texts_path = os.path.join(project_root, 'output', f"facebook_texts_dedup_{date_str}.json")
        save_to_json(facebook_pdf_texts, pdf_texts_path)
        logger.info(f"Textos de {len(facebook_pdf_texts)} PDFs guardados en {pdf_texts_path}")
    
    return results

if __name__ == "__main__":
    # Obtener fecha del argumento o usar por defecto
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.today().strftime('%d%m%Y')
    
    logger.info(f"=== Iniciando procesamiento de Facebook para fecha: {date_str} ===")
    results = process_facebook_urls(date_str)
    
    # Mostrar resumen
    if results:
        logger.info(f"Procesamiento completado exitosamente: {len(results)} URLs procesadas")
    else:
        logger.warning("No se obtuvieron resultados en el procesamiento")
    
    logger.info("=== Procesamiento finalizado ===")

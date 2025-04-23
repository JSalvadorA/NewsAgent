#!/usr/bin/env python3
"""
Script para probar el procesamiento de Facebook con deduplicación.
Ejecuta específicamente el componente de Facebook con detección de contenido duplicado.
"""

import os
import sys
import logging
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

# Ajustar path para importaciones
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

# Importaciones del sistema
from lib.config_unified import get_config
from lib.file_manager import save_to_json, ensure_dir_exists
from lib.facebook_processor_dedup import FacebookProcessorWithDedup
from lib.history_tracker import HistoryTracker

def parse_args():
    """Parsea los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(description="Procesa URLs de Facebook con detección de duplicados")
    
    parser.add_argument('--date', type=str, help="Fecha en formato DDMMYYYY (por defecto: fecha actual)")
    parser.add_argument('--input', type=str, help="Archivo JSON con URLs a procesar")
    parser.add_argument('--disable-dedup', action='store_true', help="Desactiva la deduplicación")
    parser.add_argument('--threshold', type=float, default=0.85, help="Umbral de similitud (0.0-1.0)")
    parser.add_argument('--verbose', '-v', action='store_true', help="Muestra información detallada")
    
    return parser.parse_args()

def load_facebook_urls_from_file(file_path):
    """Carga URLs de Facebook desde un archivo JSON."""
    if not os.path.exists(file_path):
        logger.error(f"Archivo no encontrado: {file_path}")
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # El formato puede variar, intentar extraer las URLs
        urls = []
        
        # Caso 1: Lista de diccionarios con clave "URL"
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            for item in data:
                if "URL" in item and isinstance(item["URL"], str):
                    url = item["URL"]
                    if "facebook.com" in url.lower() or "fb.com" in url.lower():
                        urls.append(url)
        
        # Caso 2: Diccionario con URLs como claves
        elif isinstance(data, dict):
            for url in data.keys():
                if isinstance(url, str) and ("facebook.com" in url.lower() or "fb.com" in url.lower()):
                    urls.append(url)
        
        # Caso 3: Lista simple de URLs
        elif isinstance(data, list) and all(isinstance(item, str) for item in data):
            for url in data:
                if "facebook.com" in url.lower() or "fb.com" in url.lower():
                    urls.append(url)
        
        logger.info(f"Cargadas {len(urls)} URLs de Facebook desde {file_path}")
        return urls
        
    except Exception as e:
        logger.error(f"Error cargando archivo {file_path}: {e}")
        return []

def search_facebook_urls(date_str):
    """Busca URLs de Facebook en archivos de la fecha especificada."""
    urls = []
    
    # Buscar en diferentes ubicaciones
    locations = [
        os.path.join(project_root, 'input', 'Social', f'social_links_{date_str}.json'),
        os.path.join(project_root, 'input', 'Social', f'social_links_{date_str}_unprocessed.json'),
        os.path.join(project_root, 'output', date_str, 'social_links.json'),
        os.path.join(project_root, 'output', f'facebook_results_{date_str}.json')
    ]
    
    for location in locations:
        if os.path.exists(location):
            logger.info(f"Encontrado archivo de URLs: {location}")
            file_urls = load_facebook_urls_from_file(location)
            if file_urls:
                urls.extend(file_urls)
    
    return urls

def run_facebook_processing(args):
    """Ejecuta el procesamiento de Facebook con deduplicación."""
    
    # 1. Obtener fecha a procesar
    date_str = args.date
    if not date_str:
        date_str = datetime.now().strftime('%d%m%Y')
        logger.info(f"Usando fecha actual: {date_str}")
    
    # 2. Cargar configuración
    logger.info(f"Cargando configuración...")
    config_manager = get_config(project_root)
    paths = config_manager.generate_paths(custom_date=date_str)
    config = config_manager.config
    
    # Añadir configuración específica para deduplicación
    facebook_dedup_config = {
        "enable_deduplication": not args.disable_dedup,
        "similarity_threshold": args.threshold,
        "store_mapping": True
    }
    
    if "facebook_dedup" not in config:
        config["facebook_dedup"] = facebook_dedup_config
    else:
        config["facebook_dedup"].update(facebook_dedup_config)
    
    # Combinar configuración y paths
    full_config = {'paths': paths, **config}
    
    # 3. Cargar URLs
    facebook_urls = []
    
    if args.input and os.path.exists(args.input):
        # Cargar desde archivo específico
        facebook_urls = load_facebook_urls_from_file(args.input)
    else:
        # Buscar en ubicaciones por defecto
        facebook_urls = search_facebook_urls(date_str)
    
    if not facebook_urls:
        logger.warning("No se encontraron URLs de Facebook para procesar.")
        return False
    
    logger.info(f"Se procesarán {len(facebook_urls)} URLs de Facebook.")
    
    # 4. Crear procesador con deduplicación
    logger.info(f"Inicializando procesador con deduplicación...")
    facebook_processor = FacebookProcessorWithDedup(full_config)
    
    # 5. Procesar URLs
    logger.info(f"Iniciando procesamiento de URLs...")
    start_time = time.time()
    
    # Procesar URLs
    results = facebook_processor.process_facebook_urls_parallel(facebook_urls, date_str)
    
    # Extraer texto de PDFs
    logger.info(f"Extrayendo texto de PDFs generados...")
    pdf_texts = facebook_processor.extract_text_from_all_pdfs(results)
    
    # 6. Guardar resultados
    output_dir = os.path.join(project_root, 'output')
    ensure_dir_exists(output_dir)
    
    results_file = os.path.join(output_dir, f"facebook_results_dedup_{date_str}.json")
    save_to_json(results, results_file)
    logger.info(f"Resultados guardados en: {results_file}")
    
    texts_file = os.path.join(output_dir, f"facebook_texts_dedup_{date_str}.json")
    save_to_json(pdf_texts, texts_file)
    logger.info(f"Textos extraídos guardados en: {texts_file}")
    
    # 7. Estadísticas del procesamiento
    end_time = time.time()
    total_time = end_time - start_time
    
    # Contar originales vs duplicados
    total_urls = len(facebook_urls)
    duplicates = sum(1 for r in results.values() if r.get('is_duplicate') or r.get('is_content_duplicate', False))
    unique_count = total_urls - duplicates
    
    stats = {
        "timestamp": datetime.now().isoformat(),
        "date_processed": date_str,
        "total_urls": total_urls,
        "unique_urls": unique_count,
        "duplicate_urls": duplicates,
        "duplicate_percentage": round((duplicates / total_urls) * 100, 2) if total_urls > 0 else 0,
        "processing_time_seconds": round(total_time, 2),
        "deduplication_enabled": not args.disable_dedup,
        "similarity_threshold": args.threshold
    }
    
    stats_file = os.path.join(output_dir, f"facebook_dedup_stats_{date_str}.json")
    save_to_json(stats, stats_file)
    
    logger.info(f"Procesamiento completado en {total_time:.2f} segundos.")
    logger.info(f"URLs totales: {total_urls}, Únicas: {unique_count}, Duplicadas: {duplicates}")
    logger.info(f"Estadísticas guardadas en: {stats_file}")
    
    return True

def main():
    """Función principal del script."""
    args = parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("=== INICIANDO PROCESAMIENTO DE FACEBOOK CON DEDUPLICACIÓN ===")
    
    success = run_facebook_processing(args)
    
    logger.info("=== PROCESAMIENTO FINALIZADO ===")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())

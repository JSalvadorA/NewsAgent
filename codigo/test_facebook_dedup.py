#!/usr/bin/env python3
"""
Script para probar específicamente la deduplicación de Facebook.
No procesa el PDF completo, solo las URLs de Facebook.
"""

import os
import sys
import logging
import json
import time
from datetime import datetime
import argparse

# Ajustar path para importaciones
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Configuración de logging
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, 'facebook_dedup_test.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("facebook_dedup_test")

# Importar módulos específicos
from lib.config_unified import get_config
from lib.file_manager import save_to_json, ensure_dir_exists
from lib.facebook_processor_dedup_improved import FacebookProcessorWithDedup

def parse_args():
    """Procesa argumentos de línea de comandos"""
    parser = argparse.ArgumentParser(description="Prueba de deduplicación de Facebook")
    parser.add_argument('--date', type=str, help="Fecha en formato DDMMYYYY (default: fecha actual)")
    parser.add_argument('--input', type=str, help="Archivo JSON con URLs a procesar")
    parser.add_argument('--threshold', type=float, default=0.85, help="Umbral de similitud (0.0-1.0)")
    parser.add_argument('--disable-dedup', action='store_true', help="Desactiva la deduplicación")
    return parser.parse_args()

def find_facebook_files(date_str):
    """Busca archivos con URLs de Facebook en el sistema"""
    files = []
    
    # Rutas comunes donde encontrar URLs de Facebook
    search_paths = [
        os.path.join(project_root, 'input', 'Social'),
        os.path.join(project_root, 'output'),
        os.path.join(project_root, 'output', date_str)
    ]
    
    for path in search_paths:
        if not os.path.exists(path):
            continue
            
        # Buscar archivos JSON en la ruta
        json_files = [f for f in os.listdir(path) if f.endswith('.json') and 
                      ('facebook' in f.lower() or 'social' in f.lower())]
        
        for json_file in json_files:
            files.append(os.path.join(path, json_file))
    
    return files

def extract_facebook_urls(files):
    """Extrae URLs de Facebook de los archivos JSON encontrados"""
    fb_urls = []
    
    for file_path in files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Determinar estructura
            if isinstance(data, list):
                # Lista de URLs o diccionarios
                for item in data:
                    if isinstance(item, str) and ('facebook.com' in item.lower() or 'fb.com' in item.lower()):
                        fb_urls.append(item)
                    elif isinstance(item, dict) and 'URL' in item:
                        url = item['URL']
                        if 'facebook.com' in url.lower() or 'fb.com' in url.lower():
                            fb_urls.append(url)
            
            elif isinstance(data, dict):
                # Diccionario con URLs como claves o valores
                for key, value in data.items():
                    if isinstance(key, str) and ('facebook.com' in key.lower() or 'fb.com' in key.lower()):
                        fb_urls.append(key)
                    
                    if isinstance(value, dict) and 'url' in value:
                        url = value['url']
                        if isinstance(url, str) and ('facebook.com' in url.lower() or 'fb.com' in url.lower()):
                            fb_urls.append(url)
            
            logger.info(f"Extraídas {len(fb_urls)} URLs de Facebook de {file_path}")
        except Exception as e:
            logger.warning(f"Error procesando archivo {file_path}: {e}")
    
    # Eliminar duplicados
    unique_urls = list(set(fb_urls))
    logger.info(f"Total URLs encontradas: {len(fb_urls)}, únicas: {len(unique_urls)}")
    return unique_urls

def load_urls_from_file(file_path):
    """Carga URLs directamente desde un archivo específico"""
    if not os.path.exists(file_path):
        logger.error(f"Archivo no encontrado: {file_path}")
        return []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Extraer URLs según la estructura
        urls = []
        
        if isinstance(data, list):
            for item in data:
                if isinstance(item, str):
                    urls.append(item)
                elif isinstance(item, dict) and 'URL' in item:
                    urls.append(item['URL'])
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(key, str) and ('http' in key or 'www.' in key):
                    urls.append(key)
        
        # Filtrar solo URLs de Facebook
        fb_urls = [url for url in urls if 'facebook.com' in url.lower() or 'fb.com' in url.lower()]
        logger.info(f"Cargadas {len(fb_urls)} URLs de Facebook desde {file_path}")
        return fb_urls
    
    except Exception as e:
        logger.error(f"Error cargando archivo {file_path}: {e}")
        return []

def main():
    """Función principal"""
    args = parse_args()
    
    # Obtener fecha
    date_str = args.date
    if not date_str:
        date_str = datetime.now().strftime('%d%m%Y')
        logger.info(f"Usando fecha actual: {date_str}")
    
    # Cargar configuración
    config_manager = get_config(project_root)
    paths = config_manager.generate_paths(custom_date=date_str)
    config = config_manager.config
    
    # Configurar deduplicación
    config["facebook_dedup"] = {
        "enable_deduplication": not args.disable_dedup,
        "similarity_threshold": args.threshold,
        "min_content_length": 100,
        "normalize_urls": True,
        "store_mapping": True
    }
    
    full_config = {'paths': paths, **config}
    
    # Obtener URLs de Facebook
    fb_urls = []
    
    if args.input:
        # Cargar desde archivo específico
        fb_urls = load_urls_from_file(args.input)
    else:
        # Buscar en el sistema
        files = find_facebook_files(date_str)
        fb_urls = extract_facebook_urls(files)
    
    if not fb_urls:
        logger.error("No se encontraron URLs de Facebook para procesar.")
        return 1
    
    # Crear directorio para PDFs si no existe
    base_dir = os.path.join(project_root, 'base', date_str)
    os.makedirs(base_dir, exist_ok=True)
    
    # Procesar URLs
    start_time = time.time()
    logger.info(f"Iniciando procesamiento de {len(fb_urls)} URLs con deduplicación={'desactivada' if args.disable_dedup else 'activada'}")
    
    # Crear procesador con deduplicación
    facebook_processor = FacebookProcessorWithDedup(full_config)
    
    # Procesar URLs
    results = facebook_processor.process_facebook_urls_parallel(fb_urls, date_str)
    
    # Extraer textos
    if results:
        pdf_texts = facebook_processor.extract_text_from_all_pdfs(results)
    else:
        pdf_texts = {}
    
    # Calcular estadísticas
    end_time = time.time()
    total_time = end_time - start_time
    
    total_urls = len(fb_urls)
    processed_urls = len(results)
    successful_urls = sum(1 for r in results.values() if r.get('success'))
    duplicate_urls = sum(1 for r in results.values() if r.get('is_duplicate') or r.get('is_content_duplicate'))
    unique_urls = processed_urls - duplicate_urls
    
    # Generar estadísticas
    stats = {
        "timestamp": datetime.now().isoformat(),
        "date_processed": date_str,
        "deduplication_enabled": not args.disable_dedup,
        "similarity_threshold": args.threshold,
        "total_urls": total_urls,
        "processed_urls": processed_urls,
        "successful_urls": successful_urls,
        "unique_urls": unique_urls,
        "duplicate_urls": duplicate_urls,
        "duplicate_percentage": round((duplicate_urls / total_urls) * 100, 2) if total_urls > 0 else 0,
        "processing_time_seconds": round(total_time, 2)
    }
    
    # Guardar resultados
    output_dir = os.path.join(project_root, 'output')
    os.makedirs(output_dir, exist_ok=True)
    
    results_file = os.path.join(output_dir, f"facebook_test_results_{date_str}.json")
    save_to_json(results, results_file)
    
    texts_file = os.path.join(output_dir, f"facebook_test_texts_{date_str}.json")
    save_to_json(pdf_texts, texts_file)
    
    stats_file = os.path.join(output_dir, f"facebook_test_stats_{date_str}.json")
    save_to_json(stats, stats_file)
    
    # Mostrar resultados
    logger.info("=== RESULTADOS ===")
    logger.info(f"URLs totales: {total_urls}")
    logger.info(f"URLs procesadas: {processed_urls}")
    logger.info(f"URLs exitosas: {successful_urls}")
    logger.info(f"URLs únicas: {unique_urls}")
    logger.info(f"URLs duplicadas: {duplicate_urls} ({stats['duplicate_percentage']}%)")
    logger.info(f"Tiempo de procesamiento: {total_time:.2f} segundos")
    logger.info(f"Resultados guardados en: {results_file}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

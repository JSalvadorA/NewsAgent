#!/usr/bin/env python3
# testear_imagen.py - Script para procesar una sola imagen a la vez durante testeos

import os
import sys
import csv
import time
from datetime import datetime

# Asegurarnos que la ruta del código está en el path
project_root = "C:/Jerson/SUNASS/2025/4_April/gem/scr1403"
code_dir = os.path.join(project_root, "codigo")
if code_dir not in sys.path:
    sys.path.append(code_dir)

# Configurar logging básico
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("testear_imagen")

def leer_urls_imagenes(fecha):
    """
    Lee las URLs de imágenes desde el archivo CSV de enlaces extraídos.
    
    Args:
        fecha (str): Fecha en formato DDMMYYYY
    Returns:
        list: Lista de URLs de imágenes
    """
    csv_path = os.path.join(project_root, "input", "In", f"links_extracted_{fecha}.csv")
    if not os.path.exists(csv_path):
        logger.error(f"Archivo CSV no encontrado: {csv_path}")
        return []
    
    urls_imagenes = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 2:
                url = row[1]
                # Filtrar URLs que parecen ser imágenes por su extensión
                if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                    urls_imagenes.append(url)
    logger.info(f"Encontradas {len(urls_imagenes)} URLs de imágenes en el CSV")
    return urls_imagenes

def testear_una_imagen(fecha, indice_inicial=0):
    """
    Procesa una sola imagen a partir del índice inicial.
    
    Args:
        fecha (str): Fecha en formato DDMMYYYY
        indice_inicial (int): Índice de la URL a procesar
    """
    logger.info("=" * 80)
    logger.info(f"TESTEO DE IMAGEN PARA FECHA: {fecha}")
    logger.info("=" * 80)
    
    # Leer URLs de imágenes
    urls_imagenes = leer_urls_imagenes(fecha)
    if not urls_imagenes:
        logger.error("No se encontraron URLs de imágenes para procesar.")
        return
    
    if indice_inicial >= len(urls_imagenes):
        logger.info(f"Índice {indice_inicial} fuera de rango. No hay más imágenes para procesar.")
        return
    
    url_a_procesar = urls_imagenes[indice_inicial]
    logger.info(f"Procesando imagen {indice_inicial + 1}/{len(urls_imagenes)}: {url_a_procesar}")
    
    try:
        # Importar componentes necesarios
        from codigo.lib.config_manager import load_config, get_paths
        from codigo.lib.image_processor import ImageProcessor
        
        # Cargar configuración
        config = load_config(project_root)
        paths = get_paths(config, custom_date=fecha)
        full_config = {'paths': paths, **config}
        
        # Inicializar procesador de imágenes
        image_processor = ImageProcessor(full_config)
        
        # Procesar una sola imagen
        start_time = time.time()
        metadata = image_processor.download_images_parallel([url_a_procesar], fecha)
        duration = time.time() - start_time
        
        if metadata and url_a_procesar in metadata:
            logger.info(f"✅ Imagen procesada con éxito en {duration:.2f} segundos")
            logger.info(f"Detalles: {metadata[url_a_procesar]}")
        else:
            logger.error(f"❌ Fallo al procesar la imagen. No se encontraron metadatos.")
    except Exception as e:
        logger.error(f"❌ Error procesando la imagen: {str(e)}")
        import traceback
        traceback.print_exc()
    
    logger.info("=" * 80)
    logger.info(f"Testeo completado para imagen {indice_inicial + 1}. Si desea probar la siguiente, ejecute con --indice {indice_inicial + 1}")
    logger.info("=" * 80)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Procesa una sola imagen a la vez para testeo.')
    parser.add_argument('fecha', type=str, help='Fecha en formato DDMMYYYY (ej: 05032025)')
    parser.add_argument('--indice', type=int, default=0, help='Índice de la imagen a procesar (0 para la primera)')
    args = parser.parse_args()
    
    if not args.fecha.isdigit() or len(args.fecha) != 8:
        logger.error("❌ Error: La fecha debe tener formato DDMMYYYY (ejemplo: 05032025)")
        sys.exit(1)
    
    if args.indice < 0:
        logger.error("❌ Error: El índice debe ser mayor o igual a 0")
        sys.exit(1)
    
    testear_una_imagen(args.fecha, args.indice) 
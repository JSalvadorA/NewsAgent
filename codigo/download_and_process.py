#!/usr/bin/env python3
"""
download_and_process.py
Script puente que descarga imágenes usando el sistema original
y luego las procesa con el sistema mejorado con deduplicación.

Esto permite probar el sistema de procesamiento sin modificar
los sistemas existentes.
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta

# Configurar logging
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'download_and_process.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("download_and_process")

# Agregar lib al path
lib_path = os.path.join(current_dir, 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Importar componentes necesarios
from lib.config_unified import get_config
from process_pending_images import EnhancedImageProcessor

def download_images_for_date(date_str, use_dedup=False):
    """
    Utiliza el sistema original para descargar imágenes para una fecha específica.
    
    Args:
        date_str: Fecha en formato ddmmyyyy
        use_dedup: Si es True, usa main_with_dedup.py, de lo contrario usa main.py
    
    Returns:
        bool: True si la descarga fue exitosa
    """
    try:
        script_path = os.path.join(current_dir, 'main_with_dedup.py' if use_dedup else 'main.py')
        if not os.path.exists(script_path):
            logger.error(f"Script no encontrado: {script_path}")
            return False
        
        # Ejecutar el sistema original
        logger.info(f"Iniciando descarga de imágenes para fecha {date_str}...")
        
        import importlib.util
        import subprocess
        
        try:
            logger.info(f"Ejecutando: python {script_path} {date_str}")
            result = subprocess.run(
                [sys.executable, script_path, date_str],
                capture_output=True,
                text=True,
                check=False  # No lanzar excepción si el código de salida no es 0
            )
            
            if result.returncode != 0:
                logger.warning(f"Script {script_path} terminó con código de error {result.returncode}")
                logger.warning(f"Stderr: {result.stderr}")
            else:
                logger.info(f"Descarga completada para fecha {date_str}")
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"Error ejecutando script original: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error en descarga de imágenes: {e}")
        return False

def verify_images_downloaded(date_str):
    """
    Verifica si las imágenes para una fecha específica ya fueron descargadas.
    Busca en varias rutas posibles según la estructura del sistema.
    
    Args:
        date_str: Fecha en formato ddmmyyyy
        
    Returns:
        tuple: (descargadas, ruta del directorio de imágenes, número de imágenes)
    """
    # Posibles ubicaciones de imágenes según la estructura del sistema
    possible_paths = [
        # Estructura 1: output/FECHA/images
        os.path.join(project_root, 'output', date_str, 'images'),
        
        # Estructura 2: output/Images/FECHA
        os.path.join(project_root, 'output', 'Images', date_str),
        
        # Estructura 3: input/Images/FECHA 
        os.path.join(project_root, 'input', 'Images', date_str),
        
        # Estructura 4: Base de PDF con imágenes extraídas
        os.path.join(project_root, 'base', date_str),
        
        # Estructura 5: input/Out/scraped_pdf_FECHA/images
        os.path.join(project_root, 'input', 'Out', f'scraped_pdf_{date_str}', 'images')
    ]
    
    # Buscar imágenes en todas las rutas posibles
    total_images = 0
    found_dir = None
    image_files = []
    
    for path in possible_paths:
        if os.path.exists(path) and os.path.isdir(path):
            logger.info(f"Verificando imágenes en: {path}")
            dir_images = []
            
            # Buscar en este directorio y sus subdirectorios
            for root, _, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                        img_path = os.path.join(root, file)
                        dir_images.append(img_path)
            
            if dir_images:
                logger.info(f"Encontradas {len(dir_images)} imágenes en {path}")
                image_files.extend(dir_images)
                if not found_dir:  # Mantener el primer directorio con imágenes como el principal
                    found_dir = path
    
    total_images = len(image_files)
    if total_images > 0:
        logger.info(f"Total de imágenes encontradas para fecha {date_str}: {total_images}")
        return True, found_dir, total_images
    else:
        logger.warning(f"No se encontraron imágenes para fecha {date_str} en ninguna ubicación")
        # Si no se encontraron imágenes, devolver la primera ruta como ubicación predeterminada
        return False, possible_paths[0], 0

def copy_images_to_output(date_str, source_dir, force=False):
    """
    Copia las imágenes encontradas a la estructura esperada por el procesador.
    
    Args:
        date_str: Fecha en formato ddmmyyyy
        source_dir: Directorio de origen con las imágenes
        force: Si es True, sobrescribe imágenes existentes
    
    Returns:
        tuple: (éxito, directorio de destino, número de imágenes copiadas)
    """
    from shutil import copy2
    
    # Directorio esperado por el procesador
    target_dir = os.path.join(project_root, 'output', date_str, 'images')
    os.makedirs(target_dir, exist_ok=True)
    
    # Si source_dir y target_dir son iguales, no es necesario copiar
    if os.path.normpath(source_dir) == os.path.normpath(target_dir):
        logger.info(f"Las imágenes ya están en la ubicación esperada: {target_dir}")
        
        # Contar imágenes en el directorio
        image_count = 0
        for root, _, files in os.walk(target_dir):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    image_count += 1
        
        return True, target_dir, image_count
    
    # Buscar imágenes en el directorio de origen
    images_copied = 0
    try:
        logger.info(f"Copiando imágenes de {source_dir} a {target_dir}...")
        
        for root, _, files in os.walk(source_dir):
            for file in files:
                if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                    source_path = os.path.join(root, file)
                    target_path = os.path.join(target_dir, file)
                    
                    # Verificar si ya existe
                    if os.path.exists(target_path) and not force:
                        logger.debug(f"Imagen ya existe en destino (omitida): {file}")
                        continue
                    
                    # Copiar archivo
                    copy2(source_path, target_path)
                    images_copied += 1
        
        logger.info(f"Se copiaron {images_copied} imágenes a {target_dir}")
        return True, target_dir, images_copied
        
    except Exception as e:
        logger.error(f"Error copiando imágenes: {e}")
        return False, target_dir, images_copied

def process_date_range(start_date_str, end_date_str, force_download=False, use_dedup=False):
    """
    Procesa un rango de fechas: descarga imágenes y luego las procesa.
    
    Args:
        start_date_str: Fecha inicial en formato ddmmyyyy
        end_date_str: Fecha final en formato ddmmyyyy
        force_download: Si es True, fuerza la descarga incluso si ya existen imágenes
        use_dedup: Si es True, usa main_with_dedup.py para la descarga
    """
    # Convertir strings a objetos datetime
    start_date = datetime.strptime(start_date_str, '%d%m%Y')
    end_date = datetime.strptime(end_date_str, '%d%m%Y')
    
    # Preparar lista de fechas a procesar
    current_date = start_date
    dates_to_process = []
    
    while current_date <= end_date:
        date_str = current_date.strftime('%d%m%Y')
        dates_to_process.append(date_str)
        current_date += timedelta(days=1)
    
    # Cargar configuración
    config_manager = get_config(project_root)
    config = config_manager.config
    
    # Inicializar procesador mejorado
    processor = EnhancedImageProcessor(config)
    
    # Procesar cada fecha
    for date_str in dates_to_process:
        logger.info(f"=== Procesando fecha: {date_str} ===")
        
        # Verificar si ya hay imágenes
        has_images, images_dir, num_images = verify_images_downloaded(date_str)
        
        if not has_images or force_download:
            # Descargar imágenes
            logger.info(f"No se encontraron imágenes para {date_str} o se forzó descarga. Descargando...")
            download_success = download_images_for_date(date_str, use_dedup)
            
            if not download_success:
                logger.error(f"Error en descarga para fecha {date_str}. Pasando a siguiente fecha.")
                continue
                
            # Verificar nuevamente después de descarga
            has_images, images_dir, num_images = verify_images_downloaded(date_str)
            
            if not has_images:
                logger.warning(f"No se encontraron imágenes para {date_str} después de la descarga. Pasando a siguiente fecha.")
                continue
        
        logger.info(f"Encontradas {num_images} imágenes en {images_dir}")
        
        # Copiar imágenes a la ubicación esperada por el procesador si es necesario
        copy_success, processing_dir, copied_count = copy_images_to_output(date_str, images_dir)
        if not copy_success:
            logger.warning(f"Problemas al copiar imágenes para procesamiento. Continuando de todos modos.")
        
        # Procesar las imágenes
        logger.info(f"Iniciando procesamiento de imágenes para fecha {date_str}...")
        processor.process_pending_images([date_str])
        
        logger.info(f"Procesamiento completo para fecha {date_str}")
        
        # Pausa entre fechas
        if date_str != dates_to_process[-1]:
            logger.info("Pausa de 60 segundos antes de la siguiente fecha...")
            time.sleep(60)

def main():
    """Función principal para ejecución directa"""
    parser = argparse.ArgumentParser(
        description="Descarga y procesa imágenes de un rango de fechas",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument("--date", type=str, help="Fecha específica a procesar (formato DDMMYYYY)")
    date_group.add_argument("--range", type=str, nargs=2, metavar=("START", "END"), 
                         help="Rango de fechas a procesar (formato DDMMYYYY)")
    
    parser.add_argument("--force", action="store_true", 
                       help="Forzar descarga incluso si ya existen imágenes")
    parser.add_argument("--dedup", action="store_true",
                       help="Usar sistema con deduplicación para descargas")
    
    args = parser.parse_args()
    
    if args.date:
        # Procesar una sola fecha
        process_date_range(args.date, args.date, args.force, args.dedup)
    else:
        # Procesar rango de fechas
        process_date_range(args.range[0], args.range[1], args.force, args.dedup)
    
    logger.info("Procesamiento completo.")

if __name__ == "__main__":
    main() 
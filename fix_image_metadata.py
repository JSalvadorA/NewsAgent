#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para corregir problemas con metadatos de imágenes y eliminar archivos incorrectos.
Específicamente, detecta archivos que se guardaron como imágenes pero no lo son (como MP3),
y corrige imágenes duplicadas.
"""

import os
import sys
import json
import logging
import shutil
from datetime import datetime
from PIL import Image

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("image_metadata_fixer")

# Raíz del proyecto
project_root = os.path.dirname(os.path.abspath(__file__))

def load_json_file(file_path):
    """Carga un archivo JSON y retorna su contenido."""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"Error cargando archivo JSON {file_path}: {e}")
        return {}

def save_json_file(data, file_path):
    """Guarda datos en un archivo JSON."""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        logger.info(f"Archivo guardado: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error guardando archivo JSON {file_path}: {e}")
        return False

def is_valid_image(file_path):
    """Verifica si un archivo es una imagen válida."""
    try:
        with Image.open(file_path) as img:
            img.verify()
            return True
    except Exception:
        return False

def fix_images_for_date(date_str):
    """
    Corrige problemas con imágenes para una fecha específica.
    
    Args:
        date_str: Fecha en formato DDMMYYYY
    """
    # Rutas de directorios y archivos
    images_dir = os.path.join(project_root, 'input', 'Images')
    downloads_dir = os.path.join(images_dir, 'downloads', date_str)
    metadata_file = os.path.join(images_dir, f'image_links_{date_str}.json')
    api_results_file = os.path.join(downloads_dir, 'texto_imagenes_api.json')
    
    if not os.path.exists(downloads_dir):
        logger.error(f"No se encontró el directorio de imágenes para fecha {date_str}")
        return False
    
    logger.info(f"Analizando imágenes para fecha: {date_str}")
    
    # Cargar metadatos de imágenes
    metadata = load_json_file(metadata_file)
    if not metadata:
        logger.error(f"No se encontraron metadatos para fecha {date_str}")
        return False
    
    # Cargar resultados de API (si existen)
    api_results = load_json_file(api_results_file)
    
    # Listar archivos en el directorio
    files_in_dir = os.listdir(downloads_dir)
    image_files = [f for f in files_in_dir if f.endswith(('.jpg', '.jpeg', '.png', '.gif'))]
    
    logger.info(f"Encontrados {len(image_files)} archivos de imagen en {downloads_dir}")
    
    # 1. Verificar archivos que no son imágenes
    invalid_images = []
    valid_images = []
    
    for img_file in image_files:
        img_path = os.path.join(downloads_dir, img_file)
        if not is_valid_image(img_path):
            invalid_images.append(img_file)
        else:
            valid_images.append(img_file)
    
    if invalid_images:
        logger.warning(f"Encontrados {len(invalid_images)} archivos que no son imágenes válidas:")
        for idx, invalid in enumerate(invalid_images, 1):
            logger.warning(f"  {idx}. {invalid}")
        
        # Crear directorio para archivos inválidos
        invalid_dir = os.path.join(downloads_dir, 'invalid_files')
        os.makedirs(invalid_dir, exist_ok=True)
        
        # Mover archivos inválidos
        for invalid in invalid_images:
            src = os.path.join(downloads_dir, invalid)
            dst = os.path.join(invalid_dir, invalid)
            try:
                shutil.move(src, dst)
                logger.info(f"Movido archivo inválido: {invalid} -> {invalid_dir}")
            except Exception as e:
                logger.error(f"Error moviendo archivo {invalid}: {e}")
    
    # 2. Buscar URLs duplicadas en metadatos
    url_to_file = {}
    duplicate_urls = set()
    
    for url, meta in metadata.items():
        filename = meta.get('filename')
        if filename in url_to_file.values():
            # Encontrar URL duplicada que apunta al mismo archivo
            duplicate_urls.add(url)
        else:
            url_to_file[url] = filename
    
    if duplicate_urls:
        logger.warning(f"Encontradas {len(duplicate_urls)} URLs duplicadas en metadatos")
        
        # Eliminar URLs duplicadas de los metadatos
        for url in duplicate_urls:
            if url in metadata:
                logger.info(f"Eliminando URL duplicada: {url}")
                del metadata[url]
        
        # Guardar metadatos corregidos
        save_json_file(metadata, metadata_file)
    
    # 3. Verificar imágenes en resultados de API
    if api_results:
        new_api_results = []
        
        for result in api_results:
            filename = result.get('image_filename')
            
            # Omitir resultados de imágenes inválidas
            if filename in invalid_images:
                logger.info(f"Omitiendo resultado de API para archivo inválido: {filename}")
                continue
                
            # Mantener el resultado para imágenes válidas
            new_api_results.append(result)
        
        # Guardar resultados de API corregidos si hubo cambios
        if len(new_api_results) < len(api_results):
            logger.info(f"Guardando resultados de API corregidos: {len(new_api_results)} de {len(api_results)}")
            save_json_file(new_api_results, api_results_file)
    
    logger.info(f"Corrección completada para fecha {date_str}")
    logger.info(f"Imágenes válidas: {len(valid_images)}")
    logger.info(f"Imágenes inválidas movidas: {len(invalid_images)}")
    
    return True

def main():
    if len(sys.argv) < 2:
        print("Uso: python fix_image_metadata.py DDMMYYYY")
        return 1
    
    date_str = sys.argv[1]
    
    # Validar formato de fecha
    try:
        datetime.strptime(date_str, '%d%m%Y')
    except ValueError:
        print(f"Formato de fecha inválido: '{date_str}'. Debe ser DDMMYYYY.")
        return 1
    
    # Ejecutar la corrección
    success = fix_images_for_date(date_str)
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Script para limpiar el caché del sistema NewsAgent.
Elimina archivos de caché manteniendo la estructura de directorios y archivos esenciales.
"""

import os
import sys
import shutil
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("cache_cleaner")

def get_project_root():
    """Obtiene la ruta raíz del proyecto."""
    # Asumimos que este script está en la carpeta codigo/
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..'))
    return project_root

def clean_cache_directory(cache_dir, clear_history=False, backup=True):
    """
    Limpia el directorio de caché, opcionalmente creando un backup.
    
    Args:
        cache_dir: Ruta al directorio de caché
        clear_history: Si es True, también elimina el historial de URLs procesadas
        backup: Si es True, crea un backup antes de limpiar
    
    Returns:
        int: Número de archivos eliminados
    """
    if not os.path.exists(cache_dir):
        logger.warning(f"El directorio de caché no existe: {cache_dir}")
        return 0
    
    # Crear backup si se solicita
    if backup:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"{cache_dir}_backup_{timestamp}"
        logger.info(f"Creando backup de caché en: {backup_dir}")
        shutil.copytree(cache_dir, backup_dir)
    
    # Archivos a conservar (siempre mantener .gitkeep)
    files_to_keep = ['.gitkeep']
    if not clear_history:
        files_to_keep.append('history.json')
    
    # Contar archivos antes de limpiar
    total_files = sum(1 for _ in Path(cache_dir).glob('**/*') if _.is_file())
    
    # Eliminar archivos en el directorio raíz del caché
    count = 0
    for item in os.listdir(cache_dir):
        item_path = os.path.join(cache_dir, item)
        if os.path.isfile(item_path) and item not in files_to_keep:
            os.remove(item_path)
            count += 1
            logger.debug(f"Eliminado: {item_path}")
    
    # Limpiar subdirectorios pero mantener la estructura
    for root, dirs, files in os.walk(cache_dir):
        # Evitar el directorio raíz que ya procesamos
        if root == cache_dir:
            continue
            
        # Eliminar archivos en subdirectorios
        for file in files:
            if file not in files_to_keep:
                file_path = os.path.join(root, file)
                os.remove(file_path)
                count += 1
                logger.debug(f"Eliminado: {file_path}")
    
    logger.info(f"Cache limpiado: {count} de {total_files} archivos eliminados.")
    return count

def clean_history_files(project_root, backup=True):
    """
    Limpia archivos de historial en la estructura del proyecto.
    
    Args:
        project_root: Ruta raíz del proyecto
        backup: Si es True, crea backup de los archivos de historial
    
    Returns:
        int: Número de archivos de historial limpiados
    """
    # Rutas de archivos de historial
    history_files = [
        os.path.join(project_root, 'codigo', 'lib', 'history', 'processed_urls.json'),
        os.path.join(project_root, 'cache', 'audio_processing_history.json')
    ]
    
    count = 0
    for file_path in history_files:
        if os.path.exists(file_path):
            if backup:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = f"{file_path}.backup_{timestamp}"
                shutil.copy2(file_path, backup_path)
                logger.info(f"Backup de {file_path} creado en {backup_path}")
            
            # Crear un archivo de historial vacío
            directory = os.path.dirname(file_path)
            os.makedirs(directory, exist_ok=True)
            
            # Verificar qué tipo de archivo es y crear estructura adecuada
            if file_path.endswith('processed_urls.json'):
                empty_data = []
            else:
                empty_data = {"processed_files": [], "last_update": datetime.now().isoformat()}
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(empty_data, f, indent=2)
            
            logger.info(f"Archivo de historial limpiado: {file_path}")
            count += 1
    
    return count

def main():
    """Función principal del script."""
    parser = argparse.ArgumentParser(description="Limpia el caché del sistema NewsAgent")
    parser.add_argument("--no-backup", action="store_true", help="No crear backup antes de limpiar")
    parser.add_argument("--keep-history", action="store_true", help="Mantener archivos de historial intactos")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mostrar información detallada del proceso")
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    project_root = get_project_root()
    cache_dir = os.path.join(project_root, 'cache')
    
    logger.info("=== INICIANDO LIMPIEZA DE CACHÉ ===")
    logger.info(f"Directorio del proyecto: {project_root}")
    logger.info(f"Directorio de caché: {cache_dir}")
    
    try:
        # Limpiar directorio de caché
        files_removed = clean_cache_directory(
            cache_dir, 
            clear_history=not args.keep_history,
            backup=not args.no_backup
        )
        
        # Limpiar archivos de historial si se solicita
        if not args.keep_history:
            history_files_cleaned = clean_history_files(
                project_root,
                backup=not args.no_backup
            )
            logger.info(f"Archivos de historial limpiados: {history_files_cleaned}")
        
        logger.info("=== LIMPIEZA COMPLETADA ===")
        logger.info(f"Total de archivos eliminados del caché: {files_removed}")
        
    except Exception as e:
        logger.error(f"Error durante la limpieza: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

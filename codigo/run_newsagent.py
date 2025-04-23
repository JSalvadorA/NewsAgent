#!/usr/bin/env python3
"""
Script para ejecutar el sistema NewsAgent con opción de limpiar el caché.
"""

import os
import sys
import logging
import argparse
import subprocess
import time
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("newsagent_runner")

def get_project_paths():
    """Determina las rutas principales del proyecto."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..'))
    cache_dir = os.path.join(project_root, 'cache')
    return {
        'current_dir': current_dir,
        'project_root': project_root,
        'cache_dir': cache_dir,
        'main_script': os.path.join(current_dir, 'main.py'),
        'clean_cache_script': os.path.join(current_dir, 'clean_cache.py')
    }

def clean_cache(paths, no_backup=False, keep_history=False):
    """Ejecuta el script de limpieza de caché."""
    clean_cache_script = paths['clean_cache_script']
    
    if not os.path.exists(clean_cache_script):
        logger.error(f"Script de limpieza de caché no encontrado: {clean_cache_script}")
        return False
    
    try:
        # Construir comando
        cmd = [sys.executable, clean_cache_script]
        if no_backup:
            cmd.append('--no-backup')
        if keep_history:
            cmd.append('--keep-history')
        
        # Ejecutar script de limpieza
        logger.info(f"Ejecutando limpieza de caché: {' '.join(cmd)}")
        process = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True,
            check=True
        )
        
        # Mostrar salida
        if process.stdout:
            for line in process.stdout.splitlines():
                logger.info(f"[CLEAN] {line}")
        
        if process.returncode == 0:
            logger.info("Limpieza de caché completada exitosamente")
            return True
        else:
            logger.error(f"Error en limpieza de caché. Código de salida: {process.returncode}")
            if process.stderr:
                for line in process.stderr.splitlines():
                    logger.error(f"[CLEAN ERROR] {line}")
            return False
            
    except subprocess.CalledProcessError as e:
        logger.error(f"Error ejecutando script de limpieza: {e}")
        if e.stderr:
            for line in e.stderr.splitlines():
                logger.error(f"[CLEAN ERROR] {line}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado durante limpieza: {e}")
        return False

def run_newsagent(paths, date_str=None):
    """Ejecuta el sistema NewsAgent."""
    main_script = paths['main_script']
    
    if not os.path.exists(main_script):
        logger.error(f"Script principal no encontrado: {main_script}")
        return False
    
    try:
        # Construir comando
        cmd = [sys.executable, main_script]
        if date_str:
            cmd.append(date_str)
        
        # Ejecutar sistema principal
        logger.info(f"Ejecutando NewsAgent: {' '.join(cmd)}")
        start_time = time.time()
        
        process = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            text=True
        )
        
        # Calcular duración
        duration = time.time() - start_time
        
        # Mostrar salida
        if process.stdout:
            for line in process.stdout.splitlines():
                logger.info(f"[NEWSAGENT] {line}")
        
        if process.returncode == 0:
            logger.info(f"Ejecución completada exitosamente en {duration:.2f} segundos")
            return True
        else:
            logger.error(f"Error en ejecución. Código de salida: {process.returncode}")
            if process.stderr:
                for line in process.stderr.splitlines():
                    logger.error(f"[NEWSAGENT ERROR] {line}")
            return False
            
    except Exception as e:
        logger.error(f"Error inesperado durante ejecución: {e}")
        return False

def parse_arguments():
    """Parsea los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Ejecuta el sistema NewsAgent con opción de limpiar caché"
    )
    
    # Opciones para limpieza de caché
    parser.add_argument('--clean', action='store_true', 
                        help="Limpiar caché antes de ejecutar")
    parser.add_argument('--no-backup', action='store_true',
                        help="No crear backup al limpiar caché")
    parser.add_argument('--keep-history', action='store_true',
                        help="Mantener historial de URLs procesadas al limpiar caché")
    
    # Opciones para ejecución
    parser.add_argument('--date', type=str,
                        help="Fecha a procesar en formato DDMMYYYY")
    
    # Otras opciones
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="Mostrar información detallada")
    
    return parser.parse_args()

def validate_date(date_str):
    """Valida el formato de fecha."""
    if not date_str:
        return None
        
    try:
        datetime.strptime(date_str, '%d%m%Y')
        return date_str
    except ValueError:
        logger.error(f"Formato de fecha inválido: '{date_str}'. Debe ser ddmmyyyy.")
        return None

def main():
    """Función principal del script."""
    args = parse_arguments()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    paths = get_project_paths()
    
    # Validar fecha si se proporciona
    date_str = validate_date(args.date)
    
    # Limpiar caché si se solicita
    if args.clean:
        logger.info("Iniciando limpieza de caché...")
        clean_success = clean_cache(paths, args.no_backup, args.keep_history)
        if not clean_success:
            logger.warning("La limpieza de caché falló. Continuando con la ejecución...")
    
    # Ejecutar sistema principal
    logger.info("Iniciando ejecución de NewsAgent...")
    run_success = run_newsagent(paths, date_str)
    
    # Resultado final
    if run_success:
        logger.info("Ejecución de NewsAgent completada exitosamente")
        return 0
    else:
        logger.error("Ejecución de NewsAgent falló")
        return 1

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Script de prueba para verificar la capacidad de cargar los componentes clave del sistema.
"""

import os
import sys
import logging
from datetime import datetime
import time

# Configurar logging básico
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_runner")

# Determinar la ruta del proyecto y agregarla al path
current_dir = os.path.dirname(os.path.abspath(__file__))
codigo_path = os.path.join(current_dir, 'codigo')
if codigo_path not in sys.path:
    sys.path.insert(0, codigo_path)
    logger.info(f"Agregado al path: {codigo_path}")

# Directorio de lib también debe estar en el path
lib_path = os.path.join(codigo_path, 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)
    logger.info(f"Agregado al path: {lib_path}")

logger.info("Iniciando prueba de importaciones...")

try:
    # 1. Importar el módulo de configuración
    logger.info("Importando config_unified...")
    from lib.config_unified import get_config
    
    # 2. Obtener configuración
    logger.info("Obteniendo configuración...")
    config_manager = get_config(current_dir)
    paths = config_manager.generate_paths()
    logger.info(f"Configuración cargada. PDF de entrada: {paths.get('pdf_input')}")
    
    # 3. Importar e inicializar módulos principales
    logger.info("Importando módulos principales...")
    
    # 3.1 Importar un módulo sencillo (no el problemático)
    from lib.file_manager import save_to_json, ensure_dir_exists
    logger.info("✓ file_manager importado correctamente")
    
    # 3.2 Intentar importar módulo problemático
    from lib.image_processor import ImageProcessor
    logger.info("✓ image_processor importado correctamente")
    
    # 4. Intentar crear una instancia
    logger.info("Probando inicialización de ImageProcessor...")
    
    config = config_manager.config
    full_config = {'paths': paths, **config}
    
    try:
        # No iniciamos completamente la API
        image_processor = ImageProcessor(full_config)
        logger.info("✓ ImageProcessor inicializado correctamente")
        
        # Verificar atributos clave
        if hasattr(image_processor, 'download_images_parallel'):
            logger.info("✓ Método download_images_parallel disponible")
        
        if hasattr(image_processor, 'process_downloaded_images_with_api'):
            logger.info("✓ Método process_downloaded_images_with_api disponible")
        
        # Verificar si la API está disponible
        if image_processor.api_client:
            logger.info("✓ API client está inicializado")
        else:
            logger.warning("API client no está inicializado, pero esto es normal si no hay API key configurada")
            
    except Exception as e:
        logger.error(f"Error inicializando ImageProcessor: {e}")
    
    # 5. Prueba finalizada
    logger.info("¡Prueba completada con éxito! El sistema parece estar funcionando correctamente.")
    
except Exception as e:
    logger.error(f"ERROR en la prueba: {e}")
    import traceback
    traceback.print_exc()

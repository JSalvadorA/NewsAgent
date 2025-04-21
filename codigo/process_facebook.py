# codigo/process_facebook.py
"""
Script independiente para procesar URLs de Facebook.
Se puede ejecutar directamente o importar como módulo.
"""

import os
import sys
import logging
from datetime import datetime
import argparse

# Asegurarse de que el directorio 'lib' esté en el path para imports
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Configuración de logging
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, 'facebook_processor.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("facebook_processor")

# Silenciar logs verbosos
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)
logging.getLogger("webdriver_manager").setLevel(logging.WARNING)

# Importar módulos de la biblioteca 'lib'
from lib.config_manager import load_config, get_paths
from lib.facebook_processor import FacebookProcessor

def process_facebook_urls(date_str=None):
    """
    Función principal para procesar URLs de Facebook desde archivos JSON.
    
    Args:
        date_str: Fecha en formato ddmmyyyy (opcional)
    
    Returns:
        bool: True si el procesamiento fue exitoso, False en caso contrario
    """
    try:
        # Usar fecha actual si no se proporciona
        today_date_for_filename = date_str if date_str else datetime.today().strftime('%d%m%Y')
        
        logger.info("==================================================")
        logger.info("INICIANDO PROCESAMIENTO DE FACEBOOK")
        logger.info(f"Usando fecha: {today_date_for_filename}")
        logger.info("==================================================")
        
        # Cargar configuración
        config = load_config(project_root)
        paths = get_paths(config, custom_date=today_date_for_filename)
        
        # Asegurar que el directorio 'base' y la carpeta de fecha existan
        base_dir = os.path.join(project_root, 'base')
        date_dir = os.path.join(base_dir, today_date_for_filename)
        
        try:
            # Crear directorios si no existen
            os.makedirs(base_dir, exist_ok=True)
            os.makedirs(date_dir, exist_ok=True)
            logger.info(f"Directorios base y fecha creados/verificados: {date_dir}")
        except Exception as e:
            logger.error(f"Error creando directorios para PDFs: {e}")
            return False
        
        # Construir ruta al archivo JSON de enlaces sociales
        social_links_json = paths.get('social_links_json')
        if not social_links_json:
            logger.error("No se pudo obtener la ruta al archivo de enlaces sociales.")
            return False
        
        # Inicializar el procesador de Facebook
        fb_processor = FacebookProcessor({"paths": paths, **config})
        
        # Procesar URLs de Facebook
        results = fb_processor.process_facebook_from_json(social_links_json, today_date_for_filename)
        
        # Mostrar resumen de resultados
        total_urls = len(results)
        success_count = sum(1 for result in results.values() if result.get("success", False))
        
        logger.info("==================================================")
        logger.info(f"PROCESAMIENTO DE FACEBOOK COMPLETADO:")
        logger.info(f"- Total URLs procesadas: {total_urls}")
        logger.info(f"- URLs exitosas: {success_count}")
        logger.info(f"- URLs fallidas: {total_urls - success_count}")
        logger.info("==================================================")
        
        return True
    
    except Exception as e:
        logger.critical(f"Error inesperado en el procesamiento de Facebook: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    # Configurar parser de argumentos
    parser = argparse.ArgumentParser(description='Procesar URLs de Facebook desde archivos JSON.')
    parser.add_argument('--fecha', type=str, help='Fecha en formato ddmmyyyy (por defecto: fecha actual)')
    
    args = parser.parse_args()
    date_arg = args.fecha
    
    # Validar formato de fecha si se proporciona
    if date_arg:
        try:
            datetime.strptime(date_arg, '%d%m%Y')
            logger.info(f"Se usará la fecha proporcionada: {date_arg}")
        except ValueError:
            logger.error(f"Formato de fecha inválido: '{date_arg}'. Debe ser ddmmyyyy. Usando fecha actual.")
            date_arg = None
    
    # Ejecutar el procesamiento
    success = process_facebook_urls(date_arg)
    
    # Código de salida para scripts de automatización
    sys.exit(0 if success else 1)

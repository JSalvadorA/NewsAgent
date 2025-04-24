#!/usr/bin/env python3
"""
Script para forzar el reprocesamiento de imágenes.
Ignora el caché y resultados previos para permitir probar cambios en el procesamiento.
"""
import sys
import os
import shutil
from process_pending_images import EnhancedImageProcessor
from lib.config_unified import get_config
from lib.config_manager import get_paths

def force_reprocess_images(date_str):
    """
    Fuerza el reprocesamiento de imágenes para una fecha específica.
    
    Args:
        date_str: Fecha en formato ddmmyyyy
    """
    # Obtener la ruta del proyecto
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..'))
    
    # Cargar configuración para obtener rutas estandarizadas
    config_manager = get_config(project_root)
    config = config_manager.config
    paths = get_paths(config, custom_date=date_str)
    
    # Configurar rutas estandarizadas
    results_file = paths.get('image_api_results_json')
    cache_file = os.path.join(project_root, 'cache', 'image_hash_cache.json')
    
    # Hacer copia de seguridad del archivo de resultados si existe
    if os.path.exists(results_file):
        backup_file = f"{results_file}.backup"
        print(f"Haciendo copia de seguridad de resultados en: {backup_file}")
        shutil.copy2(results_file, backup_file)
        
        # Eliminar el archivo de resultados
        os.remove(results_file)
        print(f"Archivo de resultados eliminado para forzar reprocesamiento")
    
    # Opcional: hacer copia de seguridad del caché
    if os.path.exists(cache_file):
        backup_cache = f"{cache_file}.backup"
        print(f"Haciendo copia de seguridad de caché en: {backup_cache}")
        shutil.copy2(cache_file, backup_cache)
        
        # No eliminamos el cache completamente, solo lo modificaremos desde el código
    
    # Asegurarse que config tiene paths
    if 'paths' not in config:
        config['paths'] = paths
    
    # Forzar configuración para el procesamiento por lotes
    config['batch_size'] = 2  # Procesar 2 imágenes por lote (reducido de 3)
    config['short_pause_seconds'] = 60  # Pausa de 60 segundos entre lotes
    config['long_pause_seconds'] = 90   # Pausa más larga para imágenes complejas
    config['force_reprocess'] = True    # Flag especial para forzar reprocesamiento
    
    # Crear procesador con modo de forzado
    processor = EnhancedImageProcessor(config)
    
    # Vaciar caché de procesamiento (sin eliminar el archivo)
    processor.image_results_cache = {}
    
    print(f"Iniciando reprocesamiento forzado para {date_str}...")
    processor.process_pending_images([date_str])
    print(f"Reprocesamiento completado para {date_str}")

if __name__ == "__main__":
    # Obtener fecha del argumento o usar por defecto
    date_str = sys.argv[1] if len(sys.argv) > 1 else "15042025"
    
    # Confirmación para evitar errores
    confirm = input(f"¿Estás seguro de forzar el reprocesamiento para {date_str}? (s/n): ")
    if confirm.lower() in ('s', 'si', 'sí', 'y', 'yes'):
        force_reprocess_images(date_str)
    else:
        print("Operación cancelada.") 
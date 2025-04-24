#!/usr/bin/env python3
"""
Script simple para procesar imágenes con el procesador mejorado.
Incluye detección de duplicados basada en hash perceptual y contenido.
"""
import sys
import os
from process_pending_images import EnhancedImageProcessor
from lib.config_unified import get_config

# Ejecuta el procesador de imágenes para la fecha especificada
if __name__ == "__main__":
    # Obtener fecha del argumento o usar por defecto
    date_str = sys.argv[1] if len(sys.argv) > 1 else "16042025"
    
    # Inicializar procesador
    print(f"Procesando imágenes para fecha: {date_str}")
    
    # Cargar configuración
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..'))
    config_manager = get_config(project_root)
    
    # Configuración para deduplicación de imágenes
    config = config_manager.config
    if 'image_dedup' not in config:
        config['image_dedup'] = {
            'enable_deduplication': True,
            'similarity_threshold': 0.85,
            'hash_threshold': 5,
            'store_mapping': True
        }
    
    # Configurar procesamiento en lotes y pausas
    config['batch_size'] = 3  # Procesar 3 imágenes por lote
    config['short_pause_seconds'] = 60  # Pausa de 60 segundos entre lotes simples
    config['long_pause_seconds'] = 90   # Pausa de 90 segundos entre lotes complejos
    
    # Crear procesador
    processor = EnhancedImageProcessor(config)
    
    # Procesar imágenes
    processor.process_pending_images([date_str])
    
    print(f"Procesamiento de imágenes completado para fecha: {date_str}") 
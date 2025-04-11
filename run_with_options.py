#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para ejecutar el orquestador con opciones específicas desde la terminal.
Permite configurar el tamaño de lotes y pausas para el procesamiento adaptativo de imágenes.

Uso:
    python run_with_options.py DDMMYYYY [--batch-size N] [--pause-seconds N] [--prompt TIPO]

Ejemplos:
    python run_with_options.py 01042025
    python run_with_options.py 01042025 --batch-size 2 --pause-seconds 90
    python run_with_options.py 01042025 --prompt simple
"""

import os
import sys
import argparse
import yaml
from datetime import datetime

# Asegurarse de que el directorio 'codigo' esté en el path para imports
current_dir = os.path.dirname(os.path.abspath(__file__))
code_dir = os.path.join(current_dir, 'codigo')
if code_dir not in sys.path:
    sys.path.insert(0, code_dir)

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Ejecutar orquestador con opciones específicas.')
    
    parser.add_argument('date', 
                        help='Fecha en formato DDMMYYYY para procesar')
    
    parser.add_argument('--batch-size', type=int, default=3,
                        help='Tamaño máximo del lote de imágenes (1-3 recomendado)')
    
    parser.add_argument('--pause-seconds', type=int, default=60,
                        help='Segundos de pausa entre lotes de procesamiento')
    
    parser.add_argument('--prompt', choices=['simple', 'detallado', 'estructurado', 'anti-ruido'],
                        default='detallado',
                        help='Tipo de prompt para extracción de texto de imágenes')
    
    return parser.parse_args()

def update_config(batch_size, pause_seconds, prompt_key):
    """Actualiza el archivo config.yaml con los parámetros proporcionados."""
    config_file = os.path.join(current_dir, 'config.yaml')
    
    # Guardar configuración existente para restaurarla después
    config_backup = None
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            config_backup = f.read()
    
    # Escribir nueva configuración
    new_config = {
        'api': {
            'prompt_key': prompt_key,
            'batch_size': batch_size,
            'pause_seconds': pause_seconds
        }
    }
    
    with open(config_file, 'w', encoding='utf-8') as f:
        yaml.dump(new_config, f, default_flow_style=False)
    
    print(f"Configuración aplicada: prompt={prompt_key}, batch_size={batch_size}, pause={pause_seconds}s")
    
    return config_backup

def main():
    # Parsear argumentos
    args = parse_arguments()
    
    # Validar la fecha
    try:
        date_obj = datetime.strptime(args.date, '%d%m%Y')
        print(f"Procesando fecha: {date_obj.strftime('%d/%m/%Y')}")
    except ValueError:
        print(f"Error: Formato de fecha inválido '{args.date}'. Debe ser DDMMYYYY.")
        return 1
    
    # Validar tamaño de lote
    if args.batch_size < 1:
        print(f"Error: El tamaño del lote debe ser al menos 1.")
        return 1
    
    # Actualizar configuración
    config_backup = update_config(args.batch_size, args.pause_seconds, args.prompt)
    
    try:
        # Importar e iniciar el pipeline
        from codigo.main import run_pipeline
        
        print(f"Iniciando procesamiento para fecha {args.date}...")
        print("Esto puede tomar varios minutos. Por favor, espera...")
        
        start_time = datetime.now()
        
        # Ejecutar el orquestador
        run_pipeline(custom_date_str=args.date)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        print(f"✅ Procesamiento completado en {duration:.2f} segundos")
        
    except KeyboardInterrupt:
        print("\nProceso interrumpido por el usuario.")
        return 1
    except Exception as e:
        print(f"❌ Error ejecutando el orquestador: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        # Restaurar configuración original
        if config_backup:
            config_file = os.path.join(current_dir, 'config.yaml')
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_backup)
            print("Configuración original restaurada.")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# reprocesar.py - Script para forzar el reprocesamiento de datos ignorando el historial

import os
import sys
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
logger = logging.getLogger("reprocesar")

def reprocesar(fecha, prompt="detallado", batch_size=3, pause_seconds=60):
    """
    Ejecuta el orquestador para la fecha especificada, ignorando el historial
    para forzar el reprocesamiento de todas las URLs.
    
    Args:
        fecha (str): Fecha en formato DDMMYYYY
        prompt (str): Tipo de prompt (simple, detallado, estructurado, anti-ruido)
        batch_size (int): Tamaño máximo del lote de imágenes (1-3).
        pause_seconds (int): Segundos de pausa entre lotes.
    """
    print("=" * 80)
    print(f"REPROCESANDO DATOS PARA FECHA: {fecha}")
    print(f"Configuración: prompt={prompt}, batch_size={batch_size}, pause={pause_seconds}s")
    print("MODO: IGNORAR HISTORIAL - Procesará todas las URLs independientemente de si ya fueron procesadas")
    print("=" * 80)
    
    # Configurar el entorno para ignorar historial
    os.environ["IGNORAR_HISTORIAL"] = "True"
    
    # Configurar el archivo config.yaml
    config_file = os.path.join(project_root, "config.yaml")
    try:
        # Guardar configuración existente si existe
        config_backup = None
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config_backup = f.read()
        
        # Escribir nueva configuración
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(f"""api:
  prompt_key: "{prompt}"
  batch_size: {batch_size}
  pause_seconds: {pause_seconds}
""")
        
        print(f"Configuración aplicada: prompt={prompt}, batch_size={batch_size}, pause={pause_seconds}s")
        
        # Importar el módulo principal
        from codigo.main import run_pipeline
        
        # Ejecutar el pipeline
        print(f"Ejecutando pipeline para fecha: {fecha}")
        print("Esto puede tomar varios minutos. Por favor, espere...")
        
        start_time = datetime.now()
        run_pipeline(custom_date_str=fecha)
        end_time = datetime.now()
        
        duration = (end_time - start_time).total_seconds()
        print(f"✅ Procesamiento completado en {duration:.2f} segundos")
        
        # Restaurar configuración original si existía
        if config_backup:
            with open(config_file, 'w', encoding='utf-8') as f:
                f.write(config_backup)
                print("Configuración original restaurada")
    
    except Exception as e:
        print(f"❌ Error ejecutando el reprocesamiento: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Asegurarse de limpiar la variable de entorno
        if "IGNORAR_HISTORIAL" in os.environ:
            del os.environ["IGNORAR_HISTORIAL"]
            print("Variable de entorno IGNORAR_HISTORIAL eliminada")


# Comprobar si el script está siendo ejecutado directamente
if __name__ == "__main__":
    import argparse
    
    # Crear parser de argumentos
    parser = argparse.ArgumentParser(description='Reprocesar datos para una fecha específica ignorando el historial de URLs.')
    parser.add_argument('fecha', type=str, help='Fecha en formato DDMMYYYY (ej: 05032025)')
    parser.add_argument('--prompt', type=str, default='detallado', 
                        choices=['simple', 'detallado', 'estructurado', 'anti-ruido'],
                        help='Tipo de prompt para la API')
    parser.add_argument('--batch-size', type=int, default=3, help='Tamaño del lote de imágenes (1-5)')
    parser.add_argument('--pause', type=int, default=60, help='Pausa entre lotes en segundos (10-300)')
    
    # Parsear argumentos
    args = parser.parse_args()
    
    # Validar argumentos
    if not args.fecha.isdigit() or len(args.fecha) != 8:
        print("❌ Error: La fecha debe tener formato DDMMYYYY (ejemplo: 05032025)")
        sys.exit(1)
    
    if args.batch_size < 1 or args.batch_size > 5:
        print(f"⚠️ Advertencia: El batch_size {args.batch_size} está fuera del rango recomendado (1-5). Ajustando a 3.")
        args.batch_size = 3
    
    if args.pause < 10 or args.pause > 300:
        print(f"⚠️ Advertencia: La pausa {args.pause} está fuera del rango recomendado (10-300 seg). Ajustando a 60.")
        args.pause = 60
    
    # Ejecutar el reprocesamiento
    reprocesar(args.fecha, prompt=args.prompt, batch_size=args.batch_size, pause_seconds=args.pause)

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
run_image_optimization.py

Script simple para ejecutar la optimización de procesamiento de imágenes
con una fecha específica o para el directorio de imágenes más reciente.
"""

import os
import sys
import argparse
from datetime import datetime
import glob

# Directorio actual
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
project_root = os.path.abspath(os.path.join(parent_dir, '..'))

if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Importar el optimizador de imágenes
from optimize_image_processing import optimize_and_process_images

def find_latest_image_directory():
    """Busca el directorio de imágenes más reciente en la estructura de NewsAgent"""
    output_dir = os.path.join(project_root, 'output')
    
    # Verificar que existe el directorio output
    if not os.path.exists(output_dir):
        print(f"Error: Directorio de salida no encontrado: {output_dir}")
        return None
    
    # Buscar directorios de fecha en formato ddmmyyyy
    date_dirs = []
    for item in os.listdir(output_dir):
        dir_path = os.path.join(output_dir, item)
        if os.path.isdir(dir_path) and len(item) == 8 and item.isdigit():
            # Verificar que tiene subdirectorio de imágenes
            if os.path.exists(os.path.join(dir_path, 'images')):
                date_dirs.append(item)
    
    if not date_dirs:
        print("No se encontraron directorios de fecha con imágenes.")
        return None
    
    # Convertir a objetos datetime para comparar
    date_objects = []
    for date_str in date_dirs:
        try:
            date_obj = datetime.strptime(date_str, '%d%m%Y')
            date_objects.append((date_str, date_obj))
        except ValueError:
            continue
    
    if not date_objects:
        print("No se pudieron procesar las fechas de los directorios.")
        return None
    
    # Ordenar por fecha y obtener el más reciente
    date_objects.sort(key=lambda x: x[1], reverse=True)
    latest_date_str = date_objects[0][0]
    
    latest_images_dir = os.path.join(output_dir, latest_date_str, 'images')
    if os.path.exists(latest_images_dir):
        print(f"Directorio más reciente encontrado: {latest_images_dir} (fecha: {latest_date_str})")
        return latest_images_dir, latest_date_str
    else:
        print(f"Error: Directorio de imágenes no encontrado en {latest_date_str}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Ejecuta la optimización de procesamiento de imágenes")
    parser.add_argument("--date", help="Fecha en formato ddmmyyyy para procesar")
    parser.add_argument("--dir", help="Directorio de imágenes (opcional)")
    parser.add_argument("--workers", type=int, default=2, help="Número de trabajadores en paralelo")
    parser.add_argument("--pause", type=int, default=30, help="Segundos de pausa entre lotes")
    parser.add_argument("--tesseract", action="store_true", help="Usar Tesseract como fallback")
    
    args = parser.parse_args()
    
    # Determinar directorio y fecha
    if args.dir:
        # Usar directorio específico
        image_dir = args.dir
        date_str = args.date
    elif args.date:
        # Usar fecha específica
        date_str = args.date
        image_dir = os.path.join(project_root, 'output', date_str, 'images')
        if not os.path.exists(image_dir):
            print(f"Error: No se encontró directorio de imágenes para la fecha {date_str}")
            return 1
    else:
        # Buscar el directorio más reciente
        result = find_latest_image_directory()
        if not result:
            print("No se pudo encontrar un directorio de imágenes válido.")
            return 1
        image_dir, date_str = result
    
    # Verificar que hay imágenes en el directorio
    images = glob.glob(os.path.join(image_dir, "*.jpg")) + \
             glob.glob(os.path.join(image_dir, "*.jpeg")) + \
             glob.glob(os.path.join(image_dir, "*.png"))
    
    if not images:
        print(f"No se encontraron imágenes en {image_dir}")
        return 1
    
    print(f"Procesando {len(images)} imágenes en {image_dir}")
    print(f"Fecha de procesamiento: {date_str}")
    print(f"Trabajadores: {args.workers}, Pausa: {args.pause}s, Tesseract: {'Activado' if args.tesseract else 'Desactivado'}")
    
    # Ejecutar procesamiento optimizado
    results = optimize_and_process_images(
        image_dir=image_dir,
        output_dir=image_dir,
        date_str=date_str,
        max_workers=args.workers,
        pause_seconds=args.pause,
        use_tesseract=args.tesseract
    )
    
    # Verificar resultados
    successful = sum(1 for r in results if r.get("success", False))
    print(f"\nResultados del procesamiento:")
    print(f"- Total de imágenes: {len(images)}")
    print(f"- Extracciones exitosas: {successful} ({round(successful/len(images)*100, 1)}%)")
    print(f"- Resultados guardados en: {image_dir}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

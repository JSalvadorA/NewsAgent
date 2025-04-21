# codigo/manage_skipped_images.py
"""
Herramienta para gestionar imágenes que están marcadas como 'demasiado pesadas'
para procesar y por lo tanto se omiten permanentemente.
"""

import os
import sys
import json
import logging
from datetime import datetime

# Asegurarse de que el directorio 'lib' esté en el path para imports
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Configuración básica de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("skipped_images_manager")

# Importar módulos necesarios
from lib.config_manager import load_config, get_paths
from lib.image_processor import ImageProcessor

def list_skipped_images():
    """Lista todas las imágenes que están marcadas como permanentemente omitidas."""
    config = load_config(project_root)
    paths = get_paths(config)
    
    # Inicializar el procesador de imágenes
    full_config = {'paths': paths, **config}
    image_processor = ImageProcessor(full_config)
    
    # Obtener la lista de imágenes omitidas
    skipped_images = image_processor.list_permanently_skipped_images()
    
    if not skipped_images:
        print("\nNo hay imágenes marcadas como permanentemente omitidas.")
        return
    
    # Mostrar la lista de imágenes
    print(f"\nImágenes marcadas como permanentemente omitidas ({len(skipped_images)}):")
    print("-" * 80)
    
    for i, img in enumerate(skipped_images, 1):
        timestamp_str = "Desconocido"
        if "timestamp" in img and img["timestamp"]:
            try:
                timestamp = datetime.fromtimestamp(img["timestamp"])
                timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass
            
        print(f"{i}. {img['image_filename']}")
        print(f"   Razón: {img['reason']}")
        print(f"   Error: {img['error']}")
        print(f"   Marcada el: {timestamp_str}")
        print("-" * 80)
    
    return skipped_images

def clear_skipped_image(image_filename):
    """Elimina una imagen de la lista de permanentemente omitidas."""
    config = load_config(project_root)
    paths = get_paths(config)
    
    # Inicializar el procesador de imágenes
    full_config = {'paths': paths, **config}
    image_processor = ImageProcessor(full_config)
    
    # Intentar eliminar la imagen de la lista
    success = image_processor.clear_skipped_image(image_filename)
    
    if success:
        print(f"\nImagen '{image_filename}' eliminada de la lista de omitidas.")
        print("Se intentará procesar en la próxima ejecución del orquestador.")
    else:
        print(f"\nNo se pudo eliminar la imagen '{image_filename}' de la lista.")
    
    return success

def clear_all_skipped_images():
    """Elimina todas las imágenes de la lista de permanentemente omitidas."""
    skipped_images = list_skipped_images()
    
    if not skipped_images:
        return
    
    confirmation = input("\n¿Está seguro de que desea eliminar TODAS las imágenes de la lista? (s/n): ")
    if confirmation.lower() != 's':
        print("Operación cancelada.")
        return
    
    config = load_config(project_root)
    paths = get_paths(config)
    
    # Inicializar el procesador de imágenes
    full_config = {'paths': paths, **config}
    image_processor = ImageProcessor(full_config)
    
    success_count = 0
    for img in skipped_images:
        if image_processor.clear_skipped_image(img['image_filename']):
            success_count += 1
    
    print(f"\nSe eliminaron {success_count} de {len(skipped_images)} imágenes de la lista de omitidas.")
    print("Se intentará procesar todas en la próxima ejecución del orquestador.")

def show_menu():
    """Muestra el menú principal de la herramienta."""
    print("\n=== GESTIÓN DE IMÁGENES OMITIDAS PERMANENTEMENTE ===")
    print("1. Listar imágenes omitidas")
    print("2. Eliminar una imagen de la lista (para reprocesar)")
    print("3. Eliminar todas las imágenes de la lista")
    print("4. Salir")
    
    try:
        option = int(input("\nSeleccione una opción (1-4): "))
        return option
    except ValueError:
        print("Opción inválida. Por favor, ingrese un número del 1 al 4.")
        return 0

def main():
    """Función principal de la herramienta."""
    print("Herramienta para gestionar imágenes marcadas como 'demasiado pesadas'")
    
    while True:
        option = show_menu()
        
        if option == 1:
            list_skipped_images()
        
        elif option == 2:
            images = list_skipped_images()
            if images:
                try:
                    idx = int(input("\nIngrese el número de la imagen a eliminar: ")) - 1
                    if 0 <= idx < len(images):
                        clear_skipped_image(images[idx]['image_filename'])
                    else:
                        print("Número de imagen inválido.")
                except ValueError:
                    print("Entrada inválida. Debe ingresar un número.")
        
        elif option == 3:
            clear_all_skipped_images()
        
        elif option == 4:
            print("\nSaliendo del programa. ¡Hasta pronto!")
            break
        
        else:
            print("Opción inválida. Por favor, seleccione una opción del 1 al 4.")
        
        input("\nPresione Enter para continuar...")

if __name__ == "__main__":
    main()

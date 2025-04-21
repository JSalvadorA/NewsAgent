#!/usr/bin/env python3
# verificar_sistema.py - Script para verificar y solucionar problemas en el sistema

import os
import sys
import json
import shutil
from datetime import datetime

# Configurar el path del proyecto
project_root = "C:/Jerson/SUNASS/2025/4_April/gem/scr1403"
code_dir = os.path.join(project_root, "codigo")
if code_dir not in sys.path:
    sys.path.append(code_dir)

print("="*80)
print("VERIFICADOR DE SISTEMA - GEM NEWS AGGREGATOR")
print("="*80)

# Verificar estructura básica
print("\n1. Verificando estructura de directorios...\n")

required_dirs = [
    "input/Out",
    "input/In",
    "input/Images",
    "input/Images/downloads",
    "output",
    "output/markdown",
    "codigo/lib",
    "codigo/lib/history",
    "base",
    "cache"
]

for dir_path in required_dirs:
    full_path = os.path.join(project_root, dir_path)
    if os.path.exists(full_path):
        print(f"✅ Directorio {dir_path} existe")
    else:
        print(f"❌ Directorio {dir_path} NO existe - creando...")
        try:
            os.makedirs(full_path, exist_ok=True)
            print(f"   ✅ Directorio {dir_path} creado correctamente")
        except Exception as e:
            print(f"   ❌ Error creando directorio {dir_path}: {str(e)}")

# Verificar archivo de historial
print("\n2. Verificando archivo de historial...\n")

history_file = os.path.join(code_dir, "lib", "history", "processed_urls.json")

if os.path.exists(history_file):
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
            print(f"✅ Archivo de historial existe y contiene {len(history)} URLs")
            
            # Verificar si hay URLs repetidas
            unique_urls = set(history)
            if len(unique_urls) < len(history):
                print(f"⚠️ Se encontraron {len(history) - len(unique_urls)} URLs duplicadas en el historial")
                
                # Corregir automáticamente
                with open(history_file, 'w', encoding='utf-8') as f_out:
                    json.dump(sorted(list(unique_urls)), f_out, indent=2)
                print(f"   ✅ Historial corregido - ahora contiene {len(unique_urls)} URLs únicas")
    except Exception as e:
        print(f"❌ Error leyendo archivo de historial: {str(e)}")
else:
    print(f"⚠️ Archivo de historial no existe - creando uno vacío...")
    try:
        os.makedirs(os.path.dirname(history_file), exist_ok=True)
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump([], f)
        print(f"   ✅ Archivo de historial vacío creado correctamente")
    except Exception as e:
        print(f"   ❌ Error creando archivo de historial: {str(e)}")

# Verificar permisos de escritura en carpetas clave
print("\n3. Verificando permisos de escritura en carpetas clave...\n")

write_test_dirs = [
    "input/Out",
    "input/Images/downloads",
    "output",
    "cache"
]

for dir_path in write_test_dirs:
    full_path = os.path.join(project_root, dir_path)
    test_file = os.path.join(full_path, "test_write.tmp")
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        print(f"✅ Permiso de escritura en {dir_path} OK")
    except Exception as e:
        print(f"❌ No hay permisos de escritura en {dir_path}: {str(e)}")

# Verificar rutas en código
print("\n4. Verificando configuración de rutas...\n")

try:
    from codigo.lib.config_manager import load_config, get_paths
    
    config = load_config(project_root)
    paths = get_paths(config, "05032025")  # Usar la fecha problema como ejemplo
    
    # Comprobar ruta de textos scrapeados
    scraped_texts_path = paths.get("scraped_texts_json")
    if scraped_texts_path:
        print(f"✅ Ruta de textos scrapeados configurada: {scraped_texts_path}")
        scraped_dir = os.path.dirname(scraped_texts_path)
        if not os.path.exists(scraped_dir):
            print(f"⚠️ Directorio para textos scrapeados no existe: {scraped_dir}")
            try:
                os.makedirs(scraped_dir, exist_ok=True)
                print(f"   ✅ Directorio {scraped_dir} creado correctamente")
            except Exception as e:
                print(f"   ❌ Error creando directorio {scraped_dir}: {str(e)}")
    else:
        print("❌ No se encontró configuración para 'scraped_texts_json'")
    
    # Comprobar ruta de imágenes
    image_dir = paths.get("image_download_dir")
    if image_dir:
        print(f"✅ Ruta de imágenes configurada: {image_dir}")
        if not os.path.exists(image_dir):
            print(f"⚠️ Directorio para imágenes no existe: {image_dir}")
            try:
                os.makedirs(image_dir, exist_ok=True)
                print(f"   ✅ Directorio {image_dir} creado correctamente")
            except Exception as e:
                print(f"   ❌ Error creando directorio {image_dir}: {str(e)}")
    else:
        print("❌ No se encontró configuración para 'image_download_dir'")
    
except Exception as e:
    print(f"❌ Error verificando configuración de rutas: {str(e)}")

# Verificar módulos necesarios
print("\n5. Verificando módulos Python necesarios...\n")

required_modules = [
    "requests", "beautifulsoup4", "selenium", "pillow", "pyyaml", 
    "google.generativeai", "python-dotenv", "webdriver_manager"
]

for module in required_modules:
    try:
        __import__(module.split('.')[0])
        print(f"✅ Módulo {module} instalado")
    except ImportError:
        print(f"❌ Módulo {module} NO instalado")

# Verificar si hay datos en las carpetas de salida para la fecha específica
print("\n6. Verificando datos de salida para fecha 05032025...\n")

date_str = "05032025"

# Verificar textos extraídos HTML
scraped_texts_path = os.path.join(project_root, "input", "Out", f"scraped_texts_{date_str}.json")
if os.path.exists(scraped_texts_path):
    try:
        with open(scraped_texts_path, 'r', encoding='utf-8') as f:
            scraped_data = json.load(f)
            print(f"✅ Archivo de textos HTML encontrado con {len(scraped_data)} elementos")
    except Exception as e:
        print(f"⚠️ Archivo de textos HTML existe pero no se puede leer: {str(e)}")
else:
    print(f"⚠️ No se encontró archivo de textos HTML para la fecha {date_str}")

# Verificar imágenes descargadas
images_dir = os.path.join(project_root, "input", "Images", "downloads", date_str)
if os.path.exists(images_dir):
    image_files = [f for f in os.listdir(images_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
    print(f"✅ Directorio de imágenes encontrado con {len(image_files)} imágenes")
else:
    print(f"⚠️ No se encontró directorio de imágenes para la fecha {date_str}")

# Verificar archivo consolidado
consolidated_path = os.path.join(project_root, "output", f"consolidated_{date_str}.json")
if os.path.exists(consolidated_path):
    try:
        with open(consolidated_path, 'r', encoding='utf-8') as f:
            consolidated_data = json.load(f)
            print(f"✅ Archivo consolidado encontrado y válido")
    except Exception as e:
        print(f"⚠️ Archivo consolidado existe pero no se puede leer: {str(e)}")
else:
    print(f"⚠️ No se encontró archivo consolidado para la fecha {date_str}")

# Crear backup de archivos importantes
print("\n7. Creando backup de archivos importantes...\n")

backup_dir = os.path.join(project_root, "backup_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
try:
    os.makedirs(backup_dir, exist_ok=True)
    print(f"✅ Directorio de backup creado: {backup_dir}")
    
    # Archivos a respaldar
    files_to_backup = [
        os.path.join(code_dir, "lib", "history", "processed_urls.json"),
        os.path.join(project_root, "config.yaml")
    ]
    
    for file_path in files_to_backup:
        if os.path.exists(file_path):
            try:
                backup_path = os.path.join(backup_dir, os.path.basename(file_path))
                shutil.copy2(file_path, backup_path)
                print(f"✅ Backup de {os.path.basename(file_path)} creado")
            except Exception as e:
                print(f"❌ Error creando backup de {os.path.basename(file_path)}: {str(e)}")
        else:
            print(f"⚠️ Archivo {os.path.basename(file_path)} no existe, no se puede hacer backup")
    
except Exception as e:
    print(f"❌ Error creando directorio de backup: {str(e)}")

print("\n" + "="*80)
print("VERIFICACIÓN COMPLETA")
print("="*80)
print("\nPara reprocesar la fecha 05032025 y generar nuevamente todos los archivos, ejecute:")
print("python reprocesar.py 05032025")
print("\nEsto ignorará el historial y procesará todas las URLs, independientemente de si ya fueron procesadas antes.")

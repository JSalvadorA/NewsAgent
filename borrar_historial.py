#!/usr/bin/env python3
# borrar_historial.py - Script para borrar el historial de URLs procesadas de manera segura

import os
import sys
import json
import shutil
from datetime import datetime

# Configurar logging básico
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("borrar_historial")

# Definir la ruta del proyecto y del historial
project_root = "C:/Jerson/SUNASS/2025/4_April/gem/scr1403"
history_dir = os.path.join(project_root, "codigo", "lib", "history")
history_file = os.path.join(history_dir, "processed_urls.json")


def crear_respaldo(archivo_origen):
    """
    Crea un respaldo del archivo de historial con una marca de tiempo.
    
    Args:
        archivo_origen (str): Ruta del archivo a respaldar
    Returns:
        str: Ruta del archivo de respaldo creado
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(project_root, "backup_historial")
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(backup_dir, f"processed_urls_backup_{timestamp}.json")
    
    try:
        shutil.copy2(archivo_origen, backup_file)
        logger.info(f"✅ Respaldo creado en: {backup_file}")
        return backup_file
    except Exception as e:
        logger.error(f"❌ Error al crear respaldo: {str(e)}")
        return None

def borrar_historial():
    """
    Borra el historial de URLs procesadas, creando un respaldo primero.
    """
    logger.info("=" * 80)
    logger.info("BORRANDO HISTORIAL DE URLs PROCESADAS")
    logger.info("=" * 80)
    
    if not os.path.exists(history_file):
        logger.warning(f"⚠️ Archivo de historial no encontrado en: {history_file}")
        logger.info("Creando un archivo de historial vacío...")
        try:
            os.makedirs(history_dir, exist_ok=True)
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
            logger.info(f"✅ Archivo de historial vacío creado en: {history_file}")
        except Exception as e:
            logger.error(f"❌ Error al crear archivo de historial: {str(e)}")
        return
    
    # Crear respaldo del historial actual
    logger.info("Creando respaldo del historial actual...")
    backup_path = crear_respaldo(history_file)
    if not backup_path:
        logger.error("❌ No se pudo crear el respaldo. Abortando operación por seguridad.")
        return
    
    # Leer el historial actual para mostrar estadísticas
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            historial = json.load(f)
            logger.info(f"Historial actual contiene {len(historial)} URLs procesadas.")
    except Exception as e:
        logger.warning(f"⚠️ No se pudo leer el historial: {str(e)}. Continuando con el borrado.")
    
    # Vaciar el historial
    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump([], f)
        logger.info(f"✅ Historial de URLs procesadas borrado con éxito.")
        logger.info(f"El archivo {history_file} ahora está vacío.")
    except Exception as e:
        logger.error(f"❌ Error al borrar el historial: {str(e)}")
        logger.info(f"El respaldo está disponible en: {backup_path}")
    
    logger.info("=" * 80)
    logger.info("Operación completada. Puede ejecutar el pipeline para procesar todas las URLs nuevamente.")
    logger.info("=" * 80)

if __name__ == "__main__":
    borrar_historial() 
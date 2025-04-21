#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para generar archivos JSON de URLs no procesadas.
Utiliza la función get_unprocessed_urls de text_similarity.py para
identificar qué URLs no han sido procesadas en los archivos consolidados.
"""

import os
import sys
import json
import glob
import logging
from datetime import datetime

# Asegurarse de que el directorio 'lib' esté en el path para imports
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'codigo', 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("url_processor")

# Importar la función necesaria
try:
    from text_similarity import get_unprocessed_urls
    logger.info("Función get_unprocessed_urls importada correctamente")
except ImportError as e:
    logger.error(f"Error importando get_unprocessed_urls: {e}")
    sys.exit(1)

def load_links_from_pdf(pdf_date):
    """
    Carga los enlaces extraídos de un PDF para una fecha específica.
    
    Args:
        pdf_date (str): Fecha en formato ddmmyyyy
    
    Returns:
        list: Lista de enlaces o lista vacía si no se encuentra el archivo
    """
    # Lista de posibles ubicaciones para los archivos de enlaces
    possible_locations = [
        os.path.join(current_dir, 'input', 'Out', f'links_extracted_{pdf_date}.json'),
        os.path.join(current_dir, 'input', 'Links', f'links_extracted_{pdf_date}.json'),
        os.path.join(current_dir, 'input', f'links_extracted_{pdf_date}.json'),
        # Archivos _unprocessed.json para imágenes
        os.path.join(current_dir, 'input', 'Images', f'image_links_{pdf_date}_unprocessed.json'),
        # Archivos _unprocessed.json para redes sociales
        os.path.join(current_dir, 'input', 'Social', f'social_links_{pdf_date}_unprocessed.json')
    ]
    
    # Buscar en todas las ubicaciones posibles
    for location in possible_locations:
        if os.path.exists(location):
            try:
                with open(location, 'r', encoding='utf-8') as f:
                    links = json.load(f)
                logger.info(f"Enlaces cargados desde: {location}")
                # Verificar formato (lista vs diccionario)
                if isinstance(links, dict):
                    # Convertir diccionario a lista de enlaces
                    formatted_links = []
                    for url, metadata in links.items():
                        formatted_links.append({
                            "URL": url,
                            "Context": metadata.get("context", ""),
                            "Page": 1  # Página por defecto
                        })
                    return formatted_links
                return links
            except Exception as e:
                logger.error(f"Error cargando enlaces desde {location}: {e}")
    
    # Si no se encuentra ningún archivo, buscar en subdirectorios
    for dir_path in ['input', 'input/Out', 'input/Images', 'input/Social']:
        path = os.path.join(current_dir, dir_path)
        if os.path.exists(path):
            for root, dirs, files in os.walk(path):
                for file in files:
                    if (f'links_{pdf_date}' in file or f'image_links_{pdf_date}' in file or 
                        f'social_links_{pdf_date}' in file) and file.endswith('.json'):
                        try:
                            file_path = os.path.join(root, file)
                            with open(file_path, 'r', encoding='utf-8') as f:
                                links = json.load(f)
                            logger.info(f"Enlaces cargados desde: {file_path}")
                            # Verificar formato
                            if isinstance(links, dict):
                                # Convertir diccionario a lista de enlaces
                                formatted_links = []
                                for url, metadata in links.items():
                                    formatted_links.append({
                                        "URL": url,
                                        "Context": metadata.get("context", ""),
                                        "Page": 1  # Página por defecto
                                    })
                                return formatted_links
                            return links
                        except Exception as e:
                            logger.error(f"Error cargando enlaces desde {file_path}: {e}")
    
    # Si seguimos sin encontrar enlaces, intentar generar enlaces ficticios desde el archivo consolidado
    consolidated_file = os.path.join(current_dir, 'output', f'consolidated_{pdf_date}.json')
    if os.path.exists(consolidated_file):
        try:
            with open(consolidated_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extraer URLs de las diferentes secciones
            all_urls = []
            
            # HTML pages
            html_pages = data.get('extracted_content', {}).get('html_pages', {})
            for url in html_pages.keys():
                all_urls.append({"URL": url, "Page": 1, "Context": "Extraído de HTML"})
            
            # Images
            image_texts = data.get('extracted_content', {}).get('image_texts', [])
            for img in image_texts:
                if "url" in img:
                    all_urls.append({"URL": img["url"], "Page": 1, "Context": "Extraído de imágenes"})
            
            # Facebook
            facebook_results = data.get('extracted_content', {}).get('facebook_results', {})
            for url in facebook_results.keys():
                all_urls.append({"URL": url, "Page": 1, "Context": "Extraído de Facebook"})
            
            # Audio
            audio_metadata = data.get('extracted_content', {}).get('audio_metadata', {})
            for url in audio_metadata.keys():
                all_urls.append({"URL": url, "Page": 1, "Context": "Extraído de audio"})
            
            if all_urls:
                logger.info(f"Generados {len(all_urls)} enlaces a partir del archivo consolidado")
                return all_urls
        except Exception as e:
            logger.error(f"Error generando enlaces desde el archivo consolidado: {e}")
    
    # Si no se encuentra ningún archivo, devolver lista vacía
    logger.warning(f"No se encontraron enlaces para la fecha {pdf_date}")
    return []

def load_consolidated_data(pdf_date):
    """
    Carga los datos consolidados para una fecha específica.
    
    Args:
        pdf_date (str): Fecha en formato ddmmyyyy
    
    Returns:
        dict: Datos consolidados o diccionario vacío si no se encuentra el archivo
    """
    consolidated_file = os.path.join(current_dir, 'output', f'consolidated_{pdf_date}.json')
    
    if not os.path.exists(consolidated_file):
        logger.warning(f"No se encontró archivo consolidado para la fecha {pdf_date}")
        return {}
    
    try:
        with open(consolidated_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"Datos consolidados cargados desde: {consolidated_file}")
        return data
    except Exception as e:
        logger.error(f"Error cargando datos consolidados: {e}")
        return {}

def process_date(pdf_date):
    """
    Procesa una fecha específica, generando el archivo de URLs no procesadas.
    
    Args:
        pdf_date (str): Fecha en formato ddmmyyyy
    
    Returns:
        bool: True si se procesó correctamente, False en caso contrario
    """
    logger.info(f"Procesando fecha: {pdf_date}")
    
    # Cargar enlaces del PDF
    all_links = load_links_from_pdf(pdf_date)
    if not all_links:
        logger.warning(f"No hay enlaces para procesar para la fecha {pdf_date}")
        return False
    
    # Cargar datos consolidados
    consolidated_data = load_consolidated_data(pdf_date)
    if not consolidated_data:
        logger.warning(f"No hay datos consolidados para la fecha {pdf_date}")
        # Intentar cargar el contenido extraído si existe
        extracted_content = {}
        try:
            # Buscar datos procesados en los directorios correspondientes
            html_file = os.path.join(current_dir, 'input', 'Out', f'scraped_texts_{pdf_date}.json')
            image_file = os.path.join(current_dir, 'input', 'Images', 'downloads', pdf_date, 'texto_imagenes_api.json')
            
            if os.path.exists(html_file):
                with open(html_file, 'r', encoding='utf-8') as f:
                    extracted_content['html'] = json.load(f)
            
            if os.path.exists(image_file):
                with open(image_file, 'r', encoding='utf-8') as f:
                    extracted_content['images_api'] = json.load(f)
                    
            if extracted_content:
                logger.info(f"Se cargaron datos parciales para la fecha {pdf_date}")
            else:
                logger.warning(f"No se encontraron datos parciales para la fecha {pdf_date}")
                return False
        except Exception as e:
            logger.error(f"Error cargando datos parciales: {e}")
            return False
    else:
        # Extraer el contenido relevante del archivo consolidado
        extracted_content = consolidated_data.get('extracted_content', {})
    
    # Verificar formato del contenido extraído
    if 'html_pages' in extracted_content:
        extracted_content['html'] = extracted_content.pop('html_pages')
    if 'image_texts' in extracted_content:
        extracted_content['images_api'] = extracted_content.pop('image_texts')
    
    # Obtener URLs no procesadas
    unprocessed_urls = get_unprocessed_urls(all_links, extracted_content)
    
    if not unprocessed_urls:
        logger.info(f"No hay URLs no procesadas para la fecha {pdf_date}")
        return True
    
    # Guardar URLs no procesadas
    output_file = os.path.join(current_dir, 'output', f'unprocessed_urls_{pdf_date}.json')
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(unprocessed_urls, f, indent=2, ensure_ascii=False)
        
        logger.info(f"URLs no procesadas guardadas en: {output_file}")
        return True
    except Exception as e:
        logger.error(f"Error guardando URLs no procesadas: {e}")
        return False

def main():
    """Función principal del script"""
    # Obtener todas las fechas disponibles
    consolidated_files = glob.glob(os.path.join(current_dir, 'output', 'consolidated_*.json'))
    dates = []
    
    for file in consolidated_files:
        try:
            filename = os.path.basename(file)
            date_part = filename.replace('consolidated_', '').replace('.json', '')
            if len(date_part) == 8 and date_part.isdigit():
                dates.append(date_part)
        except Exception as e:
            logger.warning(f"Error extrayendo fecha de {file}: {e}")
    
    if not dates:
        logger.warning("No se encontraron fechas para procesar")
        return
    
    # Ordenar fechas
    dates.sort()
    logger.info(f"Se procesarán {len(dates)} fechas: {dates}")
    
    # Procesar cada fecha
    processed_count = 0
    for date in dates:
        if process_date(date):
            processed_count += 1
    
    logger.info(f"Proceso completado. Se procesaron {processed_count} de {len(dates)} fechas")

if __name__ == "__main__":
    main() 
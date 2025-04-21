#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para convertir archivos JSON de URLs no procesadas a formato Markdown.
También genera un reporte de las URLs no procesadas por categoría.
"""

import os
import json
import glob
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("json_to_markdown")

def convert_json_to_markdown(json_file, output_dir):
    """
    Convierte un archivo JSON a formato Markdown
    
    Args:
        json_file (str): Ruta al archivo JSON
        output_dir (str): Directorio de salida para los archivos Markdown
    
    Returns:
        str: Ruta al archivo Markdown generado o None si hay error
    """
    try:
        # Asegurarse que el directorio de salida existe
        os.makedirs(output_dir, exist_ok=True)
        
        # Obtener nombre base del archivo
        base_name = os.path.basename(json_file)
        name_without_ext = os.path.splitext(base_name)[0]
        
        # Definir archivo de salida
        output_file = os.path.join(output_dir, f"{name_without_ext}.md")
        
        # Leer el archivo JSON
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Inicio del contenido Markdown
        md_content = [
            f"# URLs no procesadas - {name_without_ext}",
            f"Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]
        
        # Procesar cada categoría de URLs
        for category, urls in data.items():
            md_content.append(f"## Categoría: {category.upper()}")
            md_content.append(f"Total: {len(urls)} URLs")
            md_content.append("")
            md_content.append("| # | URL | Página | Contexto |")
            md_content.append("|---|-----|--------|----------|")
            
            for i, url_data in enumerate(urls, 1):
                url = url_data.get("URL", "N/A")
                page = url_data.get("Page", "N/A")
                context = url_data.get("Context", "N/A")
                # Limitar longitud del contexto para mejorar formato de tabla
                if len(context) > 50:
                    context = context[:47] + "..."
                
                md_content.append(f"| {i} | [{url}]({url}) | {page} | {context} |")
            
            md_content.append("")  # Línea en blanco entre categorías
        
        # Escribir contenido a archivo Markdown
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(md_content))
        
        logger.info(f"Archivo convertido: {output_file}")
        return output_file
    
    except Exception as e:
        logger.error(f"Error convirtiendo {json_file}: {e}")
        return None

def generate_summary_report(processed_files, output_dir):
    """
    Genera un informe resumen de todos los archivos procesados
    
    Args:
        processed_files (list): Lista de archivos procesados
        output_dir (str): Directorio donde guardar el informe
    """
    if not processed_files:
        logger.warning("No hay archivos procesados para generar informe resumen")
        return
    
    summary_file = os.path.join(output_dir, "resumen_urls_no_procesadas.md")
    
    md_content = [
        "# Resumen de URLs no procesadas",
        f"Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Archivos procesados",
        ""
    ]
    
    for file_path in processed_files:
        base_name = os.path.basename(file_path)
        md_content.append(f"- [{base_name}]({base_name})")
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_content))
    
    logger.info(f"Informe resumen generado: {summary_file}")

def main():
    """Función principal del script"""
    # Definir directorios
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ""))
    output_dir = os.path.join(project_root, "output", "markdown")
    
    logger.info(f"Buscando archivos JSON de URLs no procesadas en {project_root}")
    
    # Buscar archivos de URLs no procesadas
    json_files = glob.glob(os.path.join(project_root, "output", "unprocessed_urls_*.json"))
    
    if not json_files:
        logger.warning("No se encontraron archivos JSON de URLs no procesadas")
        # Crear archivo vacío si no hay archivos
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "sin_urls_no_procesadas.md"), 'w', encoding='utf-8') as f:
            f.write("# Sin URLs no procesadas\n\nNo se encontraron archivos JSON de URLs no procesadas.")
        return
    
    logger.info(f"Encontrados {len(json_files)} archivos JSON de URLs no procesadas")
    
    # Convertir cada archivo
    processed_files = []
    for json_file in json_files:
        output_file = convert_json_to_markdown(json_file, output_dir)
        if output_file:
            processed_files.append(output_file)
    
    # Generar informe resumen
    generate_summary_report(processed_files, output_dir)
    
    logger.info(f"Proceso completado. Archivos convertidos: {len(processed_files)}")

if __name__ == "__main__":
    main() 
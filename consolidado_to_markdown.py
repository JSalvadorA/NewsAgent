#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Script para convertir archivos consolidated_*.json a formato Markdown.
Los archivos consolidados contienen toda la información extraída de PDFs, imágenes, HTML, etc.
Este script genera reportes en Markdown legibles y estructurados.
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
logger = logging.getLogger("consolidado_to_markdown")

def convert_consolidado_to_markdown(json_file, output_dir):
    """
    Convierte un archivo consolidado JSON a formato Markdown
    
    Args:
        json_file (str): Ruta al archivo JSON consolidado
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
            f"# Reporte Consolidado - {name_without_ext}",
            f"Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ]
        
        # === Sección Metadata ===
        metadata = data.get("metadata", {})
        md_content.append("## 1. Metadatos")
        md_content.append("")
        
        # PDF de origen y fecha de procesamiento
        md_content.append(f"- **PDF de origen**: {metadata.get('source_pdf', 'N/A')}")
        md_content.append(f"- **Fecha de procesamiento**: {metadata.get('processing_date', 'N/A')}")
        
        # Lista de PDFs disponibles
        available_pdfs = metadata.get("available_pdfs", [])
        if available_pdfs:
            md_content.append(f"- **PDFs disponibles**: {len(available_pdfs)}")
            md_content.append("")
            md_content.append("| # | Archivo PDF |")
            md_content.append("|---|------------|")
            for i, pdf in enumerate(available_pdfs, 1):
                md_content.append(f"| {i} | {pdf} |")
        else:
            md_content.append("- **PDFs disponibles**: Ninguno")
        
        md_content.append("")
        
        # Estadísticas
        stats = metadata.get("stats_summary", {})
        if stats:
            md_content.append("### 1.1 Estadísticas de procesamiento")
            md_content.append("")
            md_content.append("| Métrica | Valor |")
            md_content.append("|--------|-------|")
            
            # Mostrar conteos principales
            md_content.append(f"| URLs totales | {stats.get('total_urls_in_pdf', 0)} |")
            md_content.append(f"| URLs procesadas | {stats.get('new_urls_processed_count', 0)} |")
            
            # Tiempos de procesamiento
            timings = stats.get("timings_seconds", {})
            if timings:
                md_content.append("| **Tiempos de procesamiento (segundos)** | |")
                for key, value in timings.items():
                    md_content.append(f"| - {key.replace('_', ' ').title()} | {value} |")
            
            md_content.append("")
        
        # === Sección Contenido Extraído ===
        extracted_content = data.get("extracted_content", {})
        md_content.append("## 2. Contenido Extraído")
        md_content.append("")
        
        # === 2.1 Textos de PDF ===
        pdf_paragraphs = extracted_content.get("pdf_paragraphs", {})
        
        if pdf_paragraphs:
            md_content.append("### 2.1 Textos extraídos de PDFs")
            md_content.append("")
            md_content.append(f"Total de secciones: {len(pdf_paragraphs)}")
            md_content.append("")
            
            for section, paragraphs in pdf_paragraphs.items():
                md_content.append(f"#### {section}")
                md_content.append("")
                
                if isinstance(paragraphs, list):
                    for p in paragraphs:
                        if isinstance(p, dict) and "text" in p:
                            md_content.append(f"- {p['text']}")
                        else:
                            md_content.append(f"- {p}")
                else:
                    md_content.append(f"- {paragraphs}")
                
                md_content.append("")
        else:
            md_content.append("### 2.1 Textos extraídos de PDFs")
            md_content.append("")
            md_content.append("No se encontraron textos de PDF.")
            md_content.append("")
            
        # === 2.2 Contenido HTML ===
        html_pages = extracted_content.get("html_pages", {})
        
        if html_pages:
            md_content.append("### 2.2 Contenido de páginas web")
            md_content.append("")
            md_content.append(f"Total de páginas HTML: {len(html_pages)}")
            md_content.append("")
            md_content.append("| # | URL | Título |")
            md_content.append("|---|-----|--------|")
            
            for i, (url, content) in enumerate(html_pages.items(), 1):
                title = content.get("title", "Sin título") if isinstance(content, dict) else "N/A"
                # Limitar longitud del título
                if len(title) > 50:
                    title = title[:47] + "..."
                md_content.append(f"| {i} | [{url}]({url}) | {title} |")
            
            md_content.append("")
        else:
            md_content.append("### 2.2 Contenido de páginas web")
            md_content.append("")
            md_content.append("No se encontró contenido HTML.")
            md_content.append("")
            
        # === 2.3 Textos de imágenes ===
        image_texts = extracted_content.get("image_texts", [])
        
        if image_texts:
            md_content.append("### 2.3 Textos extraídos de imágenes")
            md_content.append("")
            md_content.append(f"Total de imágenes procesadas: {len(image_texts)}")
            md_content.append("")
            md_content.append("| # | Archivo | URL |")
            md_content.append("|---|---------|-----|")
            
            for i, img in enumerate(image_texts, 1):
                if isinstance(img, dict):
                    filename = img.get("filename", "N/A")
                    url = img.get("url", "")
                    url_display = f"[Ver imagen]({url})" if url else "N/A"
                    md_content.append(f"| {i} | {filename} | {url_display} |")
            
            md_content.append("")
        else:
            md_content.append("### 2.3 Textos extraídos de imágenes")
            md_content.append("")
            md_content.append("No se encontraron textos de imágenes.")
            md_content.append("")
            
        # === 2.4 Resultados de Facebook ===
        facebook_results = extracted_content.get("facebook_results", {})
        
        if facebook_results:
            md_content.append("### 2.4 Contenido de redes sociales")
            md_content.append("")
            md_content.append(f"Total de publicaciones de redes sociales: {len(facebook_results)}")
            md_content.append("")
            md_content.append("| # | URL | Tipo |")
            md_content.append("|---|-----|------|")
            
            for i, (url, content) in enumerate(facebook_results.items(), 1):
                content_type = content.get("type", "Desconocido") if isinstance(content, dict) else "N/A"
                md_content.append(f"| {i} | [{url}]({url}) | {content_type} |")
            
            md_content.append("")
        else:
            md_content.append("### 2.4 Contenido de redes sociales")
            md_content.append("")
            md_content.append("No se encontró contenido de redes sociales.")
            md_content.append("")
            
        # === 2.5 Transcripciones de Audio ===
        audio_transcriptions = extracted_content.get("audio_transcriptions", [])
        
        if audio_transcriptions:
            md_content.append("### 2.5 Transcripciones de audio")
            md_content.append("")
            md_content.append(f"Total de archivos de audio transcritos: {len(audio_transcriptions)}")
            md_content.append("")
            
            for i, audio in enumerate(audio_transcriptions, 1):
                if isinstance(audio, dict):
                    filename = audio.get("filename", f"Audio {i}")
                    url = audio.get("url", "")
                    transcript = audio.get("transcript", "Sin transcripción")
                    
                    md_content.append(f"#### {filename}")
                    if url:
                        md_content.append(f"URL: [{url}]({url})")
                    md_content.append("")
                    md_content.append("**Transcripción:**")
                    md_content.append("")
                    md_content.append(transcript)
                    md_content.append("")
            
        else:
            md_content.append("### 2.5 Transcripciones de audio")
            md_content.append("")
            md_content.append("No se encontraron transcripciones de audio.")
            md_content.append("")
        
        # Escribir contenido a archivo Markdown
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(md_content))
        
        logger.info(f"Archivo consolidado convertido: {output_file}")
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
    
    summary_file = os.path.join(output_dir, "resumen_consolidados.md")
    
    md_content = [
        "# Resumen de Reportes Consolidados",
        f"Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Reportes disponibles",
        ""
    ]
    
    # Ordenar los archivos por fecha (suponiendo que el nombre tiene formato consolidated_DDMMYYYY.md)
    processed_files.sort(key=lambda f: os.path.basename(f).replace("consolidated_", "").replace(".md", ""))
    
    for file_path in processed_files:
        base_name = os.path.basename(file_path)
        date_part = base_name.replace("consolidated_", "").replace(".md", "")
        
        # Intentar formatear la fecha para mejor visualización
        try:
            if len(date_part) == 8:  # Formato DDMMYYYY
                formatted_date = f"{date_part[:2]}/{date_part[2:4]}/{date_part[4:]}"
            else:
                formatted_date = date_part
        except:
            formatted_date = date_part
            
        md_content.append(f"- [{formatted_date}]({base_name})")
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_content))
    
    logger.info(f"Informe resumen de consolidados generado: {summary_file}")

def combine_unprocessed_urls():
    """
    Combina todos los archivos unprocessed_urls_*.json en un solo archivo
    
    Returns:
        str: Ruta al archivo JSON combinado o None si hay error
    """
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ""))
        json_files = glob.glob(os.path.join(project_root, "output", "unprocessed_urls_*.json"))
        
        if not json_files:
            logger.warning("No se encontraron archivos JSON de URLs no procesadas para combinar")
            return None
            
        combined_data = {}
        
        for json_file in json_files:
            # Extraer fecha del nombre del archivo
            base_name = os.path.basename(json_file)
            date_part = base_name.replace("unprocessed_urls_", "").replace(".json", "")
            
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    file_data = json.load(f)
                
                if file_data:
                    combined_data[date_part] = file_data
            except Exception as e:
                logger.error(f"Error al leer el archivo {json_file}: {e}")
        
        if not combined_data:
            logger.warning("No se encontraron datos válidos para combinar")
            return None
            
        output_file = os.path.join(project_root, "output", "all_unprocessed_urls.json")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(combined_data, f, indent=2, ensure_ascii=False)
            
        logger.info(f"Archivo combinado de URLs no procesadas generado: {output_file}")
        return output_file
            
    except Exception as e:
        logger.error(f"Error combinando archivos de URLs no procesadas: {e}")
        return None

def main():
    """Función principal del script"""
    # Definir directorios
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ""))
    output_dir = os.path.join(project_root, "output", "markdown")
    
    # Crear directorio de salida si no existe
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"Buscando archivos consolidated_*.json en {project_root}")
    
    # Buscar archivos consolidated
    json_files = glob.glob(os.path.join(project_root, "output", "consolidated_*.json"))
    
    if not json_files:
        logger.warning("No se encontraron archivos consolidated_*.json")
        # Crear archivo vacío si no hay archivos
        with open(os.path.join(output_dir, "sin_consolidados.md"), 'w', encoding='utf-8') as f:
            f.write("# Sin archivos consolidados\n\nNo se encontraron archivos consolidated_*.json.")
        return
    
    logger.info(f"Encontrados {len(json_files)} archivos consolidated_*.json")
    
    # Convertir cada archivo
    processed_files = []
    for json_file in json_files:
        output_file = convert_consolidado_to_markdown(json_file, output_dir)
        if output_file:
            processed_files.append(output_file)
    
    # Generar informe resumen
    generate_summary_report(processed_files, output_dir)
    
    # Combinar archivos de URLs no procesadas
    combine_unprocessed_urls()
    
    logger.info(f"Proceso completado. Archivos convertidos: {len(processed_files)}")

if __name__ == "__main__":
    main() 
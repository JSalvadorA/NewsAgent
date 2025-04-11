def filter_pdf_sections(pdf_text_data):
    """
    Filtra secciones no deseadas del texto extraído del PDF.
    Elimina información de correo Gmail, encabezados estándar CONTENIDO_INICIAL y URLs de Google Mail.
    
    Args:
        pdf_text_data (dict): Datos extraídos del PDF con secciones y metadatos
        
    Returns:
        dict: Datos filtrados sin las secciones no deseadas
    """
    filtered_data = pdf_text_data.copy()  # Copiar para no modificar el original
    
    # 1. Remover sección CONTENIDO_INICIAL completa
    if "CONTENIDO_INICIAL" in filtered_data:
        logger.info(f"Eliminando sección CONTENIDO_INICIAL con {len(filtered_data['CONTENIDO_INICIAL'])} entradas")
        del filtered_data["CONTENIDO_INICIAL"]
    
    # 2. Remover metadatos de Gmail en otras secciones
    sections_to_process = [key for key in filtered_data.keys()]
    
    for section_key in sections_to_process:
        if not isinstance(filtered_data[section_key], list):
            continue
            
        # Filtrar entradas en cada sección
        filtered_entries = []
        for entry in filtered_data[section_key]:
            # Saltarse entradas que contengan URLs de Gmail
            url = entry.get("metadata", {}).get("url", "")
            text = entry.get("text", "")
            
            # Criterios para excluir
            is_gmail = "Gmail" in text or "gmail.com" in url.lower() or "Google Mail" in text
            is_mail_link = url.startswith("https://mail.google.com")
            is_empty_url = not url and ("RV:" in text or "FW:" in text or "Fwd:" in text)
            
            # Si no cumple ningún criterio de exclusión, mantener la entrada
            if not (is_gmail or is_mail_link or is_empty_url):
                filtered_entries.append(entry)
        
        # Actualizar sección con entradas filtradas
        if len(filtered_entries) < len(filtered_data[section_key]):
            logger.info(f"Sección {section_key}: Filtradas {len(filtered_data[section_key]) - len(filtered_entries)} entradas")
        filtered_data[section_key] = filtered_entries
    
    return filtered_data# codigo/lib/text_extractor.py
"""
Módulo para la extracción de texto estructurado de PDFs.
Se encarga de identificar cabeceras y párrafos, y organizar la información en un formato JSON estructurado.
"""

import fitz  # PyMuPDF
import logging
import os
import json
import re
from datetime import datetime
import unicodedata

logger = logging.getLogger(__name__)

# Lista de cabeceras a identificar en el PDF
KNOWN_HEADERS = [
    "NORMAS LEGALES",
    "NOTICIAS – SUNASS",
    "NOTICIAS - SUNASS",  # Variante con guion normal en lugar de guion largo
    "ALERTAS",
    "SECTOR",
    "MEDIOAMBIENTE",
    "MEDIO AMBIENTE",  # Variante con espacio
    "POLÍTICA / ECONOMÍA",
    "POLÍTICA/ECONOMÍA",  # Variante sin espacios
    "POLITICA / ECONOMIA",  # Variante sin acentos
]

# Expresiones regulares para detectar posibles cabeceras
HEADER_PATTERNS = [
    r'^[A-Z\s\-–\/]{5,}$',  # Solo mayúsculas, espacios, guiones y /
    r'^[A-ZÁÉÍÓÚÑ\s\-–\/]{5,}$',  # Mayúsculas con acentos
]

def normalize_text(text):
    """
    Normaliza el texto eliminando caracteres especiales y normalizando espacios.
    """
    if not text:
        return ""
    
    # Normalizar Unicode (NFD y luego eliminar los diacríticos)
    text = unicodedata.normalize('NFD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    
    # Reemplazar múltiples espacios por uno solo
    text = re.sub(r'\s+', ' ', text)
    
    # Eliminar espacios al inicio y final
    return text.strip()

def is_likely_header(text):
    """
    Determina si un texto es probablemente una cabecera basándose en patrones.
    """
    text = text.strip()
    if not text:
        return False
    
    # Verificar si coincide con una cabecera conocida
    normalized_text = normalize_text(text).upper()
    for header in KNOWN_HEADERS:
        if normalized_text == normalize_text(header).upper():
            return True
    
    # Verificar patrones de cabecera
    for pattern in HEADER_PATTERNS:
        if re.match(pattern, text):
            # Descartar líneas demasiado largas
            if len(text) > 50:
                return False
            # Descartar líneas con caracteres típicos de URLs o correos
            if any(char in text for char in '@:?=&%'):
                return False
            # Al menos 5 caracteres de longitud
            if len(text) < 5:
                return False
            return True
    
    return False

def find_urls_in_text(text):
    """
    Busca URLs en un texto y las devuelve como una lista.
    """
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    return url_pattern.findall(text)

def contains_email(text):
    """
    Verifica si el texto contiene un correo electrónico.
    """
    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    return bool(email_pattern.search(text))

def clean_paragraph(text):
    """
    Limpia un párrafo de texto eliminando caracteres problemáticos y normalizando espacios.
    """
    if not text:
        return ""
    
    # Eliminar caracteres de control y normalizar espacios
    text = re.sub(r'[\x00-\x1F\x7F]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def generate_brief_description(text, max_words=5):
    """
    Genera una breve descripción del texto usando las primeras palabras,
    asegurándose de que no contenga URLs.
    """
    if not text:
        return ""
    
    # Eliminar URLs del texto para la descripción
    url_pattern = re.compile(
        r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
    )
    text_without_urls = url_pattern.sub('', text)
    
    words = text_without_urls.split()
    if len(words) <= max_words:
        return text_without_urls.strip()
    
    return " ".join(words[:max_words]) + "..."

def extract_text_by_sections(pdf_path):
    """
    Extrae texto del PDF organizándolo por secciones (cabeceras) y párrafos.
    Excluye párrafos que contienen correos electrónicos.
    
    Returns:
        dict: Diccionario con la estructura de secciones y párrafos
    """
    if not os.path.exists(pdf_path):
        logger.error(f"Archivo PDF no encontrado: {pdf_path}")
        return {}
    
    if not pdf_path.lower().endswith(".pdf"):
        logger.error(f"El archivo no parece ser un PDF: {pdf_path}")
        return {}
    
    # Estructura para almacenar el texto extraído
    sections = {}
    current_section = "CONTENIDO_INICIAL"  # Sección por defecto
    sections[current_section] = []
    
    try:
        doc = fitz.open(pdf_path)
        logger.info(f"Abriendo PDF para extracción de texto: {pdf_path} ({doc.page_count} páginas)")
        
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            
            # Extraer bloques de texto (párrafos)
            blocks = page.get_text("blocks")
            
            for block in blocks:
                # En PyMuPDF los bloques son tuplas (x0, y0, x1, y1, text, block_no, block_type)
                text = block[4].strip()
                if not text:
                    continue
                
                # Verificar si es una cabecera
                if is_likely_header(text):
                    normalized_header = normalize_text(text).upper()
                    # Verificar si coincide con una cabecera conocida
                    for known_header in KNOWN_HEADERS:
                        if normalized_header == normalize_text(known_header).upper():
                            current_section = known_header
                            break
                    else:
                        # Si no coincide exactamente, usar el texto como sección
                        current_section = text
                    
                    # Inicializar la sección si no existe
                    if current_section not in sections:
                        sections[current_section] = []
                    
                    logger.debug(f"Cabecera detectada: '{current_section}' en página {page_num + 1}")
                else:
                    # Es un párrafo normal
                    # Limpiar el texto
                    clean_text = clean_paragraph(text)
                    if not clean_text:
                        continue
                    
                    # Verificar si el párrafo contiene correos electrónicos
                    if contains_email(clean_text):
                        logger.debug(f"Párrafo descartado por contener correo electrónico: {clean_text[:50]}...")
                        continue
                    
                    # Buscar URLs en el texto
                    urls = find_urls_in_text(clean_text)
                    
                    # Crear el objeto de párrafo
                    paragraph = {
                        "metadata": {
                            "description": generate_brief_description(clean_text),
                            "url": urls[0] if urls else ""
                        },
                        "text": clean_text,
                        "page": page_num + 1
                    }
                    
                    # Añadir a la sección actual
                    sections[current_section].append(paragraph)
        
        # Cerrar el documento
        doc.close()
        
        # Eliminar secciones vacías
        sections = {k: v for k, v in sections.items() if v}
        
        return sections
    
    except Exception as e:
        logger.error(f"Error al extraer texto del PDF '{pdf_path}': {e}", exc_info=True)
        return {}

def extract_and_save_pdf_text(pdf_path, date_str=None):
    """
    Extrae el texto del PDF y lo guarda en un archivo JSON.
    
    Args:
        pdf_path (str): Ruta al archivo PDF
        date_str (str, optional): Fecha en formato ddmmyyyy. Si no se proporciona, se usa la fecha actual.
    
    Returns:
        tuple: (éxito, ruta del archivo JSON generado o None si hubo error)
    """
    if not date_str:
        date_str = datetime.today().strftime('%d%m%Y')
    
    try:
        # Extraer texto por secciones
        sections = extract_text_by_sections(pdf_path)
        
        if not sections:
            logger.warning(f"No se pudo extraer texto del PDF o el PDF está vacío: {pdf_path}")
            return False, None
        
        # Aplicar filtro para eliminar secciones no deseadas
        filtered_sections = filter_pdf_sections(sections)
        
        # Crear directorio de salida
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # Usar la carpeta "input/Out" en lugar de "output"
        output_dir = os.path.join(project_root, 'input', 'Out', 'scraped_pdf_' + date_str)
        os.makedirs(output_dir, exist_ok=True)
        
        # Nombre del archivo de salida
        output_file = os.path.join(output_dir, f"pdf_text_{date_str}.json")
        
        # Guardar resultado en JSON
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(filtered_sections, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Texto del PDF extraído y guardado en: {output_file}")
        logger.info(f"Se encontraron {len(filtered_sections)} secciones con un total de {sum(len(v) for v in filtered_sections.values())} párrafos")
        logger.info(f"Se filtraron {sum(len(v) for v in sections.values()) - sum(len(v) for v in filtered_sections.values())} párrafos no deseados")
        
        return True, output_file
    
    except Exception as e:
        logger.error(f"Error al procesar y guardar texto del PDF: {e}", exc_info=True)
        return False, None

# Si se ejecuta directamente, procesar un archivo PDF de prueba
if __name__ == "__main__":
    import sys
    
    # Configuración de logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    if len(sys.argv) > 1:
        test_pdf = sys.argv[1]
        date_str = sys.argv[2] if len(sys.argv) > 2 else None
        
        success, output_path = extract_and_save_pdf_text(test_pdf, date_str)
        if success:
            print(f"Texto extraído exitosamente y guardado en: {output_path}")
        else:
            print(f"Error al extraer texto del PDF: {test_pdf}")
    else:
        print("Uso: python text_extractor.py <ruta_del_pdf> [fecha_ddmmyyyy]")
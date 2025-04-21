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
import sys
from typing import Dict, List, Tuple, Optional, Union, Any

# Importar las utilidades para verificar dependencias
from .utils import check_dependency, check_tesseract_installed, get_tesseract_languages

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

def filter_pdf_sections(pdf_text_data):
    """
    Filtra secciones no deseadas del texto extraído del PDF.
    Elimina información de correo Gmail, encabezados estándar CONTENIDO_INICIAL,
    URLs de Google Mail, archivos adjuntos, imágenes y disclaimers.
    
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
    
    # Patrones para filtrar entradas no deseadas
    exclusion_patterns = [
        # Patrones de correo
        r'RV:\s', r'FW:\s', r'Fwd:\s', r'Gmail', r'google\.com',
        # Patrones de archivos adjuntos
        r'\d+\s+archivos?\s+adjuntos?', r'image\d+\.\w{3}\s+\d+K',
        # Patrones de imágenes
        r'^image\d+\.\w{3}', 
        # Patrones de notas de confidencialidad
        r'Pensemos en el medio ambiente', r'NOTA DE CONFIDENCIALIDAD', 
        r'antes de imprimir este documento'
    ]
    
    for section_key in sections_to_process:
        if not isinstance(filtered_data[section_key], list):
            continue
            
        # Filtrar entradas en cada sección
        filtered_entries = []
        for entry in filtered_data[section_key]:
            # Extraer URL y texto para la evaluación
            url = entry.get("metadata", {}).get("url", "")
            text = entry.get("text", "")
            
            # Verificar si contiene alguno de los patrones a excluir
            should_exclude = False
            
            # Criterios para excluir basados en URL
            is_mail_link = url.startswith("https://mail.google.com")
            is_empty_url = not url
            
            # Si es una URL de correo, excluir directamente
            if is_mail_link:
                should_exclude = True
            # Si no tiene URL, verificar patrones en el texto
            elif is_empty_url:
                # Verificar cada patrón de exclusión
                for pattern in exclusion_patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        should_exclude = True
                        break
                        
                # Casos específicos adicionales basados en ejemplos exactos
                if text.strip() in [
                    "3 archivos adjuntos", 
                    "image013.jpg 1K", 
                    "image001.jpg 17K"
                ]:
                    should_exclude = True
            
            # Si no se debe excluir, mantener la entrada
            if not should_exclude:
                filtered_entries.append(entry)
        
        # Actualizar sección con entradas filtradas
        if len(filtered_entries) < len(filtered_data[section_key]):
            logger.info(f"Sección {section_key}: Filtradas {len(filtered_data[section_key]) - len(filtered_entries)} entradas")
        filtered_data[section_key] = filtered_entries
    
    return filtered_data

def extract_text_by_sections(pdf_path):
    """
    Extrae texto del PDF organizándolo por secciones (cabeceras) y párrafos.
    Incluye OCR para PDFs escaneados que no tienen texto extraíble.
    
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
        
        # Variables para detectar si es un PDF escaneado
        total_text_length = 0
        needs_ocr = False
        
        # Primera pasada: Intentar extraer texto normal
        for page_num in range(min(doc.page_count, 3)):  # Revisar primeras 3 páginas
            page = doc.load_page(page_num)
            page_text = page.get_text("text")
            total_text_length += len(page_text)
        
        # Si no hay suficiente texto en las primeras páginas, probablemente es un PDF escaneado
        if total_text_length < 500:  # Umbral arbitrario para detectar PDF escaneado
            logger.warning(f"PDF {pdf_path} parece ser un documento escaneado con poco texto (encontrados {total_text_length} caracteres). Intentando OCR...")
            needs_ocr = True
        
        # Procesar con OCR si es necesario
        if needs_ocr:
            return extract_text_with_ocr(pdf_path)
        
        # Extracción normal si no necesita OCR
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
        # Intentar con OCR como fallback si falla la extracción normal
        logger.info(f"Intentando OCR como fallback para {pdf_path}")
        try:
            return extract_text_with_ocr(pdf_path)
        except Exception as ocr_e:
            logger.error(f"Error también en OCR para '{pdf_path}': {ocr_e}", exc_info=True)
            return {}

def extract_text_with_ocr(pdf_path: str, output_path: Optional[str] = None, 
                         dpi: int = 300, language: str = 'spa', 
                         use_gpu: bool = False) -> Dict[str, Any]:
    """
    Extrae texto de un PDF escaneado utilizando OCR con Tesseract.
    
    Args:
        pdf_path: Ruta al archivo PDF
        output_path: Ruta donde se guardará el JSON con el texto extraído, si no se proporciona no se guarda
        dpi: Resolución en DPI para la conversión de PDF a imagen
        language: Código de idioma para Tesseract OCR
        use_gpu: Si se debe usar GPU para el procesamiento OCR (si está disponible)
        
    Returns:
        Dict con el texto extraído organizado por secciones
    """
    result = {
        "success": False,
        "sections": [],
        "error": None,
        "metadata": {
            "filename": os.path.basename(pdf_path),
            "pages_processed": 0,
            "extraction_date": datetime.datetime.now().isoformat(),
            "extraction_method": "ocr"
        }
    }
    
    # Verificar que el archivo existe
    if not os.path.exists(pdf_path):
        error_msg = f"El archivo PDF no existe: {pdf_path}"
        logger.error(error_msg)
        result["error"] = error_msg
        return result
    
    # Verificar dependencias necesarias
    missing_deps = []
    
    # Verificar PyMuPDF
    if not check_dependency("fitz", "PyMuPDF"):
        missing_deps.append("PyMuPDF")
    
    # Verificar pytesseract
    if not check_dependency("pytesseract"):
        missing_deps.append("pytesseract")
    
    # Verificar Pillow
    if not check_dependency("PIL", "Pillow"):
        missing_deps.append("Pillow")
    
    # Si faltan dependencias, reportar el error
    if missing_deps:
        dep_str = ", ".join(missing_deps)
        error_msg = f"Faltan dependencias para OCR: {dep_str}. Instálelas con: pip install {' '.join(missing_deps)}"
        logger.error(error_msg)
        result["error"] = error_msg
        return result
    
    # Verificar que Tesseract está instalado
    tesseract_installed, tesseract_info = check_tesseract_installed()
    if not tesseract_installed:
        error_msg = f"Tesseract OCR no está instalado. {tesseract_info}"
        logger.error(error_msg)
        result["error"] = error_msg
        return result
    else:
        logger.info(f"Usando Tesseract OCR: {tesseract_info}")
        
    # Verificar idioma disponible
    available_languages = get_tesseract_languages()
    if language not in available_languages:
        lang_warning = f"El idioma '{language}' no está disponible en Tesseract. Idiomas disponibles: {', '.join(available_languages[:5])}"
        if 'eng' in available_languages:
            language = 'eng'
            lang_warning += f". Usando 'eng' como alternativa."
        elif available_languages:
            language = available_languages[0]
            lang_warning += f". Usando '{language}' como alternativa."
        logger.warning(lang_warning)
    
    # Ahora que se han verificado todas las dependencias, importamos los módulos
    import fitz
    import pytesseract
    from PIL import Image
    import io
    
    # Configurar pytesseract
    if tesseract_installed and tesseract_info != 'tesseract':
        pytesseract.pytesseract.tesseract_cmd = tesseract_info
    
    # Configurar opciones de OCR
    config = f"--oem 1 --psm 3"
    if use_gpu:
        # Tesseract 5+ soporta GPU con OpenCL
        config += " --opencl"
    
    try:
        # Abrir el documento PDF
        doc = fitz.open(pdf_path)
        num_pages = doc.page_count
        
        if num_pages == 0:
            error_msg = f"El PDF no contiene páginas: {pdf_path}"
            logger.error(error_msg)
            result["error"] = error_msg
            return result
        
        logger.info(f"Procesando PDF con OCR: {pdf_path} ({num_pages} páginas)")
        
        # Estructura para organizar el texto extraído
        extracted_sections = {}
        current_section = "CONTENIDO_PRINCIPAL"
        extracted_sections[current_section] = []
        
        # Procesar cada página
        for page_num in range(num_pages):
            try:
                logger.debug(f"Procesando página {page_num + 1}/{num_pages} con OCR...")
                page = doc.load_page(page_num)
                
                # Convertir página a imagen con la resolución especificada
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72))
                img_bytes = pix.tobytes("png")
                
                # Abrir la imagen con PIL
                img = Image.open(io.BytesIO(img_bytes))
                
                # Ejecutar OCR
                config_with_lang = f"{config} -l {language}"
                page_text = pytesseract.image_to_string(img, config=config_with_lang)
                
                if not page_text.strip():
                    logger.warning(f"No se pudo extraer texto de la página {page_num + 1}")
                    continue
                
                # Procesar el texto extraído
                lines = page_text.split('\n')
                current_paragraph = ""
                
                for line in lines:
                    line = line.strip()
                    
                    # Saltar líneas vacías
                    if not line:
                        if current_paragraph:
                            clean_text = clean_paragraph(current_paragraph)
                            if clean_text and len(clean_text) > 10 and not contains_email(clean_text):
                                # Añadir párrafo a la sección actual
                                urls = find_urls_in_text(clean_text)
                                paragraph = {
                                    "metadata": {
                                        "description": generate_brief_description(clean_text),
                                        "url": urls[0] if urls else ""
                                    },
                                    "text": clean_text,
                                    "page": page_num + 1
                                }
                                extracted_sections[current_section].append(paragraph)
                            current_paragraph = ""
                        continue
                    
                    # Comprobar si es una cabecera
                    if is_likely_header(line):
                        # Guardar el párrafo actual antes de cambiar de sección
                        if current_paragraph:
                            clean_text = clean_paragraph(current_paragraph)
                            if clean_text and len(clean_text) > 10 and not contains_email(clean_text):
                                urls = find_urls_in_text(clean_text)
                                paragraph = {
                                    "metadata": {
                                        "description": generate_brief_description(clean_text),
                                        "url": urls[0] if urls else ""
                                    },
                                    "text": clean_text,
                                    "page": page_num + 1
                                }
                                extracted_sections[current_section].append(paragraph)
                            current_paragraph = ""
                        
                        # Crear nueva sección
                        normalized_header = normalize_text(line).upper()
                        
                        # Verificar si coincide con una cabecera conocida
                        for known_header in KNOWN_HEADERS:
                            if normalized_header == normalize_text(known_header).upper():
                                current_section = known_header
                                break
                        else:
                            # Si no coincide con ninguna cabecera conocida, usar el texto como sección
                            current_section = line
                        
                        # Inicializar sección si no existe
                        if current_section not in extracted_sections:
                            extracted_sections[current_section] = []
                            logger.debug(f"Nueva sección detectada: '{current_section}'")
                    else:
                        # Añadir línea al párrafo actual
                        if current_paragraph:
                            current_paragraph += " " + line
                        else:
                            current_paragraph = line
                
                # Procesar último párrafo de la página
                if current_paragraph:
                    clean_text = clean_paragraph(current_paragraph)
                    if clean_text and len(clean_text) > 10 and not contains_email(clean_text):
                        urls = find_urls_in_text(clean_text)
                        paragraph = {
                            "metadata": {
                                "description": generate_brief_description(clean_text),
                                "url": urls[0] if urls else ""
                            },
                            "text": clean_text,
                            "page": page_num + 1
                        }
                        extracted_sections[current_section].append(paragraph)
                
                # Actualizar metadatos
                result["metadata"]["pages_processed"] += 1
                
            except Exception as e:
                logger.error(f"Error procesando OCR en página {page_num + 1}: {str(e)}")
        
        # Cerrar el documento PDF
        doc.close()
        
        # Eliminar secciones vacías
        extracted_sections = {k: v for k, v in extracted_sections.items() if v}
        
        # Actualizar resultado
        result["sections"] = extracted_sections
        result["success"] = True
        
        # Filtrar secciones no deseadas
        filtered_sections = filter_pdf_sections(extracted_sections)
        result["sections"] = filtered_sections
        
        # Guardar en archivo si se ha proporcionado una ruta
        if output_path:
            try:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                logger.info(f"Texto extraído guardado en: {output_path}")
            except Exception as e:
                logger.error(f"Error al guardar resultado OCR: {str(e)}")
        
        logger.info(f"OCR completado: {len(result['sections'])} secciones, {sum(len(v) for v in result['sections'].values())} párrafos")
        return result
        
    except Exception as e:
        error_msg = f"Error en extracción OCR: {str(e)}"
        logger.error(error_msg, exc_info=True)
        result["error"] = error_msg
        return result

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
        date_str = datetime.datetime.today().strftime('%d%m%Y')
    
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
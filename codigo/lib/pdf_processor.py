# codigo/lib/pdf_processor.py
import fitz  # PyMuPDF
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

def get_text_around_link(page, link_dict):
    """
    Intenta extraer texto alrededor del rectángulo del enlace para dar contexto.
    """
    try:
        if 'from' in link_dict: # PyMuPDF >= 1.19 usa 'from' para el Rect
             rect = link_dict['from']
        elif 'rect' in link_dict: # Versiones anteriores
            rect = link_dict['rect']
        else:
            return "" # No hay información de ubicación

        # Amplía un poco el área para capturar contexto
        # Ajusta estos valores según necesites más o menos contexto
        h_margin = 30 # Margen horizontal
        v_margin = 10 # Margen vertical
        expanded_rect = fitz.Rect(rect.x0 - h_margin, rect.y0 - v_margin,
                                  rect.x1 + h_margin, rect.y1 + v_margin)

        # Asegurarse de que el rectángulo expandido no se salga de la página
        page_rect = page.rect
        expanded_rect.intersect(page_rect)

        if expanded_rect.is_empty or expanded_rect.width <= 0 or expanded_rect.height <= 0:
             return "" # Área inválida

        text = page.get_text("text", clip=expanded_rect, sort=True).strip()
        # Limpieza simple: reemplazar saltos de línea múltiples por espacio
        text = ' '.join(text.split())
        return text

    except Exception as e:
        logger.warning(f"Error extrayendo contexto para enlace {link_dict.get('uri', 'N/A')}: {e}")
        return ""

def extract_links_from_pdf(pdf_path):
    """
    Abre un archivo PDF y extrae todos los enlaces URI (http, https, ftp),
    junto con su página, ubicación (rectángulo) y texto de contexto.
    Excluye explícitamente los enlaces 'mailto:'.
    """
    links = []
    if not os.path.exists(pdf_path):
        logger.error(f"Archivo PDF no encontrado: {pdf_path}")
        return links
    if not pdf_path.lower().endswith(".pdf"):
         logger.error(f"El archivo no parece ser un PDF: {pdf_path}")
         return links

    try:
        doc = fitz.open(pdf_path)
        logger.info(f"Abriendo PDF: {pdf_path} ({doc.page_count} páginas)")
    except Exception as e:
        # Captura errores específicos de fitz si es posible, o genéricos
        logger.error(f"Error al abrir o procesar el archivo PDF '{pdf_path}': {e}")
        return links # Retorna lista vacía si no se puede abrir

    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        page_links = page.get_links() # Obtiene todos los tipos de enlaces

        for link_dict in page_links:
            # Verificar que sea un enlace URI y no un mailto
            if link_dict.get('kind') == fitz.LINK_URI:
                uri = link_dict.get('uri')
                if uri and not uri.lower().startswith('mailto:'):
                     context = get_text_around_link(page, link_dict)
                     rect = link_dict.get('from') # PyMuPDF >= 1.19
                     if rect:
                         rect_tuple = (rect.x0, rect.y0, rect.x1, rect.y1)
                     else: # Compatibilidad con versiones anteriores
                         rect_compat = link_dict.get('rect')
                         rect_tuple = tuple(rect_compat) if rect_compat else None

                     links.append({
                        "Page": page_num + 1,
                        "URL": uri,
                        "Rect": rect_tuple, # Guardar como tupla simple
                        "Context": context
                    })
            # Podrías añadir lógica aquí para otros tipos de enlaces si fuera necesario
            # elif link_dict.get('kind') == fitz.LINK_GOTO:
            #     # Enlace interno
            #     pass

    try:
        doc.close()
    except Exception as e:
         logger.warning(f"Error menor al cerrar el PDF '{pdf_path}': {e}")


    logger.info(f"Se extrajeron {len(links)} enlaces URI (no mailto) de {os.path.basename(pdf_path)}.")
    return links

def has_text_layer(pdf_path, min_char_per_page=10, sample_pages=3):
    """
    Verifica si un PDF tiene una capa de texto accesible.
    
    Args:
        pdf_path (str): Ruta al archivo PDF.
        min_char_per_page (int): Número mínimo de caracteres por página para considerar que tiene texto.
        sample_pages (int): Número de páginas a analizar como muestra.
    
    Returns:
        bool: True si el PDF tiene una capa de texto accesible, False en caso contrario.
    """
    logger.info(f"Verificando si el PDF {pdf_path} tiene capa de texto accesible")
    
    if not os.path.exists(pdf_path):
        logger.warning(f"El archivo PDF {pdf_path} no existe")
        return False
    
    try:
        doc = fitz.open(pdf_path)
        
        # Determinar cuántas páginas verificar
        total_pages = len(doc)
        pages_to_check = min(total_pages, sample_pages)
        
        if total_pages == 0:
            logger.warning(f"El PDF {pdf_path} no tiene páginas")
            doc.close()
            return False
        
        # Calcular el total de caracteres en las primeras páginas
        total_chars = 0
        for i in range(pages_to_check):
            page = doc[i]
            text = page.get_text()
            total_chars += len(text)
        
        avg_chars = total_chars / pages_to_check
        logger.info(f"PDF {pdf_path}: {avg_chars:.2f} caracteres promedio por página (en {pages_to_check} páginas)")
        
        doc.close()
        return avg_chars >= min_char_per_page
    
    except Exception as e:
        logger.error(f"Error al verificar capa de texto en {pdf_path}: {e}", exc_info=True)
        return False

def extract_text_from_page(doc, page_num, extraction_method="text"):
    """
    Extrae texto de una página específica utilizando el método indicado.
    
    Args:
        doc: Documento PDF abierto (fitz.Document)
        page_num: Número de página (0-indexed)
        extraction_method: Método de extracción ("text", "dict", "blocks", etc.)
        
    Returns:
        str: Texto extraído de la página
    """
    try:
        page = doc.load_page(page_num)
        text = page.get_text(extraction_method)
        return text
    except Exception as e:
        logger.warning(f"Error extrayendo texto de página {page_num+1}: {e}")
        return ""

def extract_text_parallel(pdf_path, max_workers=4, extraction_method="text"):
    """
    Extrae texto de un PDF utilizando procesamiento paralelo para mayor velocidad.
    
    Args:
        pdf_path: Ruta al archivo PDF
        max_workers: Número máximo de hilos para el procesamiento paralelo
        extraction_method: Método de extracción para PyMuPDF
        
    Returns:
        list: Lista de textos extraídos, uno por página
    """
    if not os.path.exists(pdf_path):
        logger.error(f"Archivo PDF no encontrado: {pdf_path}")
        return []
        
    try:
        doc = fitz.open(pdf_path)
        all_pages_text = [""] * doc.page_count  # Inicializar lista de resultados
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Crear tareas para cada página
            future_to_page = {
                executor.submit(extract_text_from_page, doc, page_num, extraction_method): page_num
                for page_num in range(doc.page_count)
            }
            
            # Procesar resultados a medida que se completan
            for future in as_completed(future_to_page):
                page_num = future_to_page[future]
                try:
                    text = future.result()
                    all_pages_text[page_num] = text
                except Exception as e:
                    logger.error(f"Error en extracción paralela para página {page_num+1}: {e}")
        
        doc.close()
        logger.info(f"Extracción paralela completada para {pdf_path}: {len(all_pages_text)} páginas procesadas")
        return all_pages_text
        
    except Exception as e:
        logger.error(f"Error en extracción paralela de '{pdf_path}': {e}")
        return []

def optimize_pdf(input_path, output_path=None, compression_level=2):
    """
    Optimiza un PDF reduciendo su tamaño.
    
    Args:
        input_path: Ruta al PDF original
        output_path: Ruta donde guardar el PDF optimizado (si es None, se usa un nombre temporal)
        compression_level: Nivel de compresión (0-3, donde 3 es máxima compresión)
        
    Returns:
        str: Ruta al PDF optimizado
    """
    if not os.path.exists(input_path):
        logger.error(f"Archivo PDF no encontrado: {input_path}")
        return None
        
    if output_path is None:
        # Crear nombre para archivo optimizado
        base_name = os.path.basename(input_path)
        dir_name = os.path.dirname(input_path)
        name, ext = os.path.splitext(base_name)
        output_path = os.path.join(dir_name, f"{name}_optimized{ext}")
    
    try:
        # Abrir documento
        doc = fitz.open(input_path)
        
        # Configurar opciones de optimización según el nivel de compresión
        compression_options = {
            0: {"garbage": 0, "clean": 0, "deflate": 0, "compress": False},
            1: {"garbage": 1, "clean": 1, "deflate": 1, "compress": True},
            2: {"garbage": 3, "clean": 1, "deflate": 1, "compress": True},
            3: {"garbage": 4, "clean": 1, "deflate": 1, "compress": True}
        }
        
        options = compression_options.get(compression_level, compression_options[2])
        
        # Aplicar optimización
        doc.save(
            output_path,
            garbage=options["garbage"],
            clean=options["clean"],
            deflate=options["deflate"],
            compress=options["compress"]
        )
        
        # Calcular reducción de tamaño
        original_size = os.path.getsize(input_path)
        new_size = os.path.getsize(output_path)
        reduction_percent = ((original_size - new_size) / original_size) * 100
        
        logger.info(f"PDF optimizado: {input_path} → {output_path}")
        logger.info(f"Tamaño reducido de {original_size/1024:.1f}KB a {new_size/1024:.1f}KB "
                  f"({reduction_percent:.1f}% de reducción)")
        
        return output_path
        
    except Exception as e:
        logger.error(f"Error optimizando PDF '{input_path}': {e}")
        return None
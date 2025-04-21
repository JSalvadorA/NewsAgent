"""
Módulo para detectar similitud entre textos y consolidar contenido único.
Proporciona funciones para comparar el contenido de textos extraídos de PDFs
y determinar si son duplicados o similares.
"""

import logging
import unicodedata
import re
from difflib import SequenceMatcher
import hashlib
from collections import defaultdict

logger = logging.getLogger(__name__)

def normalize_text(text):
    """
    Normaliza un texto para comparaciones:
    - Elimina caracteres especiales y diacríticos
    - Convierte a minúsculas
    - Elimina espacios duplicados
    - Elimina símbolos y puntuación
    
    Args:
        text (str): Texto a normalizar
        
    Returns:
        str: Texto normalizado
    """
    if not text:
        return ""
    
    # Convertir a minúsculas
    text = text.lower()
    
    # Normalizar Unicode (NFD y eliminar diacríticos)
    text = unicodedata.normalize('NFD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    
    # Eliminar símbolos, puntuación y números
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\d+', ' ', text)
    
    # Reemplazar múltiples espacios por uno solo
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def calculate_text_hash(text):
    """
    Calcula un hash del texto normalizado para comparaciones rápidas.
    
    Args:
        text (str): Texto para el cual calcular el hash
        
    Returns:
        str: Hash del texto
    """
    normalized = normalize_text(text)
    if not normalized:
        return ""
    
    return hashlib.md5(normalized.encode('utf-8')).hexdigest()

def calculate_similarity_ratio(text1, text2):
    """
    Calcula la relación de similitud entre dos textos usando SequenceMatcher.
    
    Args:
        text1 (str): Primer texto
        text2 (str): Segundo texto
        
    Returns:
        float: Valor entre 0 y 1 que representa la similitud (1 = idénticos)
    """
    if not text1 or not text2:
        return 0.0
    
    # Normalizar para comparación
    text1_norm = normalize_text(text1)
    text2_norm = normalize_text(text2)
    
    # Si los textos son muy largos, usar una técnica de muestreo
    if len(text1_norm) > 5000 or len(text2_norm) > 5000:
        # Verificar si los primeros 1000 caracteres son similares
        prefix_match = SequenceMatcher(None, text1_norm[:1000], text2_norm[:1000]).ratio()
        
        # Si los prefijos son muy similares, tomar algunas muestras más
        if prefix_match > 0.8:
            # Muestrear el medio y el final
            middle1 = text1_norm[len(text1_norm)//2:len(text1_norm)//2+500]
            middle2 = text2_norm[len(text2_norm)//2:len(text2_norm)//2+500]
            
            suffix1 = text1_norm[-1000:] if len(text1_norm) > 1000 else text1_norm
            suffix2 = text2_norm[-1000:] if len(text2_norm) > 1000 else text2_norm
            
            middle_match = SequenceMatcher(None, middle1, middle2).ratio()
            suffix_match = SequenceMatcher(None, suffix1, suffix2).ratio()
            
            # Ponderar las tres comparaciones
            return (prefix_match * 0.4 + middle_match * 0.3 + suffix_match * 0.3)
        else:
            # Si los prefijos no son similares, no son duplicados
            return prefix_match
    else:
        # Para textos más pequeños, comparar completamente
        return SequenceMatcher(None, text1_norm, text2_norm).ratio()

def is_duplicate_content(text1, text2, threshold=0.85):
    """
    Determina si dos textos son duplicados basándose en un umbral de similitud.
    
    Args:
        text1 (str): Primer texto
        text2 (str): Segundo texto
        threshold (float): Umbral de similitud (0-1)
        
    Returns:
        bool: True si los textos son similares por encima del umbral
    """
    # Si los textos son exactamente iguales, retornar inmediatamente
    if text1 == text2:
        return True
    
    # Si alguno es vacío, no son duplicados
    if not text1 or not text2:
        return False
    
    # Calcular similitud
    similarity = calculate_similarity_ratio(text1, text2)
    
    return similarity >= threshold

def find_similar_paragraphs(paragraphs, threshold=0.85):
    """
    Encuentra párrafos similares en una lista.
    
    Args:
        paragraphs (list): Lista de objetos párrafo con una clave 'text'
        threshold (float): Umbral de similitud (0-1)
        
    Returns:
        dict: Diccionario de grupos de párrafos similares
    """
    similar_groups = defaultdict(list)
    processed_indices = set()
    
    # Calcular hashes para todos los párrafos
    paragraph_hashes = {}
    for i, para in enumerate(paragraphs):
        if not para or not para.get('text'):
            continue
        text = para.get('text', '')
        paragraph_hashes[i] = calculate_text_hash(text)
    
    # Agrupar párrafos por similitud de hash
    for i in range(len(paragraphs)):
        if i in processed_indices or not paragraphs[i].get('text'):
            continue
            
        hash1 = paragraph_hashes[i]
        group_id = i
        similar_groups[group_id].append(paragraphs[i])
        processed_indices.add(i)
        
        # Comparar con el resto de párrafos
        for j in range(i+1, len(paragraphs)):
            if j in processed_indices or not paragraphs[j].get('text'):
                continue
                
            # Verificación rápida por hash
            hash2 = paragraph_hashes[j]
            
            # Si los hashes son idénticos, son duplicados
            if hash1 == hash2:
                similar_groups[group_id].append(paragraphs[j])
                processed_indices.add(j)
            else:
                # Si los hashes son diferentes, verificar por similitud
                # Solo para textos relativamente largos (evitar falsos positivos)
                if len(paragraphs[i].get('text', '')) > 100 and len(paragraphs[j].get('text', '')) > 100:
                    if is_duplicate_content(paragraphs[i].get('text', ''), paragraphs[j].get('text', ''), threshold):
                        similar_groups[group_id].append(paragraphs[j])
                        processed_indices.add(j)
    
    # Filtrar grupos que solo tienen un elemento (no hay duplicados)
    return {k: v for k, v in similar_groups.items() if len(v) > 1}

def detect_duplicate_pdfs(pdf_texts, similarity_threshold=0.85, min_text_length=500):
    """
    Detecta PDFs que tienen contenido similar o idéntico.
    
    Args:
        pdf_texts (dict): Diccionario de textos de PDF con formato {url: {extracted_text: "..."}}
        similarity_threshold (float): Umbral de similitud (0-1)
        min_text_length (int): Longitud mínima de texto para considerar similitud
        
    Returns:
        dict: Grupos de PDFs similares {group_id: [urls]}
    """
    if not pdf_texts or len(pdf_texts) <= 1:
        return {}
    
    similar_groups = defaultdict(list)
    processed_urls = set()
    
    # Extraer solo el texto de cada PDF
    url_to_text = {}
    for url, data in pdf_texts.items():
        if isinstance(data, dict) and 'extracted_text' in data:
            text = data['extracted_text']
        elif isinstance(data, dict) and 'content' in data:
            # Manejar estructura alternativa como en los PDFs de facebook_texts
            content = data.get('content', {})
            if isinstance(content, dict):
                # Concatenar texto de todas las secciones
                sections_text = []
                for section, paragraphs in content.items():
                    if isinstance(paragraphs, list):
                        for para in paragraphs:
                            if isinstance(para, dict) and 'text' in para:
                                sections_text.append(para['text'])
                text = " ".join(sections_text)
            else:
                text = str(content)
        else:
            text = str(data)
        
        # Solo considerar textos con longitud mínima
        if len(text) >= min_text_length:
            url_to_text[url] = text
    
    # Lista de URLs con textos válidos
    urls = list(url_to_text.keys())
    
    # Comparar todos los pares de PDFs
    for i, url1 in enumerate(urls):
        if url1 in processed_urls:
            continue
            
        text1 = url_to_text[url1]
        group_id = i
        similar_groups[group_id].append(url1)
        processed_urls.add(url1)
        
        for j in range(i+1, len(urls)):
            url2 = urls[j]
            if url2 in processed_urls:
                continue
                
            text2 = url_to_text[url2]
            
            # Comprobar similitud
            if is_duplicate_content(text1, text2, similarity_threshold):
                similar_groups[group_id].append(url2)
                processed_urls.add(url2)
    
    # Filtrar grupos que solo tienen un elemento (no hay duplicados)
    similar_groups = {k: v for k, v in similar_groups.items() if len(v) > 1}
    
    logger.info(f"Detectados {len(similar_groups)} grupos de PDFs con contenido similar")
    for group_id, urls_in_group in similar_groups.items():
        logger.debug(f"Grupo {group_id}: {len(urls_in_group)} PDFs similares")
    
    return similar_groups

def consolidate_pdf_texts(pdf_texts, similarity_threshold=0.85):
    """
    Consolida los textos de PDFs, manteniendo solo una versión de cada texto similar.
    
    Args:
        pdf_texts (dict): Diccionario de textos de PDF con formato {url: {extracted_text: "..."}}
        similarity_threshold (float): Umbral de similitud (0-1)
        
    Returns:
        dict: Textos de PDF consolidados sin duplicados, conserva el contenido 
              más completo de cada grupo con metadatos de las fuentes
    """
    # Encuentra grupos de PDFs similares
    similar_groups = detect_duplicate_pdfs(pdf_texts, similarity_threshold)
    
    if not similar_groups:
        logger.info("No se encontraron PDFs con contenido similar")
        return pdf_texts
    
    # Crear copia del diccionario original
    consolidated_texts = pdf_texts.copy()
    
    # Consolidar cada grupo
    for group_id, urls in similar_groups.items():
        # Si solo hay un elemento en el grupo, no hay que consolidar
        if len(urls) <= 1:
            continue
        
        # Encontrar el texto más completo del grupo
        longest_text_url = None
        max_length = 0
        
        for url in urls:
            data = pdf_texts.get(url, {})
            
            if isinstance(data, dict) and 'extracted_text' in data:
                text_length = len(data['extracted_text'])
            elif isinstance(data, dict) and 'content' in data:
                # Contar longitud total de contenido para estructura alternativa
                content = data.get('content', {})
                if isinstance(content, dict):
                    text_length = sum(
                        len(para.get('text', '')) 
                        for section, paragraphs in content.items() 
                        if isinstance(paragraphs, list)
                        for para in paragraphs 
                        if isinstance(para, dict)
                    )
                else:
                    text_length = len(str(content))
            else:
                text_length = len(str(data))
            
            if text_length > max_length:
                max_length = text_length
                longest_text_url = url
        
        if not longest_text_url:
            continue
        
        # Reemplazar todos los PDFs del grupo con el texto más largo
        best_content = pdf_texts[longest_text_url]
        
        # Añadir metadatos de las fuentes
        if isinstance(best_content, dict):
            # Crear o actualizar lista de fuentes originales
            if 'similar_sources' not in best_content:
                best_content['similar_sources'] = []
            
            # Añadir todas las URLs excepto la principal como fuentes similares
            for url in urls:
                if url != longest_text_url:
                    source_meta = {
                        'url': url,
                        'pdf_path': pdf_texts.get(url, {}).get('pdf_path', '')
                    }
                    best_content['similar_sources'].append(source_meta)
                    
                    # Eliminar la versión duplicada
                    if url in consolidated_texts:
                        del consolidated_texts[url]
        
        # Asegurar que el contenido principal sigue en el resultado
        consolidated_texts[longest_text_url] = best_content
    
    logger.info(f"Consolidación completada: {len(pdf_texts)} textos reducidos a {len(consolidated_texts)}")
    return consolidated_texts

def get_unprocessed_urls(all_links, processed_data):
    """
    Genera un diccionario con URLs no procesadas por categoría.
    
    Args:
        all_links (list): Lista de enlaces extraídos del PDF
        processed_data (dict): Datos procesados con subdiccionarios por tipo
        
    Returns:
        dict: URLs no procesadas por categoría
    """
    # Extraer URLs procesadas de cada categoría
    processed_urls = set()
    
    # HTML procesado
    if 'html' in processed_data and processed_data['html']:
        processed_urls.update(processed_data['html'].keys())
    
    # Imágenes procesadas
    if 'images_api' in processed_data and processed_data['images_api']:
        for image_data in processed_data['images_api']:
            if image_data.get('url'):
                processed_urls.add(image_data['url'])
    
    # Audio procesado
    if 'audio' in processed_data and processed_data['audio']:
        processed_urls.update(processed_data['audio'].keys())
    
    # Facebook procesado
    if 'facebook' in processed_data and processed_data['facebook']:
        processed_urls.update(processed_data['facebook'].keys())
    
    # Categorizar URLs no procesadas
    unprocessed_by_category = {
        'html': [],
        'image': [],
        'facebook': [],
        'audio': [],
        'other': []
    }
    
    # Clasificar URLs no procesadas
    for link in all_links:
        url = link.get('URL')
        if not url or url in processed_urls:
            continue
        
        url_lower = url.lower()
        
        # Clasificar URL por tipo
        if url_lower.startswith(('http://facebook.com', 'https://facebook.com', 
                               'http://www.facebook.com', 'https://www.facebook.com',
                               'http://fb.com', 'https://fb.com')):
            unprocessed_by_category['facebook'].append(link)
        elif any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']):
            unprocessed_by_category['image'].append(link)
        elif any(ext in url_lower for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.opus']):
            unprocessed_by_category['audio'].append(link)
        elif url_lower.startswith(('http://', 'https://')) and not url_lower.endswith(('.pdf', '.doc', '.docx')):
            unprocessed_by_category['html'].append(link)
        else:
            unprocessed_by_category['other'].append(link)
    
    # Eliminar categorías vacías
    return {k: v for k, v in unprocessed_by_category.items() if v} 
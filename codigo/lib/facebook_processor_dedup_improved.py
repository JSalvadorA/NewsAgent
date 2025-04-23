#!/usr/bin/env python3
"""
Módulo mejorado de procesamiento de Facebook con detección de duplicados.
Implementa detección proactiva de duplicados basada en contenido.
"""

import os
import json
import logging
import hashlib
import time
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import re
from typing import Dict, List, Tuple, Set, Any
from datetime import datetime
import PyPDF2
from pathlib import Path
import base64
from difflib import SequenceMatcher
import threading

from .facebook_processor import FacebookProcessor

logger = logging.getLogger(__name__)

class FacebookProcessorWithDedup:
    """
    Envoltorio mejorado para FacebookProcessor con detección proactiva de duplicados.
    Detecta duplicados antes de generar PDFs para evitar procesamiento innecesario.
    """
    
    def __init__(self, config):
        """
        Inicializa el envoltorio con la configuración proporcionada.
        
        Args:
            config: Configuración del sistema
        """
        self.config = config
        # Crear el procesador original pero no lo usaremos directamente para process_facebook_urls_parallel
        self.facebook_processor = FacebookProcessor(config)
        
        # Configuración de deduplicación
        dedup_config = config.get('facebook_dedup', {})
        self.enable_deduplication = dedup_config.get('enable_deduplication', True)
        self.similarity_threshold = dedup_config.get('similarity_threshold', 0.85)
        self.min_content_length = dedup_config.get('min_content_length', 100)
        self.sample_size = dedup_config.get('sample_size', 1000)
        self.normalize_urls = dedup_config.get('normalize_urls', True)
        self.store_mapping = dedup_config.get('store_mapping', True)
        
        # Estado para deduplicación
        self.content_hashes = {}  # Hash -> URL
        self.text_samples = {}    # URL -> muestra de texto
        self.duplicate_mapping = {}  # URL duplicada -> URL original
        self.content_lock = threading.Lock()  # Para acceso thread-safe
        
        # Directorio para guardar información sobre duplicados
        self.paths = config.get('paths', {})
        self.project_root = self.paths.get('project_root', '')
        
        logger.info(f"FacebookProcessorWithDedup inicializado. Deduplicación {'activada' if self.enable_deduplication else 'desactivada'}")
    
    def normalize_facebook_url(self, url: str) -> str:
        """
        Normaliza una URL de Facebook eliminando parámetros de tracking y otros identificadores.
        
        Args:
            url: URL original
            
        Returns:
            URL normalizada
        """
        if not self.normalize_urls:
            return url
            
        try:
            # Parsear la URL
            parsed_url = urlparse(url)
            
            # Obtener parámetros
            params = parse_qs(parsed_url.query)
            
            # Eliminar parámetros de tracking conocidos
            tracking_params = ['fbclid', 'ref', 'ref_type', 'source', 'utm_source', 'utm_medium', 
                              'utm_campaign', 'tracking', '_ga', 'rdid', 'mibextid']
            
            for param in params.copy():
                if param in tracking_params or param.startswith('utm_'):
                    del params[param]
            
            # Recrear query string
            query_string = urlencode(params, doseq=True)
            
            # Recrear URL normalizada
            normalized_url = urlunparse((
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                parsed_url.params,
                query_string,
                ''  # Sin fragmento
            ))
            
            # Eliminar IDs específicos que mantienen el mismo contenido
            normalized_url = re.sub(r'/posts/\d+/', '/posts/', normalized_url)
            normalized_url = re.sub(r'/videos/\d+/', '/videos/', normalized_url)
            normalized_url = re.sub(r'/watch/\?v=\d+', '/watch/', normalized_url)
            
            # Reemplazar múltiples patrones de identificadores
            patterns = [
                r'story\.php\?story_fbid=[^&]+&id=\d+',
                r'permalink\.php\?story_fbid=[^&]+&id=\d+',
                r'/posts/pfbid[^/]+',
                r'/videos/\d+',
                r'/share/[pv]/[^/]+',
                r'/\d+/videos/\d+',
                r'/\d+/posts/\d+'
            ]
            
            for pattern in patterns:
                # Reemplazar con un marcador genérico que representa ese tipo de contenido
                if re.search(pattern, normalized_url):
                    # Extraer el dominio y la primera parte de la ruta
                    domain_parts = parsed_url.netloc.split('.')
                    if len(domain_parts) >= 2:
                        domain = domain_parts[-2] if domain_parts[-2] != 'co' else domain_parts[-3]
                    else:
                        domain = parsed_url.netloc
                    
                    # Determinar el tipo de contenido
                    if 'story.php' in normalized_url or 'permalink.php' in normalized_url:
                        content_type = 'post'
                    elif 'videos' in normalized_url or 'watch' in normalized_url:
                        content_type = 'video'
                    elif 'posts' in normalized_url or 'share' in normalized_url:
                        content_type = 'post'
                    else:
                        content_type = 'content'
                    
                    # Si hay ID de página/perfil, extraerlo
                    page_id = None
                    if 'id=' in normalized_url:
                        id_match = re.search(r'id=(\d+)', normalized_url)
                        if id_match:
                            page_id = id_match.group(1)
                    
                    # Crear una URL representativa
                    if page_id:
                        normalized_url = f"facebook://{domain}/{page_id}/{content_type}"
                    else:
                        normalized_url = f"facebook://{domain}/{content_type}"
                    
                    break
            
            return normalized_url
            
        except Exception as e:
            logger.warning(f"Error normalizando URL {url}: {e}")
            return url
    
    def text_similarity(self, text1: str, text2: str) -> float:
        """
        Calcula la similitud entre dos textos usando SequenceMatcher.
        
        Args:
            text1, text2: Textos a comparar
            
        Returns:
            Similitud como valor entre 0.0 y 1.0
        """
        if not text1 or not text2:
            return 0.0
        
        # Limitar el tamaño para rendimiento
        sample_size = min(self.sample_size, min(len(text1), len(text2)))
        
        # Tomar muestras significativas (inicio, medio y final)
        if len(text1) > 3*sample_size:
            text1_sample = text1[:sample_size] + text1[len(text1)//2-sample_size//2:len(text1)//2+sample_size//2] + text1[-sample_size:]
        else:
            text1_sample = text1[:3*sample_size]
            
        if len(text2) > 3*sample_size:
            text2_sample = text2[:sample_size] + text2[len(text2)//2-sample_size//2:len(text2)//2+sample_size//2] + text2[-sample_size:]
        else:
            text2_sample = text2[:3*sample_size]
        
        # Calcular similitud
        matcher = SequenceMatcher(None, text1_sample, text2_sample)
        return matcher.ratio()
    
    def is_content_duplicate(self, content_text: str, url: str) -> Tuple[bool, str]:
        """
        Verifica si el contenido es duplicado comparándolo con muestras existentes.
        
        Args:
            content_text: Texto del contenido a verificar
            url: URL de origen
            
        Returns:
            Tuple con (es_duplicado, url_original)
        """
        if not self.enable_deduplication or not content_text or len(content_text) < self.min_content_length:
            return False, None
        
        # Generar fingerprint
        content_hash = hashlib.md5(content_text[:self.sample_size].encode('utf-8')).hexdigest()
        
        with self.content_lock:
            # Verificar exactitud por hash
            if content_hash in self.content_hashes:
                original_url = self.content_hashes[content_hash]
                logger.debug(f"Contenido duplicado exacto detectado: {url} es duplicado de {original_url}")
                self.duplicate_mapping[url] = original_url
                return True, original_url
            
            # Si no hay match exacto, buscar por similitud
            for orig_url, sample in self.text_samples.items():
                similarity = self.text_similarity(content_text, sample)
                if similarity >= self.similarity_threshold:
                    logger.debug(f"Contenido similar detectado: {url} es similar a {orig_url} ({similarity:.2f})")
                    self.duplicate_mapping[url] = orig_url
                    return True, orig_url
            
            # Si no es duplicado, registrar
            self.content_hashes[content_hash] = url
            self.text_samples[url] = content_text
            
        return False, None
    
    def filter_duplicate_urls(self, urls: List[str]) -> List[str]:
        """
        Filtrar URLs que son duplicadas basadas en normalización.
        
        Args:
            urls: Lista de URLs a filtrar
            
        Returns:
            Lista de URLs únicas
        """
        if not self.enable_deduplication:
            return urls
            
        # Normalizar URLs
        normalized_urls = {}
        for url in urls:
            normalized = self.normalize_facebook_url(url)
            normalized_urls[url] = normalized
        
        # Agrupar por URL normalizada
        url_groups = {}
        for original, normalized in normalized_urls.items():
            if normalized not in url_groups:
                url_groups[normalized] = []
            url_groups[normalized].append(original)
        
        # Seleccionar un representante de cada grupo
        unique_urls = []
        for norm_url, originals in url_groups.items():
            representative = originals[0]
            unique_urls.append(representative)
            
            # Registrar las demás como duplicados
            if len(originals) > 1:
                for dup in originals[1:]:
                    self.duplicate_mapping[dup] = representative
                    logger.info(f"URL duplicada por normalización: {dup} -> {representative}")
        
        logger.info(f"Filtrado de URLs: {len(urls)} originales -> {len(unique_urls)} únicas tras normalización")
        return unique_urls
    
    def process_facebook_url(self, url: str, date_str: str, index: int) -> Dict[str, Any]:
        """
        Procesa una URL de Facebook verificando primero si es un duplicado.
        
        Args:
            url: URL de Facebook a procesar
            date_str: Fecha en formato ddmmyyyy
            index: Índice para el nombre del archivo
            
        Returns:
            Resultado del procesamiento
        """
        # Verificar si ya es un duplicado conocido (por normalización)
        if url in self.duplicate_mapping:
            original_url = self.duplicate_mapping[url]
            return {
                "url": url,
                "timestamp": datetime.now().isoformat(),
                "pdf_path": None,
                "success": False,
                "is_duplicate": True,
                "duplicate_of": original_url,
                "duplicate_type": "url_normalized"
            }
        
        # Directorio para PDFs
        output_dir = os.path.join(self.paths.get('project_root'), 'base', date_str)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
        
        # Generar nombre de archivo
        pdf_filename = f"{date_str}-{index}.pdf"
        pdf_path = os.path.join(output_dir, pdf_filename)
        
        # Inicializar WebDriver y generar captura
        driver = None
        result = {
            "url": url,
            "timestamp": datetime.now().isoformat(),
            "pdf_path": None,
            "success": False,
            "error": None
        }
        
        try:
            # Configuración de Chrome del procesador original
            driver = None
            chrome_options = self.facebook_processor.chrome_options
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(60)
            
            # Navegar a la URL
            driver.get(url)
            time.sleep(3)  # Espera básica
            
            # Hacer scroll para cargar contenido
            for _ in range(2):
                driver.execute_script("window.scrollBy(0, 600)")
                time.sleep(1)
            
            # Extraer texto visible para verificación de duplicados
            from selenium.webdriver.common.by import By
            visible_text = driver.find_element(By.TAG_NAME, "body").text
            
            # Verificar si es un duplicado de contenido
            is_duplicate, duplicate_of = self.is_content_duplicate(visible_text, url)
            if is_duplicate:
                # Es un duplicado, no generar PDF
                driver.quit()
                return {
                    "url": url,
                    "timestamp": datetime.now().isoformat(),
                    "pdf_path": None,
                    "success": False,
                    "is_duplicate": True,
                    "duplicate_of": duplicate_of,
                    "duplicate_type": "content_similar"
                }
            
            # No es duplicado, generar PDF
            print_options = {
                "printBackground": True,
                "paperWidth": 8.27,
                "paperHeight": 11.7,
                "marginTop": 0.4,
                "marginBottom": 0.4,
                "marginLeft": 0.4,
                "marginRight": 0.4,
                "scale": 0.9,
            }
            
            # Usar método CDP para generar PDF
            result_cdp = driver.execute_cdp_cmd("Page.printToPDF", print_options)
            
            # Guardar PDF
            pdf_data = base64.b64decode(result_cdp['data'])
            with open(pdf_path, 'wb') as f:
                f.write(pdf_data)
            
            # Actualizar resultado
            result["pdf_path"] = pdf_path
            result["success"] = True
            logger.info(f"PDF guardado exitosamente: {pdf_path}")
            
        except Exception as e:
            logger.error(f"Error procesando URL {url}: {e}")
            result["error"] = str(e)
        finally:
            # Cerrar WebDriver
            if driver:
                try:
                    driver.quit()
                except:
                    pass
        
        return result
    
    def process_facebook_urls_parallel(self, urls: List[str], date_str: str) -> Dict[str, Any]:
        """
        Procesa las URLs de Facebook en paralelo con detección de duplicados.
        
        Args:
            urls: Lista de URLs a procesar
            date_str: Fecha en formato ddmmyyyy
            
        Returns:
            Resultados del procesamiento
        """
        if not urls:
            logger.info("No hay URLs de Facebook para procesar.")
            return {}
        
        start_time = time.time()
        logger.info(f"Procesando {len(urls)} URLs de Facebook con deduplicación")
        
        # Paso 1: Filtrar por normalización de URL
        unique_urls = self.filter_duplicate_urls(urls)
        
        # Paso 2: Procesar URLs únicas
        results = {}
        total_urls = len(unique_urls)
        processed_count = 0
        
        logger.info(f"Iniciando procesamiento de {total_urls} URLs únicas de Facebook")
        start_time = time.time()
        
        # Usar ThreadPoolExecutor para paralelizar
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(self.facebook_processor.max_workers, 5)) as executor:
            # Crear trabajos para cada URL
            future_to_url = {}
            for idx, url in enumerate(unique_urls, 1):
                future = executor.submit(self.process_facebook_url, url, date_str, idx)
                future_to_url[future] = url
            
            # Procesar resultados a medida que se completan
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                processed_count += 1
                
                try:
                    result = future.result()
                    results[url] = result
                    
                    status = "PDF generado" if result.get("success") else \
                             "Duplicado" if result.get("is_duplicate") else \
                             f"Error: {result.get('error', 'desconocido')}"
                    
                    logger.info(f"URL {processed_count}/{total_urls}: {url} - {status}")
                    
                except Exception as e:
                    logger.error(f"Error procesando URL {url}: {e}")
                    results[url] = {
                        "url": url,
                        "timestamp": datetime.now().isoformat(),
                        "success": False,
                        "error": str(e)
                    }
                
                # Mostrar progreso periódicamente
                if processed_count % 5 == 0 or processed_count == total_urls:
                    elapsed = time.time() - start_time
                    logger.info(f"Progreso: {processed_count}/{total_urls} URLs procesadas en {elapsed:.2f} seg.")
        
        # Paso 3: Verificar duplicados de contenido en los PDFs generados
        self._detect_content_duplicates(results, date_str)
        
        # Paso 4: Añadir resultados para URLs duplicadas
        complete_results = {}
        
        # Incluir resultados originales
        for url, result in results.items():
            complete_results[url] = result
        
        # Añadir referencias para duplicados
        for dup_url, orig_url in self.duplicate_mapping.items():
            if dup_url not in complete_results and orig_url in complete_results:
                orig_result = complete_results[orig_url]
                
                dup_result = orig_result.copy()
                dup_result['is_duplicate'] = True
                dup_result['duplicate_of'] = orig_url
                dup_result['processed'] = False
                
                complete_results[dup_url] = dup_result
        
        # Guardar mapeo de duplicados
        if self.store_mapping and self.duplicate_mapping:
            self._save_duplicate_mapping(date_str)
        
        # Estadísticas
        end_time = time.time()
        total_urls = len(urls)
        unique_count = len(unique_urls)
        dup_count = total_urls - unique_count
        
        logger.info(f"Procesamiento completo: {total_urls} URLs totales, {unique_count} únicas, {dup_count} duplicadas")
        logger.info(f"Tiempo de procesamiento total: {end_time - start_time:.2f} segundos")
        
        return complete_results
    
    def _detect_content_duplicates(self, results: Dict[str, Any], date_str: str) -> None:
        """
        Detecta duplicados basados en el contenido de los PDFs generados.
        
        Args:
            results: Resultados del procesamiento
            date_str: Fecha en formato ddmmyyyy
        """
        logger.info("Buscando duplicados por contenido en PDFs generados...")
        
        content_duplicates = 0
        processed_texts = {}
        
        # Extraer texto de todos los PDFs primero
        for url, result in results.items():
            if result.get('success') and result.get('pdf_path') and os.path.exists(result['pdf_path']):
                # Extraer contenido
                text = self.facebook_processor.extract_text_from_pdf(result['pdf_path'])
                if text and len(text) > self.min_content_length:
                    processed_texts[url] = text
        
        # Ahora comparar textos entre sí
        for url, text in processed_texts.items():
            # Saltar si ya está marcado como duplicado
            if results[url].get('is_content_duplicate'):
                continue
                
            # Comparar con otros textos
            for other_url, other_text in processed_texts.items():
                # No comparar consigo mismo o con duplicados ya identificados
                if url == other_url or results[other_url].get('is_content_duplicate'):
                    continue
                    
                # Verificar similitud
                similarity = self.text_similarity(text, other_text)
                if similarity >= self.similarity_threshold:
                    # Marcar como duplicado el que tenga URL "mayor" (criterio arbitrario)
                    duplicate_url = url if url > other_url else other_url
                    original_url = other_url if duplicate_url == url else url
                    
                    # Actualizar resultado
                    if duplicate_url in results:
                        results[duplicate_url]['is_content_duplicate'] = True
                        results[duplicate_url]['duplicate_of'] = original_url
                        results[duplicate_url]['similarity'] = similarity
                        content_duplicates += 1
                        
                        # Registrar el mapeo
                        self.duplicate_mapping[duplicate_url] = original_url
                        break
        
        logger.info(f"Encontrados {content_duplicates} duplicados por contenido")
    
    def _save_duplicate_mapping(self, date_str: str) -> None:
        """
        Guarda el mapeo de URLs duplicadas a un archivo.
        
        Args:
            date_str: Fecha en formato ddmmyyyy
        """
        if not self.project_root:
            return
            
        try:
            output_dir = os.path.join(self.project_root, 'output')
            os.makedirs(output_dir, exist_ok=True)
            
            mapping_data = {
                "generated_at": datetime.now().isoformat(),
                "date_processed": date_str,
                "duplicate_count": len(self.duplicate_mapping),
                "mapping": self.duplicate_mapping,
            }
            
            output_path = os.path.join(output_dir, f"facebook_duplicates_{date_str}.json")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"Mapeo de duplicados guardado en: {output_path}")
            
        except Exception as e:
            logger.error(f"Error guardando mapeo de duplicados: {e}")
    
    def _create_webdriver(self):
        """Crea una instancia de WebDriver utilizando las opciones configuradas"""
        return self.facebook_processor._create_webdriver()
    
    def extract_text_from_all_pdfs(self, facebook_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Utiliza el procesador original para extraer texto de PDFs, pero
        maneja correctamente los duplicados.
        
        Args:
            facebook_results: Resultados del procesamiento
            
        Returns:
            Textos extraídos incluyendo referencias para duplicados
        """
        # Identificar PDFs únicos para procesar
        unique_results = {url: result for url, result in facebook_results.items()
                         if not result.get('is_duplicate') and not result.get('is_content_duplicate')}
        
        # Extraer texto de PDFs únicos
        pdf_texts = self.facebook_processor.extract_text_from_all_pdfs(unique_results)
        
        # Añadir referencias para URLs duplicadas
        for url, result in facebook_results.items():
            if (result.get('is_duplicate') or result.get('is_content_duplicate')) and 'duplicate_of' in result:
                original_url = result['duplicate_of']
                if original_url in pdf_texts:
                    # Crear referencia
                    duplicate_text_info = pdf_texts[original_url].copy()
                    duplicate_text_info['is_duplicate'] = True
                    duplicate_text_info['original_source'] = original_url
                    
                    # Usar el texto del original
                    pdf_texts[url] = duplicate_text_info
        
        return pdf_texts
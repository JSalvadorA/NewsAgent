#!/usr/bin/env python3
"""
Módulo de procesamiento de Facebook con detección de duplicados.
Envuelve el FacebookProcessor original añadiendo la capacidad de filtrar contenido duplicado.
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

from .facebook_processor import FacebookProcessor

logger = logging.getLogger(__name__)

class FacebookProcessorWithDedup:
    """
    Envoltorio para FacebookProcessor que añade detección de duplicados.
    Utiliza el procesador original pero filtra URLs que probablemente generen contenido duplicado.
    """
    
    def __init__(self, config):
        """
        Inicializa el envoltorio con la configuración proporcionada.
        
        Args:
            config: Configuración del sistema
        """
        self.config = config
        # Crear el procesador original
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
        self.content_samples = {}  # URL -> muestra de contenido
        self.duplicate_mapping = {}  # URL duplicada -> URL original
        self.processed_urls = set()  # URLs ya procesadas
        
        # Directorio para guardar información sobre duplicados
        self.paths = config.get('paths', {})
        self.project_root = self.paths.get('project_root', '')
        
        logger.info(f"FacebookProcessorWithDedup inicializado. Deduplicación {'activada' if self.enable_deduplication else 'desactivada'}")
    
    def normalize_facebook_url(self, url: str) -> str:
        """
        Normaliza una URL de Facebook eliminando parámetros de tracking.
        
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
                              'utm_campaign', 'tracking', '_ga']
            
            for param in tracking_params:
                if param in params:
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
            
            # Eliminar IDs de publicación específicos que mantengan el mismo contenido
            # Ejemplo: /posts/123456789/ -> /posts/
            normalized_url = re.sub(r'/posts/\d+/', '/posts/', normalized_url)
            
            return normalized_url
            
        except Exception as e:
            logger.warning(f"Error normalizando URL {url}: {e}")
            return url
    
    def extract_content_from_pdf(self, pdf_path: str) -> str:
        """
        Extrae el contenido textual de un PDF.
        
        Args:
            pdf_path: Ruta al archivo PDF
            
        Returns:
            Contenido textual del PDF
        """
        if not os.path.exists(pdf_path):
            return ""
            
        try:
            with open(pdf_path, 'rb') as file:
                # Crear lector de PDF
                pdf_reader = PyPDF2.PdfReader(file)
                
                # Extraer texto de todas las páginas
                text = ""
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n\n"
                
                return text.strip()
        except Exception as e:
            logger.error(f"Error extrayendo texto de PDF {pdf_path}: {e}")
            return ""
    
    def get_content_fingerprint(self, text: str) -> str:
        """
        Genera una huella digital del contenido para comparación.
        
        Args:
            text: Texto completo
            
        Returns:
            Hash del contenido como identificador
        """
        if not text or len(text) < self.min_content_length:
            return ""
            
        # Crear un extracto significativo (primeros N caracteres + últimos N)
        sample_size = min(self.sample_size, len(text) // 2)
        content_sample = (text[:sample_size] + text[-sample_size:]).strip()
        
        # Generar hash
        return hashlib.md5(content_sample.encode('utf-8')).hexdigest()
    
    def is_duplicate_content(self, text: str, url: str = None) -> Tuple[bool, str]:
        """
        Determina si el contenido es duplicado basado en hashes.
        
        Args:
            text: Texto a verificar
            url: URL de origen (opcional)
            
        Returns:
            Tuple de (es_duplicado, url_original)
        """
        if not self.enable_deduplication:
            return False, None
            
        if not text or len(text) < self.min_content_length:
            return False, None
            
        # Generar fingerprint
        content_hash = self.get_content_fingerprint(text)
        if not content_hash:
            return False, None
            
        # Verificar si ya existe este hash
        if content_hash in self.content_hashes:
            original_url = self.content_hashes[content_hash]
            if url:
                self.duplicate_mapping[url] = original_url
                logger.info(f"Contenido duplicado detectado: {url} es duplicado de {original_url}")
            return True, original_url
            
        # No es duplicado, registrar si hay URL
        if url:
            self.content_hashes[content_hash] = url
            self.content_samples[url] = text[:self.sample_size] + "..." if len(text) > self.sample_size else text
            
        return False, None
    
    def filter_duplicate_urls(self, urls: List[str]) -> List[str]:
        """
        Filtra URLs que probablemente contengan contenido duplicado.
        
        Args:
            urls: Lista de URLs a filtrar
            
        Returns:
            Lista de URLs únicas
        """
        if not self.enable_deduplication:
            return urls
            
        # Normalizar URLs primero
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
            # Usar la primera URL como representante
            representative = originals[0]
            unique_urls.append(representative)
            
            # Registrar las demás como duplicados
            if len(originals) > 1:
                for dup in originals[1:]:
                    self.duplicate_mapping[dup] = representative
                    logger.info(f"URL duplicada por normalización: {dup} -> {representative}")
        
        logger.info(f"Filtrado de URLs: {len(urls)} originales -> {len(unique_urls)} únicas tras normalización")
        return unique_urls
    
    def process_facebook_urls_parallel(self, urls: List[str], date_str: str) -> Dict[str, Any]:
        """
        Procesa URLs de Facebook en paralelo, evitando duplicados.
        
        Args:
            urls: Lista de URLs a procesar
            date_str: Fecha en formato ddmmyyyy
            
        Returns:
            Diccionario con resultados del procesamiento
        """
        if not urls:
            logger.info("No hay URLs de Facebook para procesar.")
            return {}
        
        start_time = time.time()
        logger.info(f"Procesando {len(urls)} URLs de Facebook con deduplicación")
        
        # Paso 1: Filtrar por normalización de URL
        unique_urls = self.filter_duplicate_urls(urls)
        
        # Paso 2: Procesar URLs únicas con el procesador original
        results = self.facebook_processor.process_facebook_urls_parallel(unique_urls, date_str)
        
        # Paso 3: Buscar duplicados por contenido
        if self.enable_deduplication:
            self._detect_content_duplicates(results, date_str)
        
        # Paso 4: Incorporar resultados para URLs duplicadas
        complete_results = {}
        
        # Primero incluir todos los resultados originales
        for url, result in results.items():
            complete_results[url] = result
            
        # Luego añadir referencias para las URLs que se saltaron por duplicación
        for dup_url, orig_url in self.duplicate_mapping.items():
            if dup_url not in complete_results and orig_url in complete_results:
                # Copiar el resultado de la URL original
                orig_result = complete_results[orig_url]
                
                # Crear una versión modificada para la URL duplicada
                dup_result = orig_result.copy()
                dup_result['is_duplicate'] = True
                dup_result['duplicate_of'] = orig_url
                dup_result['processed'] = False  # No se procesó directamente
                
                complete_results[dup_url] = dup_result
                logger.debug(f"Añadido resultado para URL duplicada: {dup_url}")
        
        # Guardar mapeo de duplicados si está configurado
        if self.store_mapping and self.duplicate_mapping:
            self._save_duplicate_mapping(date_str)
        
        # Estadísticas finales
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
        
        # Iterar por los resultados
        for url, result in results.items():
            # Solo procesar PDFs generados con éxito
            if result.get('success') and result.get('pdf_path') and os.path.exists(result['pdf_path']):
                # Extraer contenido del PDF
                pdf_content = self.extract_content_from_pdf(result['pdf_path'])
                
                # Verificar si es duplicado
                is_duplicate, original_url = self.is_duplicate_content(pdf_content, url)
                
                if is_duplicate:
                    content_duplicates += 1
                    # No eliminamos el PDF ya generado, solo registramos que es duplicado
                    result['is_content_duplicate'] = True
                    result['duplicate_of'] = original_url
        
        logger.info(f"Encontrados {content_duplicates} duplicados por contenido")
    
    def _save_duplicate_mapping(self, date_str: str) -> None:
        """
        Guarda el mapeo de URLs duplicadas a un archivo.
        
        Args:
            date_str: Fecha en formato ddmmyyyy
        """
        if not self.project_root:
            logger.warning("No se puede guardar mapeo de duplicados: project_root no definido")
            return
            
        try:
            # Crear directorio de salida si no existe
            output_dir = os.path.join(self.project_root, 'output')
            os.makedirs(output_dir, exist_ok=True)
            
            # Mapeo a guardar
            mapping_data = {
                "generated_at": datetime.now().isoformat(),
                "date_processed": date_str,
                "duplicate_count": len(self.duplicate_mapping),
                "mapping": self.duplicate_mapping,
                "content_samples": self.content_samples
            }
            
            # Guardar a archivo
            output_path = os.path.join(output_dir, f"facebook_duplicates_{date_str}.json")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"Mapeo de duplicados guardado en: {output_path}")
            
        except Exception as e:
            logger.error(f"Error guardando mapeo de duplicados: {e}")
    
    def extract_text_from_all_pdfs(self, facebook_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extrae texto de todos los PDFs, delegando al procesador original.
        
        Args:
            facebook_results: Resultados del procesamiento
            
        Returns:
            Textos extraídos
        """
        # Filtrar resultados para procesar solo PDFs no duplicados
        unique_results = {}
        
        for url, result in facebook_results.items():
            # Incluir solo los que no son duplicados o son los representantes
            if not result.get('is_duplicate') and not result.get('is_content_duplicate'):
                unique_results[url] = result
        
        # Usar el procesador original para extraer textos
        pdf_texts = self.facebook_processor.extract_text_from_all_pdfs(unique_results)
        
        # Añadir referencias para URLs duplicadas
        complete_texts = pdf_texts.copy()
        
        for url, result in facebook_results.items():
            if (result.get('is_duplicate') or result.get('is_content_duplicate')) and 'duplicate_of' in result:
                original_url = result['duplicate_of']
                if original_url in pdf_texts:
                    # Crear una copia de la información de texto
                    duplicate_text_info = pdf_texts[original_url].copy()
                    duplicate_text_info['is_duplicate'] = True
                    duplicate_text_info['original_source'] = original_url
                    
                    complete_texts[url] = duplicate_text_info
        
        return complete_texts

#!/usr/bin/env python3
"""
Versión mejorada del módulo de procesamiento de Facebook con detección de duplicados.
Detecta URLs duplicadas antes de procesarlas para evitar la generación de PDFs redundantes.
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
    Versión mejorada del procesador de Facebook con detección de duplicados.
    Filtra URLs duplicadas antes de generar PDFs y mantiene registro de duplicados.
    """
    
    def __init__(self, config):
        """
        Inicializa el procesador con la configuración proporcionada.
        
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
        
        # Diccionarios para deduplicación
        self.normalized_mapping = {}  # URL original -> URL normalizada
        self.duplicate_mapping = {}   # URL duplicada -> URL original
        self.pdf_mapping = {}         # URL -> ruta PDF
        
        # Directorio para guardar información sobre duplicados
        self.paths = config.get('paths', {})
        self.project_root = self.paths.get('project_root', '')
        
        # Cargar historial de PDFs si existe
        self._load_existing_pdfs()
        
        logger.info(f"FacebookProcessorWithDedup inicializado. Deduplicación {'activada' if self.enable_deduplication else 'desactivada'}")
    
    def _load_existing_pdfs(self):
        """
        Carga información de PDFs existentes para comparación.
        """
        try:
            # Buscar en la carpeta de resultados si hay mapeos anteriores
            if self.project_root:
                output_dir = os.path.join(self.project_root, 'output')
                if os.path.exists(output_dir):
                    # Buscar archivos de duplicados anteriores
                    duplicate_files = [f for f in os.listdir(output_dir) if f.startswith("facebook_duplicates_") and f.endswith(".json")]
                    
                    for dup_file in duplicate_files:
                        try:
                            with open(os.path.join(output_dir, dup_file), 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                
                                # Añadir al mapeo
                                if 'mapping' in data:
                                    self.duplicate_mapping.update(data['mapping'])
                                    logger.info(f"Cargado historial de duplicados desde {dup_file}: {len(data['mapping'])} URLs")
                        except Exception as e:
                            logger.warning(f"Error cargando historial de duplicados desde {dup_file}: {e}")
        except Exception as e:
            logger.warning(f"Error cargando historial de PDFs: {e}")
    
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
            # Memorizar URL original
            self.normalized_mapping[url] = url
            
            # Parsear la URL
            parsed_url = urlparse(url)
            
            # Simplificar rutas comunes
            path = parsed_url.path
            
            # Eliminar IDs de publicación específicos que mantengan el mismo contenido
            # Ejemplo: /posts/123456789/ -> /posts/
            path = re.sub(r'/posts/\d+/', '/posts/', path)
            
            # Convertir fb.com a facebook.com y manejar m.facebook.com
            netloc = parsed_url.netloc.lower()
            if netloc.startswith('fb.com'):
                netloc = 'facebook.com' + netloc[6:]
            elif netloc.startswith('m.facebook.com'):
                netloc = 'facebook.com' + netloc[13:]
                
            # Simplificar patrones específicos de Facebook
            # Ejemplo: /story.php?story_fbid=1234&id=5678 -> /story/1234
            if '/story.php' in path:
                params = parse_qs(parsed_url.query)
                if 'story_fbid' in params:
                    path = f"/story/{params['story_fbid'][0]}"
                    parsed_url = parsed_url._replace(query='')
            
            # Limpiar parámetros de tracking
            query = parsed_url.query
            if query:
                params = parse_qs(query)
                tracking_params = ['fbclid', 'ref', 'ref_type', 'source', 'utm_source', 'utm_medium', 
                                  'utm_campaign', 'tracking', '_ga', 'mibextid', 'rdid']
                
                for param in tracking_params:
                    if param in params:
                        del params[param]
                
                # Recrear query
                query = urlencode(params, doseq=True)
            
            # Recrear URL normalizada
            normalized_url = urlunparse((
                parsed_url.scheme,
                netloc,
                path,
                '',  # No params
                query,
                ''   # No fragment
            ))
            
            # Almacenar la normalización
            self.normalized_mapping[url] = normalized_url
            
            return normalized_url
            
        except Exception as e:
            logger.warning(f"Error normalizando URL {url}: {e}")
            return url
    
    def filter_urls_by_normalization(self, urls: List[str]) -> List[str]:
        """
        Primera fase de deduplicación: filtrar URLs basadas en normalización.
        
        Args:
            urls: Lista de URLs a filtrar
            
        Returns:
            Lista de URLs únicas
        """
        if not urls or not self.enable_deduplication:
            return urls
        
        # Normalizar URLs y agrupar 
        groups = {}
        for url in urls:
            norm_url = self.normalize_facebook_url(url)
            if norm_url not in groups:
                groups[norm_url] = []
            groups[norm_url].append(url)
        
        # Seleccionar un representante de cada grupo
        unique_urls = []
        for norm_url, group_urls in groups.items():
            # Tomar la primera URL como representante
            representative = group_urls[0]
            unique_urls.append(representative)
            
            # Marcar el resto como duplicados
            if len(group_urls) > 1:
                for dup_url in group_urls[1:]:
                    self.duplicate_mapping[dup_url] = representative
                    logger.info(f"URL duplicada (por normalización): {dup_url} -> {representative}")
        
        duplicate_count = len(urls) - len(unique_urls)
        logger.info(f"Deduplicación por normalización: {len(urls)} originales -> {len(unique_urls)} únicas ({duplicate_count} duplicadas)")
        
        return unique_urls
    
    def process_facebook_urls_parallel(self, urls: List[str], date_str: str) -> Dict[str, Any]:
        """
        Procesa URLs de Facebook en paralelo con deduplicación previa.
        
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
        logger.info(f"Procesando {len(urls)} URLs de Facebook con deduplicación avanzada")
        
        # PRIMER PASO: Filtrar duplicados por normalización de URL
        unique_urls = self.filter_urls_by_normalization(urls)
        
        # SEGUNDO PASO: Procesar solo las URLs únicas
        results = {}
        if unique_urls:
            # Procesar las URLs únicas con el procesador normal
            results = self.facebook_processor.process_facebook_urls_parallel(unique_urls, date_str)
            
            # Guardar el mapeo de URLs a rutas de PDF
            for url, result in results.items():
                if result.get('success') and result.get('pdf_path'):
                    self.pdf_mapping[url] = result['pdf_path']
        
        # TERCER PASO: Añadir entradas para las URLs duplicadas detectadas en normalización
        # Esto evita la generación de PDFs duplicados pero mantiene registro completo
        for dup_url, orig_url in self.duplicate_mapping.items():
            if dup_url not in results and orig_url in results:
                orig_result = results[orig_url]
                
                # Crear resultado para la URL duplicada
                dup_result = orig_result.copy()
                dup_result['is_duplicate'] = True
                dup_result['duplicate_of'] = orig_url
                dup_result['pdf_path'] = orig_result.get('pdf_path')  # Usar el mismo PDF
                
                # Añadir al diccionario de resultados
                results[dup_url] = dup_result
        
        # Guardar el mapeo de duplicados
        if self.store_mapping and self.duplicate_mapping:
            self._save_duplicate_mapping(date_str)
        
        # Estadísticas
        end_time = time.time()
        total_time = end_time - start_time
        logger.info(f"Procesamiento de Facebook con deduplicación completado en {total_time:.2f} segundos")
        
        return results
    
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
                "normalized_mapping": self.normalized_mapping,
                "pdf_mapping": self.pdf_mapping
            }
            
            # Guardar a archivo
            output_path = os.path.join(output_dir, f"facebook_duplicates_{date_str}_v2.json")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"Mapeo de duplicados guardado en: {output_path}")
            
        except Exception as e:
            logger.error(f"Error guardando mapeo de duplicados: {e}")
    
    def extract_text_from_all_pdfs(self, facebook_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extrae texto de todos los PDFs, considerando duplicados.
        
        Args:
            facebook_results: Resultados del procesamiento
            
        Returns:
            Textos extraídos
        """
        # Filtrar URLs por no duplicados para procesamiento
        unique_urls = {}
        duplicate_urls = {}
        
        for url, result in facebook_results.items():
            if result.get('is_duplicate', False):
                duplicate_urls[url] = result
            else:
                unique_urls[url] = result
        
        # Procesar solo los PDFs únicos
        pdf_texts = self.facebook_processor.extract_text_from_all_pdfs(unique_urls)
        
        # Añadir referencias para las URLs duplicadas
        for dup_url, dup_result in duplicate_urls.items():
            orig_url = dup_result.get('duplicate_of')
            if orig_url in pdf_texts:
                # Copiar la información de texto del original
                pdf_texts[dup_url] = pdf_texts[orig_url].copy()
                pdf_texts[dup_url]['is_duplicate'] = True
                pdf_texts[dup_url]['original_url'] = orig_url
        
        return pdf_texts

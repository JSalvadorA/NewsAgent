"""
process_pending_images.py
Script para procesar imágenes pendientes con detección de duplicados y manejo de tiempos límite.
Incluye detección de complejidad para procesar imágenes complejas individualmente.
"""
import os
import sys
import json
import time
import logging
import hashlib
import numpy as np
from PIL import Image
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from collections import defaultdict
import cv2  # Para análisis de complejidad de imágenes

# Agregar el directorio lib al path para importaciones
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
project_root = os.path.abspath(os.path.join(current_dir, '..'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Configurar logging
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'image_processor_enhanced.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("image_processor_enhanced")

# Importar componentes del sistema original
from lib.config_unified import get_config
from lib.image_processor import ImageProcessor
from lib.gemini_image_extractor import GeminiImageExtractor

class EnhancedImageProcessor:
    """Procesador de imágenes mejorado con detección de duplicados y manejo adaptativo"""
    
    def __init__(self, config):
        self.config = config
        self.paths = config.get('paths', {})
        self.project_root = self.paths.get('project_root', '')
        
        # Inicializar el procesador de imágenes original y el extractor de Gemini
        self.image_processor = ImageProcessor(config)
        self.gemini_extractor = GeminiImageExtractor(config)
        
        # Caché para resultados de imágenes similares
        self.image_hash_cache = {}
        self.image_results_cache = {}
        self.duplicate_mapping = {}  # Nueva estructura para mapear duplicados
        self.cache_lock = Lock()
        
        # Configuración optimizada
        self.similarity_threshold = config.get('image_similarity_threshold', 0.85)
        self.max_retries = config.get('max_retries', 1)  # Solo un reintento
        self.batch_size = config.get('batch_size', 3)
        self.cache_file = os.path.join(project_root, 'cache', 'image_hash_cache.json')
        
        # Umbrales de complejidad para procesamiento individual
        self.complexity_threshold = config.get('complexity_threshold', 0.6)  # Umbral para considerar una imagen compleja
        self.ocr_text_threshold = config.get('ocr_text_threshold', 500)      # Umbral de cantidad de texto estimado
        
        # Tiempos de pausa adaptables
        self.long_pause = config.get('long_pause_seconds', 60)  # Pausa larga (60s)
        self.short_pause = config.get('short_pause_seconds', 30)  # Pausa corta (30s)
        
        # Flag para forzar reprocesamiento (ignorar caché)
        self.force_reprocess = config.get('force_reprocess', False)
        
        # Cargar caché existente si está disponible
        self._load_cache()
        
        logger.info(f"EnhancedImageProcessor inicializado con batch_size={self.batch_size}, "
                   f"max_retries={self.max_retries}, pausas={self.short_pause}s/{self.long_pause}s"
                   f"{' (modo forzado)' if self.force_reprocess else ''}")
    
    def _load_cache(self):
        """Carga la caché de hashes de imágenes si existe"""
        cache_dir = os.path.dirname(self.cache_file)
        os.makedirs(cache_dir, exist_ok=True)
        
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    self.image_hash_cache = cache_data.get('image_hashes', {})
                    self.image_results_cache = cache_data.get('image_results', {})
                    self.duplicate_mapping = cache_data.get('duplicate_mapping', {})
                    
                # Verificar si las rutas en la caché existen, limpiar las que no
                valid_paths = {}
                for img_path, hash_value in self.image_hash_cache.items():
                    if os.path.exists(img_path):
                        valid_paths[img_path] = hash_value
                    
                self.image_hash_cache = valid_paths
                
                # Limpiar resultados de caché para rutas que ya no existen
                valid_results = {}
                for img_path, result in self.image_results_cache.items():
                    if os.path.exists(img_path):
                        valid_results[img_path] = result
                
                self.image_results_cache = valid_results
                
                logger.info(f"Caché de imágenes cargada: {len(self.image_hash_cache)} hashes, "
                           f"{len(self.image_results_cache)} resultados, "
                           f"{len(self.duplicate_mapping)} mapeos de duplicados")
            except Exception as e:
                logger.warning(f"Error cargando caché de imágenes: {e}")
    
    def _save_cache(self):
        """Guarda la caché de hashes y resultados"""
        try:
            cache_data = {
                'image_hashes': self.image_hash_cache,
                'image_results': self.image_results_cache,
                'duplicate_mapping': self.duplicate_mapping,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Caché guardada: {len(self.image_hash_cache)} hashes, "
                       f"{len(self.image_results_cache)} resultados, "
                       f"{len(self.duplicate_mapping)} mapeos de duplicados")
        except Exception as e:
            logger.error(f"Error guardando caché: {e}")
    
    def compute_image_hash(self, image_path):
        """Calcula un hash perceptual para identificar imágenes similares"""
        try:
            # Si ya calculamos el hash antes, retornarlo directamente
            if image_path in self.image_hash_cache:
                return self.image_hash_cache[image_path]
            
            # Abrir la imagen y reducir tamaño para el hash
            with Image.open(image_path) as img:
                # Redimensionar y convertir a escala de grises
                img = img.resize((16, 16), Image.LANCZOS).convert('L')
                pixels = np.array(img.getdata(), dtype=np.float64).reshape((16, 16))
                
                # Calcular la media para generar un hash binario
                avg = pixels.mean()
                hash_value = ''.join('1' if p > avg else '0' for p in pixels.flatten())
                
                # Guardar en caché
                with self.cache_lock:
                    self.image_hash_cache[image_path] = hash_value
                
                return hash_value
        except Exception as e:
            logger.error(f"Error calculando hash para {image_path}: {e}")
            return None
    
    def estimate_image_complexity(self, image_path):
        """
        Estima la complejidad de una imagen basada en varios factores:
        1. Tamaño del archivo
        2. Detección de cantidad de texto (usando bordes y texturas)
        3. Complejidad de la imagen (variabilidad, gradientes)
        
        Retorna:
        - score de complejidad (0-1)
        - estimación de cantidad de texto
        - si la imagen debe procesarse individualmente
        """
        try:
            # 1. Obtener tamaño en MB (factor básico)
            file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
            size_score = min(file_size_mb / 5.0, 1.0)  # Normalizar, máximo 1.0
            
            # 2. Leer la imagen con OpenCV para análisis
            img = cv2.imread(image_path)
            if img is None:
                logger.warning(f"No se pudo leer la imagen para análisis de complejidad: {image_path}")
                return 0.5, 0, file_size_mb > 2.0  # Valor predeterminado moderado
            
            # Convertir a escala de grises para análisis
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # 3. Detección de bordes (Canny) - más bordes suelen indicar más texto o detalles
            edges = cv2.Canny(gray, 100, 200)
            edge_ratio = np.count_nonzero(edges) / edges.size
            
            # 4. Detección de textura (desviación estándar local)
            texture_score = np.std(gray) / 128.0  # Normalizar a aprox. 0-1
            
            # 5. Histograma de gradientes - variabilidad de la imagen
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
            mag = cv2.magnitude(gx, gy)
            gradient_score = np.mean(mag) / 128.0  # Normalizar
            
            # 6. Estimación de texto mediante características
            # Alto edge_ratio + alta textura suele indicar texto
            text_estimate = int(edge_ratio * texture_score * img.shape[0] * img.shape[1] / 50)
            
            # 7. Cálculo del score final combinando factores (pesos ajustables)
            complexity_score = (
                0.2 * size_score + 
                0.3 * edge_ratio + 
                0.3 * texture_score + 
                0.2 * gradient_score
            )
            
            # MODIFICACIÓN: Imágenes muy complejas o grandes (>3MB) se procesan individualmente
            # Las demás se procesan en lotes, independientemente de su complejidad
            needs_individual_processing = (
                complexity_score > 0.8 or  # Solo imágenes extremadamente complejas
                file_size_mb > 3.0 or      # Imágenes muy grandes
                text_estimate > 10000      # Imágenes con muchísimo texto estimado
            )
            
            logger.info(f"Complejidad de imagen {os.path.basename(image_path)}: "
                       f"score={complexity_score:.2f}, texto_est={text_estimate}, "
                       f"individual={needs_individual_processing}")
            
            return complexity_score, text_estimate, needs_individual_processing
            
        except Exception as e:
            logger.error(f"Error estimando complejidad de imagen {image_path}: {e}")
            # En caso de error, asumir que es compleja para ser conservadores
            return 0.7, 0, True
    
    def hash_distance(self, hash1, hash2):
        """Calcula la distancia de Hamming entre dos hashes"""
        if not hash1 or not hash2 or len(hash1) != len(hash2):
            return float('inf')
        
        # Distancia de Hamming (contar bits diferentes)
        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))
    
    def find_similar_images(self, image_paths, threshold=5):
        """
        Agrupa imágenes similares basadas en sus hashes perceptuales.
        Un threshold más bajo es más restrictivo (más similar).
        
        También registra los duplicados en self.duplicate_mapping para futura referencia.
        """
        # Calcular hashes para todas las imágenes
        image_hashes = {}
        for path in image_paths:
            hash_value = self.compute_image_hash(path)
            if hash_value:
                image_hashes[path] = hash_value
        
        # Agrupar imágenes por similitud
        groups = []
        processed = set()
        
        for img_path, img_hash in image_hashes.items():
            if img_path in processed:
                continue
                
            # Crear un nuevo grupo
            group = [img_path]
            processed.add(img_path)
            
            # Buscar imágenes similares
            for other_path, other_hash in image_hashes.items():
                if other_path not in processed:
                    distance = self.hash_distance(img_hash, other_hash)
                    if distance <= threshold:
                        group.append(other_path)
                        processed.add(other_path)
                        
                        # Registrar esta imagen como duplicado del representante del grupo
                        with self.cache_lock:
                            self.duplicate_mapping[other_path] = img_path
            
            groups.append(group)
        
        # Actualizar el mapeo de duplicados para todo el grupo
        if len(groups) < len(image_paths):
            logger.info(f"Deduplicación: {len(image_paths) - len(groups)} duplicados identificados")
        
        logger.info(f"Agrupamiento: {len(image_paths)} imágenes -> {len(groups)} grupos")
        return groups
    
    def process_image(self, img_path):
        """
        Procesa una imagen individual utilizando GeminiImageExtractor
        y gestiona los resultados y posibles errores.
        
        Args:
            img_path: Ruta a la imagen a procesar
            
        Returns:
            dict: Resultado del procesamiento con la información extraída
        """
        # Verificar si tenemos resultados en caché para imágenes similares
        cached_result = self._find_cached_result(img_path)
        if cached_result:
            logger.info(f"Usando resultado en caché para imagen similar: {os.path.basename(img_path)}")
            return cached_result
        
        # Obtener tamaño para logging
        file_size_mb = os.path.getsize(img_path) / (1024 * 1024)
        est_time = min(max(30, int(file_size_mb * 5)), 120)
        logger.info(f"Procesando imagen {os.path.basename(img_path)} ({file_size_mb:.2f}MB, tiempo estimado: ~{est_time}s)")
        
        start_time = time.time()
        
        try:
            # Llamar al extractor de Gemini para obtener texto
            text = self.gemini_extractor.extract_text_from_image(img_path)
            
            # Crear resultado en formato consistente
            result = {
                "image_path": img_path,
                "processed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file_size_mb": round(file_size_mb, 2),
                "detected_text": text if text else "",
                "success": bool(text),
                "processing_time_seconds": round(time.time() - start_time, 2)
            }
            
            # Guardar en caché para futuras consultas
            self._cache_result(img_path, result)
            
            proc_time = time.time() - start_time
            if result["success"]:
                logger.info(f"Imagen {os.path.basename(img_path)} procesada exitosamente en {proc_time:.2f}s")
            else:
                logger.warning(f"Imagen {os.path.basename(img_path)} procesada sin texto extraído en {proc_time:.2f}s")
            
            return result
            
        except Exception as e:
            proc_time = time.time() - start_time
            logger.error(f"Error procesando {os.path.basename(img_path)}: {str(e)}")
            
            # Crear un resultado de error
            error_result = {
                "image_path": img_path,
                "processed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e),
                "processing_time_seconds": round(proc_time, 2),
                "success": False
            }
            
            return error_result
    
    def process_image_batch_adaptive(self, batch, date_str):
        """
        Procesa un lote de imágenes con estrategia adaptativa.
        Maneja errores individualmente para cada imagen.
        
        Args:
            batch: Lista de rutas de imágenes a procesar
            date_str: Fecha para asociar con el procesamiento
            
        Returns:
            tuple: (resultados del procesamiento, tiempo de pausa recomendado)
        """
        results = []
        processing_times = []
        
        for img_path in batch:
            # Procesar imagen y capturar resultado
            result = self.process_image(img_path)
            results.append(result)
            
            # Registrar tiempo de procesamiento para ajuste adaptativo
            if "processing_time_seconds" in result:
                processing_times.append(result["processing_time_seconds"])
            else:
                # Si no hay tiempo de procesamiento, asumir un valor conservador
                processing_times.append(30)
        
        # Calcular promedio de tiempos para ajuste adaptativo
        if processing_times:
            avg_time = sum(processing_times) / len(processing_times)
            logger.info(f"Tiempo promedio de procesamiento para el lote: {avg_time:.2f}s")
            
            # Ajustar tamaño de batch según rendimiento - solo con fines informativos
            if avg_time > 30 and self.batch_size > 1:
                logger.info(f"Tiempo promedio alto: se podría reducir batch size a {max(1, self.batch_size - 1)}")
            elif avg_time < 15 and self.batch_size < 4:
                logger.info(f"Tiempo promedio bajo: se podría aumentar batch size a {self.batch_size + 1}")
            
            # Siempre usar pausa fija de 60 segundos entre lotes (según requisito)
            return results, self.short_pause
        
        # Si no hay tiempos de procesamiento, usar pausa estándar
        return results, self.short_pause
    
    def _find_cached_result(self, image_path):
        """
        Busca un resultado en caché para una imagen o sus duplicados
        
        Args:
            image_path: Ruta a la imagen a buscar
            
        Returns:
            dict: Resultado en caché o None si no existe
        """
        # Si estamos en modo forzado, siempre ignorar la caché
        if self.force_reprocess:
            return None
        
        img_hash = self.compute_image_hash(image_path)
        if not img_hash:
            return None
        
        with self.cache_lock:
            # 1. Verificar si tenemos exactamente esta imagen
            if image_path in self.image_results_cache:
                result = self.image_results_cache[image_path].copy()
                result['source'] = 'direct_cache'
                return result
            
            # 2. Verificar si es un duplicado conocido
            if image_path in self.duplicate_mapping:
                original_path = self.duplicate_mapping[image_path]
                if original_path in self.image_results_cache:
                    result = self.image_results_cache[original_path].copy()
                    result['image_path'] = image_path
                    result['based_on_similar'] = original_path
                    result['source'] = 'duplicate_mapped'
                    return result
            
            # 3. Buscar imágenes con hash similar
            for path, hash_value in self.image_hash_cache.items():
                if path != image_path and path in self.image_results_cache:
                    distance = self.hash_distance(img_hash, hash_value)
                    if distance <= 5:  # Threshold para considerar imágenes similares
                        # Crear una copia del resultado con la ruta actualizada
                        result = self.image_results_cache[path].copy()
                        result['image_path'] = image_path
                        result['based_on_similar'] = path
                        result['source'] = 'similarity_match'
                        
                        # Registrar esta similitud para futuras consultas
                        self.duplicate_mapping[image_path] = path
                        
                        return result
        
        return None
    
    def _cache_result(self, image_path, result):
        """
        Guarda un resultado en la caché y actualiza el mapeo de duplicados si es necesario
        
        Args:
            image_path: Ruta a la imagen
            result: Resultado a guardar
        """
        # Asegurar que el resultado tenga la ruta de la imagen
        if 'image_path' not in result:
            result['image_path'] = image_path
        
        # Si el resultado fue obtenido de otro similar, registrar el mapeo
        if 'based_on_similar' in result:
            with self.cache_lock:
                self.duplicate_mapping[image_path] = result['based_on_similar']
            
        with self.cache_lock:
            self.image_results_cache[image_path] = result
    
    def _save_duplicate_mapping(self, date_str):
        """
        Guarda el mapeo de duplicados en un archivo JSON para referencia y diagnóstico
        
        Args:
            date_str: Fecha en formato ddmmyyyy
        """
        if not self.duplicate_mapping:
            return
        
        try:
            # Preparar directorio
            output_dir = os.path.join(self.project_root, 'output', date_str)
            os.makedirs(output_dir, exist_ok=True)
            
            # Crear datos para guardar
            mapping_data = {
                "timestamp": datetime.now().isoformat(),
                "date_processed": date_str,
                "total_duplicates": len(self.duplicate_mapping),
                "mapping": {}
            }
            
            # Convertir las rutas completas a nombres de archivo para mejor legibilidad
            for dup_path, original_path in self.duplicate_mapping.items():
                dup_filename = os.path.basename(dup_path)
                original_filename = os.path.basename(original_path)
                mapping_data["mapping"][dup_filename] = original_filename
            
            # Guardar archivo
            output_path = os.path.join(output_dir, f"image_duplicates_{date_str}.json")
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(mapping_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Mapeo de duplicados guardado en {output_path}: {len(self.duplicate_mapping)} duplicados")
            
        except Exception as e:
            logger.error(f"Error guardando mapeo de duplicados: {e}")
    
    def process_pending_images(self, date_strs):
        """
        Procesa imágenes pendientes para las fechas especificadas.
        
        Args:
            date_strs: Lista de fechas en formato ddmmyyyy
        """
        for date_str in date_strs:
            logger.info(f"=== Procesando imágenes para fecha {date_str} ===")
            
            # Directorio de imágenes para esta fecha - ESTANDARIZAR RUTAS
            images_dir = os.path.join(self.project_root, 'output', date_str, 'images')
            output_json = os.path.join(images_dir, "texto_imagenes_api.json")
            
            # Crear directorio si no existe
            os.makedirs(images_dir, exist_ok=True)
            
            # Verificar si ya existe el archivo de resultados
            existing_results = []
            processed_paths = set()
            processed_hashes = set()  # Usar hashes además de rutas para evitar duplicados
            
            # Si estamos en modo forzado, ignoramos resultados existentes
            if self.force_reprocess:
                logger.info("Modo de reprocesamiento forzado: ignorando resultados existentes")
            elif os.path.exists(output_json) and os.path.getsize(output_json) > 0:
                logger.info(f"El archivo de resultados ya existe para {date_str}. Verificando si hay imágenes pendientes...")
                
                # Cargar resultados existentes
                try:
                    with open(output_json, 'r', encoding='utf-8') as f:
                        existing_results = json.load(f)
                    
                    # Extraer rutas e información de imágenes ya procesadas
                    for result in existing_results:
                        if 'image_path' in result:
                            processed_paths.add(result['image_path'])
                            
                            # Si tiene contenido, calcular hash de contenido para identificar duplicados
                            if 'detected_text' in result and result['detected_text']:
                                content_hash = hashlib.md5(result['detected_text'].encode('utf-8')).hexdigest()
                                processed_hashes.add(content_hash)
                    
                    logger.info(f"Cargados {len(existing_results)} resultados existentes")
                except Exception as e:
                    logger.error(f"Error leyendo archivo existente {output_json}: {e}")
            
            # Buscar todas las imágenes descargadas
            if not os.path.exists(images_dir):
                logger.warning(f"Directorio de imágenes no encontrado: {images_dir}")
                continue
                
            all_images = []
            for root, _, files in os.walk(images_dir):
                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                        img_path = os.path.join(root, file)
                        all_images.append(img_path)
            
            # Identificar imágenes pendientes considerando duplicados conocidos
            pending_images = []
            
            # Si estamos en modo forzado, todas las imágenes son "pendientes"
            if self.force_reprocess:
                pending_images = all_images
                logger.info(f"Modo forzado: reprocesando todas las {len(all_images)} imágenes")
            else:
                for img in all_images:
                    # Verificar si esta imagen ya está procesada
                    if img in processed_paths:
                        continue
                        
                    # Verificar si es un duplicado conocido que ya fue procesado
                    if img in self.duplicate_mapping:
                        original = self.duplicate_mapping[img]
                        if original in processed_paths:
                            logger.info(f"Saltando duplicado conocido: {os.path.basename(img)} -> {os.path.basename(original)}")
                            continue
                    
                    # Si llegamos aquí, la imagen necesita ser procesada
                    pending_images.append(img)
            
            if not pending_images:
                logger.info(f"No hay imágenes pendientes para {date_str}")
                continue
            
            logger.info(f"Encontradas {len(pending_images)}/{len(all_images)} imágenes" + 
                        (" para procesar" if not self.force_reprocess else " para reprocesar"))
            
            # Agrupar imágenes similares
            image_groups = self.find_similar_images(pending_images)
            
            # Seleccionar una imagen representativa de cada grupo
            representative_images = []
            for group in image_groups:
                # Elegir la más pequeña del grupo como representante
                sorted_by_size = sorted(group, key=lambda p: os.path.getsize(p))
                representative = sorted_by_size[0]
                representative_images.append(representative)
                
                # Registrar grupo para logs y actualizar mapeo de duplicados
                if len(group) > 1:
                    logger.info(f"Grupo con {len(group)} imágenes similares. Representante: {os.path.basename(representative)}")
                    
                    # Actualizar mapeo de duplicados
                    for dup in group:
                        if dup != representative:
                            with self.cache_lock:
                                self.duplicate_mapping[dup] = representative
            
            # Analizar complejidad de las imágenes y separarlas en complejas e individuales
            complex_images = []
            batch_images = []
            
            logger.info("Analizando complejidad de imágenes para separar procesamiento...")
            for img in representative_images:
                complexity_score, text_estimate, needs_individual = self.estimate_image_complexity(img)
                
                if needs_individual:
                    complex_images.append(img)
                    logger.info(f"Imagen compleja: {os.path.basename(img)} (score: {complexity_score:.2f}, texto est: {text_estimate})")
                else:
                    batch_images.append(img)
            
            logger.info(f"Clasificación: {len(complex_images)} imágenes complejas (procesamiento individual), {len(batch_images)} imágenes para batch")
            
            all_results = existing_results.copy()
            
            # 1. Primero procesar imágenes complejas individualmente
            if complex_images:
                logger.info(f"Procesando {len(complex_images)} imágenes complejas individualmente...")
                
                for idx, img in enumerate(complex_images, 1):
                    logger.info(f"Procesando imagen compleja {idx}/{len(complex_images)}: {os.path.basename(img)}")
                    
                    # Procesar individualmente
                    individual_results, pause_time = self.process_image_batch_adaptive([img], date_str)
                    all_results.extend(individual_results)
                    
                    # Guardar resultados parciales después de cada imagen compleja
                    try:
                        with open(output_json, 'w', encoding='utf-8') as f:
                            json.dump(all_results, f, ensure_ascii=False, indent=2)
                        logger.info(f"Resultados parciales guardados en {output_json} ({len(all_results)} total)")
                    except Exception as e:
                        logger.error(f"Error guardando resultados parciales: {e}")
                    
                    # Actualizar rutas procesadas para evitar duplicados en batch posterior
                    for result in individual_results:
                        if 'image_path' in result:
                            processed_paths.add(result['image_path'])
                    
                    # Pausa entre imágenes complejas (excepto la última)
                    if idx < len(complex_images):
                        logger.info(f"Pausa de {pause_time} segundos después de imagen compleja...")
                        time.sleep(pause_time)
            
            # 2. Luego procesar imágenes simples en lotes
            # Verificar que no se procesen imágenes ya tratadas en el paso 1
            batch_images = [img for img in batch_images if img not in processed_paths]
            
            if batch_images:
                logger.info(f"Procesando {len(batch_images)} imágenes regulares en lotes...")
                
                current_batch = []
                batch_count = 0
                
                for img_idx, img in enumerate(batch_images):
                    # Verificar otra vez si esta imagen es un duplicado conocido
                    if img in self.duplicate_mapping and self.duplicate_mapping[img] in processed_paths:
                        logger.info(f"Saltando duplicado detectado durante procesamiento: {os.path.basename(img)}")
                        continue
                    
                    current_batch.append(img)
                    
                    if len(current_batch) >= self.batch_size or img_idx == len(batch_images) - 1:
                        if current_batch:  # Asegurar que hay imágenes para procesar
                            batch_count += 1
                            logger.info(f"Procesando lote #{batch_count} con {len(current_batch)} imágenes")
                            
                            # Procesar lote actual
                            batch_results, pause_time = self.process_image_batch_adaptive(current_batch, date_str)
                            all_results.extend(batch_results)
                            
                            # Guardar resultados parciales después de cada lote
                            try:
                                with open(output_json, 'w', encoding='utf-8') as f:
                                    json.dump(all_results, f, ensure_ascii=False, indent=2)
                                logger.info(f"Resultados parciales guardados en {output_json} ({len(all_results)} total)")
                            except Exception as e:
                                logger.error(f"Error guardando resultados parciales: {e}")
                                # Implementar reintento en caso de error
                                time.sleep(1)
                                try:
                                    with open(output_json, 'w', encoding='utf-8') as f:
                                        json.dump(all_results, f, ensure_ascii=False, indent=2)
                                    logger.info(f"Reintento exitoso: resultados guardados en {output_json}")
                                except Exception as retry_err:
                                    logger.error(f"Error en reintento: {retry_err}")
                            
                            # Actualizar rutas procesadas
                            for result in batch_results:
                                if 'image_path' in result:
                                    processed_paths.add(result['image_path'])
                            
                            # Vaciar lote actual
                            current_batch = []
                            
                            # Pausa entre lotes (si no es el último)
                            if img_idx < len(batch_images) - 1:
                                logger.info(f"Pausa de {pause_time} segundos antes del próximo lote...")
                                time.sleep(pause_time)
            
            # 3. Procesar resultados para imágenes duplicadas
            # Esto crea entradas para las imágenes duplicadas sin tener que procesarlas
            logger.info("Generando resultados para imágenes duplicadas...")
            
            duplicates_added = 0
            for img_path in all_images:
                # Verificar si la imagen ya tiene resultado
                if img_path in processed_paths:
                    continue
                    
                # Verificar si es un duplicado conocido
                if img_path in self.duplicate_mapping:
                    original_path = self.duplicate_mapping[img_path]
                    
                    # Buscar el resultado del original
                    original_result = None
                    for result in all_results:
                        if result.get('image_path') == original_path:
                            original_result = result
                            break
                    
                    if original_result:
                        # Crear una copia del resultado original pero con la ruta de la imagen duplicada
                        duplicate_result = original_result.copy()
                        duplicate_result['image_path'] = img_path
                        duplicate_result['is_duplicate'] = True
                        duplicate_result['duplicate_of'] = original_path
                        all_results.append(duplicate_result)
                        duplicates_added += 1
            
            if duplicates_added > 0:
                logger.info(f"Añadidos {duplicates_added} resultados para imágenes duplicadas")
                
                # Guardar los resultados con las entradas de duplicados
                try:
                    with open(output_json, 'w', encoding='utf-8') as f:
                        json.dump(all_results, f, ensure_ascii=False, indent=2)
                    logger.info(f"Resultados con duplicados guardados en {output_json}")
                except Exception as e:
                    logger.error(f"Error guardando resultados con duplicados: {e}")
            
            # Guardar resultados finales (un respaldo adicional)
            try:
                with open(output_json, 'w', encoding='utf-8') as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
                logger.info(f"Procesamiento completo para {date_str}: {len(all_results)} resultados guardados en {output_json}")
            except Exception as e:
                logger.error(f"Error guardando resultados finales: {e}")
            
            # Guardar mapeo de duplicados
            self._save_duplicate_mapping(date_str)
            
            # Guardar caché actualizada
            self._save_cache()

    def download_images_parallel(self, image_links, date_str):
        """
        Método forward para mantener compatibilidad con main_with_dedup.py
        Delega la descarga de imágenes al ImageProcessor original
        
        Args:
            image_links: Lista de enlaces a imágenes
            date_str: Fecha en formato ddmmyyyy
            
        Returns:
            dict: Metadatos de las imágenes descargadas
        """
        logger.info("Delegando descarga de imágenes al ImageProcessor original")
        
        # Asegurar que el directorio de salida existe y está configurado correctamente
        output_dir = os.path.join(self.project_root, 'output', date_str, 'images')
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Directorio de salida para imágenes: {output_dir}")
        
        # Asegurar que los paths tienen el directorio correcto
        if 'paths' in self.config:
            self.config['paths']['image_download_dir'] = output_dir
        
        # Configurar el procesador de imágenes original
        self.image_processor.paths['image_download_dir'] = output_dir
        self.image_processor.paths['image_links_json'] = os.path.join(self.project_root, 'input', 'Images', f"image_links_{date_str}.json")
        
        # Ahora delegar la descarga
        return self.image_processor.download_images_parallel(image_links, date_str)

# Función principal
def main():
    # Fechas pendientes (ajustar según sea necesario)
    pending_dates = ['16042025', '17042025', '18042025', '19042025', '20042025', '21042025']
    
    # Permitir fechas como argumentos de línea de comandos
    if len(sys.argv) > 1:
        pending_dates = sys.argv[1:]
        logger.info(f"Usando fechas proporcionadas por línea de comandos: {pending_dates}")
    
    # Cargar configuración
    config_manager = get_config(project_root)
    config = config_manager.config
    
    # Inicializar procesador mejorado
    processor = EnhancedImageProcessor(config)
    
    # Procesar imágenes pendientes
    processor.process_pending_images(pending_dates)
    
    logger.info("Procesamiento de imágenes pendientes completado")

if __name__ == "__main__":
    main()
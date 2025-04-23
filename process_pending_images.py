"""
process_pending_images.py
Script para procesar imágenes pendientes con detección de duplicados y manejo de tiempos límite.
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
        self.cache_lock = Lock()
        
        # Configuración optimizada
        self.similarity_threshold = config.get('image_similarity_threshold', 0.85)
        self.max_retries = config.get('max_retries', 3)
        self.batch_size = config.get('batch_size', 3)
        self.cache_file = os.path.join(project_root, 'cache', 'image_hash_cache.json')
        
        # Cargar caché existente si está disponible
        self._load_cache()
    
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
                logger.info(f"Caché de imágenes cargada: {len(self.image_hash_cache)} hashes, {len(self.image_results_cache)} resultados")
            except Exception as e:
                logger.warning(f"Error cargando caché de imágenes: {e}")
    
    def _save_cache(self):
        """Guarda la caché de hashes y resultados"""
        try:
            cache_data = {
                'image_hashes': self.image_hash_cache,
                'image_results': self.image_results_cache,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Caché guardada: {len(self.image_hash_cache)} hashes, {len(self.image_results_cache)} resultados")
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
            
            groups.append(group)
        
        logger.info(f"Agrupamiento: {len(image_paths)} imágenes -> {len(groups)} grupos")
        return groups
    
    def process_image_batch_adaptive(self, batch, date_str):
        """
        Procesa un lote de imágenes con estrategia adaptativa:
        - Si alguna imagen toma más tiempo, reduce el tamaño del siguiente lote
        - Utiliza un timeout adaptativo basado en el tamaño de la imagen
        """
        results = []
        processing_times = []
        
        for img_path in batch:
            # Verificar si tenemos resultados en caché para imágenes similares
            cached_result = self._find_cached_result(img_path)
            if cached_result:
                logger.info(f"Usando resultado en caché para imagen similar: {img_path}")
                results.append(cached_result)
                continue
            
            # Si no hay caché, procesar la imagen
            start_time = time.time()
            retry_count = 0
            success = False
            
            # Determinar timeout adaptativo basado en tamaño
            file_size_mb = os.path.getsize(img_path) / (1024 * 1024)
            # Más tiempo para imágenes más grandes (mínimo 30s, máximo 120s)
            timeout = min(max(30, int(file_size_mb * 5)), 120)
            
            while retry_count < self.max_retries and not success:
                try:
                    # Procesar imagen con tiempo límite adaptativo
                    result = self.gemini_extractor.extract_text_from_image(img_path, timeout=timeout)
                    
                    if result and not result.get('error'):
                        success = True
                        
                        # Guardar en caché
                        self._cache_result(img_path, result)
                        
                        # Guardar resultado
                        results.append(result)
                    else:
                        # Si falló pero no hubo excepción, aumentar timeout
                        timeout *= 1.5
                        retry_count += 1
                        logger.warning(f"Reintento {retry_count}/{self.max_retries} para {img_path} con timeout {timeout}s")
                        time.sleep(2)  # Pausa breve entre reintentos
                except Exception as e:
                    retry_count += 1
                    # Backoff exponencial entre reintentos
                    wait_time = 2 ** retry_count
                    logger.error(f"Error procesando {img_path}: {e}. Reintento en {wait_time}s")
                    time.sleep(wait_time)
            
            if not success:
                logger.error(f"Falló el procesamiento de {img_path} después de {self.max_retries} intentos")
                results.append({
                    "image_path": img_path,
                    "error": f"Failed after {self.max_retries} attempts",
                    "timestamp": datetime.now().isoformat()
                })
            
            # Registrar tiempo de procesamiento
            proc_time = time.time() - start_time
            processing_times.append(proc_time)
            logger.info(f"Imagen {img_path} procesada en {proc_time:.2f}s")
        
        # Calcular promedio de tiempos para ajustar el siguiente batch
        if processing_times:
            avg_time = sum(processing_times) / len(processing_times)
            # Si el promedio supera los 30 segundos, reducir tamaño del siguiente batch
            if avg_time > 30 and self.batch_size > 1:
                self.batch_size = max(1, self.batch_size - 1)
                logger.info(f"Tiempo promedio alto ({avg_time:.2f}s): reduciendo batch size a {self.batch_size}")
            # Si el promedio es bajo, aumentar gradualmente
            elif avg_time < 15 and self.batch_size < 3:
                self.batch_size += 1
                logger.info(f"Tiempo promedio bajo ({avg_time:.2f}s): aumentando batch size a {self.batch_size}")
        
        return results
    
    def _find_cached_result(self, image_path):
        """Busca un resultado en caché para una imagen similar"""
        img_hash = self.compute_image_hash(image_path)
        if not img_hash:
            return None
        
        with self.cache_lock:
            # Primero, verificar si tenemos exactamente esta imagen
            if image_path in self.image_results_cache:
                return self.image_results_cache[image_path]
            
            # Si no, buscar imágenes con hash similar
            for path, hash_value in self.image_hash_cache.items():
                if path != image_path and path in self.image_results_cache:
                    distance = self.hash_distance(img_hash, hash_value)
                    if distance <= 5:  # Threshold para considerar imágenes similares
                        # Crear una copia del resultado con la ruta actualizada
                        result = self.image_results_cache[path].copy()
                        result['image_path'] = image_path
                        result['based_on_similar'] = path
                        return result
        
        return None
    
    def _cache_result(self, image_path, result):
        """Guarda un resultado en la caché"""
        with self.cache_lock:
            self.image_results_cache[image_path] = result
    
    def process_pending_images(self, date_strs):
        """
        Procesa imágenes pendientes para las fechas especificadas.
        
        Args:
            date_strs: Lista de fechas en formato ddmmyyyy
        """
        for date_str in date_strs:
            logger.info(f"=== Procesando imágenes para fecha {date_str} ===")
            
            # Directorio de imágenes para esta fecha
            images_dir = os.path.join(self.project_root, 'output', date_str, 'images')
            output_json = os.path.join(images_dir, "texto_imagenes_api.json")
            
            # Verificar si ya existe el archivo de resultados
            if os.path.exists(output_json) and os.path.getsize(output_json) > 0:
                logger.info(f"El archivo de resultados ya existe para {date_str}. Verificando si hay imágenes pendientes...")
                
                # Cargar resultados existentes
                try:
                    with open(output_json, 'r', encoding='utf-8') as f:
                        existing_results = json.load(f)
                except Exception as e:
                    logger.error(f"Error leyendo archivo existente {output_json}: {e}")
                    existing_results = []
                
                # Extraer rutas de imágenes ya procesadas
                processed_paths = set()
                for result in existing_results:
                    if 'image_path' in result:
                        processed_paths.add(result['image_path'])
            else:
                existing_results = []
                processed_paths = set()
            
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
            
            # Identificar imágenes pendientes
            pending_images = [img for img in all_images if img not in processed_paths]
            
            if not pending_images:
                logger.info(f"No hay imágenes pendientes para {date_str}")
                continue
                
            logger.info(f"Encontradas {len(pending_images)}/{len(all_images)} imágenes pendientes para {date_str}")
            
            # Agrupar imágenes similares
            image_groups = self.find_similar_images(pending_images)
            
            # Seleccionar una imagen representativa de cada grupo
            representative_images = []
            for group in image_groups:
                # Elegir la más pequeña del grupo como representante
                sorted_by_size = sorted(group, key=lambda p: os.path.getsize(p))
                representative = sorted_by_size[0]
                representative_images.append(representative)
                
                # Registrar grupo para logs
                if len(group) > 1:
                    logger.info(f"Grupo con {len(group)} imágenes similares. Representante: {os.path.basename(representative)}")
            
            # Procesar representantes en lotes adaptables
            logger.info(f"Procesando {len(representative_images)} imágenes representativas en lotes...")
            
            all_results = existing_results.copy()
            current_batch = []
            batch_count = 0
            
            for img in representative_images:
                current_batch.append(img)
                
                if len(current_batch) >= self.batch_size:
                    batch_count += 1
                    logger.info(f"Procesando lote #{batch_count} con {len(current_batch)} imágenes")
                    
                    # Procesar lote actual
                    batch_results = self.process_image_batch_adaptive(current_batch, date_str)
                    all_results.extend(batch_results)
                    
                    # Guardar resultados parciales después de cada lote
                    with open(output_json, 'w', encoding='utf-8') as f:
                        json.dump(all_results, f, ensure_ascii=False, indent=2)
                    
                    # Vaciar lote actual
                    current_batch = []
                    
                    # Pausa entre lotes (si no es el último)
                    if len(all_results) < len(representative_images):
                        pause_time = 60
                        logger.info(f"Pausa de {pause_time} segundos antes del próximo lote...")
                        time.sleep(pause_time)
            
            # Procesar último lote si queda alguno
            if current_batch:
                batch_count += 1
                logger.info(f"Procesando último lote #{batch_count} con {len(current_batch)} imágenes")
                batch_results = self.process_image_batch_adaptive(current_batch, date_str)
                all_results.extend(batch_results)
            
            # Guardar resultados finales
            with open(output_json, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Procesamiento completo para {date_str}: {len(all_results)} resultados guardados en {output_json}")
            
            # Guardar caché actualizada
            self._save_cache()

# Función principal
def main():
    # Fechas pendientes
    pending_dates = ['16042025', '17042025', '18042025', '19042025', '20042025', '21042025']
    
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
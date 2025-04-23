# codigo/lib/image_processor.py
import os
import requests
import logging
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Importar utilidades locales
from .cache_utils import get_cache_key, load_from_cache, save_to_cache
from .file_manager import save_to_json, ensure_dir_exists

# Intentar importar ImageTextExtractorAPI de diferentes formas para mayor compatibilidad
try:
    # Primero intenta la importación relativa (estilo paquete)
    from .image_text_extractor_api import ImageTextExtractorAPI
except ImportError:
    try:
        # Intenta importación absoluta dentro del paquete lib
        from lib.image_text_extractor_api import ImageTextExtractorAPI
    except ImportError:
        try:
            # Intenta importación absoluta desde codigo.lib
            from codigo.lib.image_text_extractor_api import ImageTextExtractorAPI
        except ImportError:
            # Implementa una clase de respaldo que registre los errores pero no falle la importación
            class ImageTextExtractorAPI:
                def __init__(self, **kwargs):
                    import logging
                    self.logger = logging.getLogger(__name__)
                    self.logger.error("No se pudo importar la verdadera ImageTextExtractorAPI. Usando implementación de respaldo.")
                    
                def extract_text_from_image(self, image_path):
                    return {
                        "error": "Módulo ImageTextExtractorAPI no disponible",
                        "image_filename": image_path if isinstance(image_path, str) else "unknown",
                        "extracted_text": ""
                    }

logger = logging.getLogger(__name__)

# --- Funciones de ayuda ---
def create_session_with_retries(retries=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504)):
    """Crea una sesión de Requests con reintentos configurados (duplicado de html_scraper, podría ir a utils)."""
    session = requests.Session()
    retry_strategy = requests.packages.urllib3.util.retry.Retry(
        total=retries, read=retries, connect=retries,
        backoff_factor=backoff_factor, status_forcelist=status_forcelist,
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class ImageProcessor:
    def __init__(self, config):
        self.config = config
        self.paths = config.get('paths', {})
        self.cache_dir = self.paths.get('cache_dir')
        self.cache_expiry = config.get('cache_expiry')
        self.session = create_session_with_retries()
        self.headers = config.get('headers', {}) # Usar headers de config (User-Agent)
        self.max_workers = config.get('max_workers', 5)

        # Inicializar cliente Gemini API
        self.api_client = None
        try:
            # Obtener configuración de API desde config
            api_config = config.get('api', {})
            api_key = api_config.get('key')
            model_name = api_config.get('model', 'gemini-1.5-pro-latest')
            prompt_key = api_config.get('prompt_key', 'detallado')
            
            # Verificar si la clase ImageTextExtractorAPI está disponible
            if 'ImageTextExtractorAPI' in globals():
                # Inicializar cliente API de Gemini
                self.api_client = ImageTextExtractorAPI(
                    api_key=api_key,
                    model_name=model_name,
                    prompt_key=prompt_key
                )
                logger.info(f"Cliente Gemini API inicializado con modelo {model_name}")
            else:
                logger.warning("Clase ImageTextExtractorAPI no disponible globalmente")
                # Intentar crear un cliente minimalista de respaldo
                self.api_client = object()
                self.api_client.extract_text_from_image = lambda image_path: {
                    "error": "Clase ImageTextExtractorAPI no disponible",
                    "image_filename": os.path.basename(image_path) if isinstance(image_path, str) else "unknown",
                    "extracted_text": ""
                }
                
        except Exception as e:
            logger.warning(f"No se pudo inicializar Gemini API: {e}")
            logger.warning("API de extracción de texto de imágenes no configurada. No se procesarán imágenes con API.")


    def download_single_image(self, url_info, image_index, date_str):
        """
        Descarga una única imagen desde una URL.
        Gestiona caché basado en la URL.
        Retorna la URL y un diccionario con metadatos o error.
        """
        url = url_info.get("URL")
        context = url_info.get("Context", "")
        output_dir = self.paths.get("image_download_dir")

        if not url or not output_dir:
            return url, {"error": "URL o directorio de salida inválido", "context": context}

        cache_key = get_cache_key(url) # Cache por URL de la imagen
        if self.cache_dir and self.cache_expiry is not None:
            cached_result = load_from_cache(self.cache_dir, cache_key, self.cache_expiry)
            if cached_result:
                # Verificar si el archivo realmente existe en la ruta cacheada
                if cached_result.get("filepath") and os.path.exists(cached_result["filepath"]):
                     logger.debug(f"Usando caché (metadata y archivo existente) para imagen {url}")
                     # Actualizar contexto si es diferente (podría cambiar entre PDFs)
                     if cached_result.get("context") != context:
                          cached_result["context"] = context
                          # Resave cache with updated context? Optional.
                     return url, cached_result
                else:
                     logger.debug(f"Cache HIT para imagen {url}, pero archivo no encontrado en {cached_result.get('filepath')}. Se redescargará.")
                     # No retornamos cache, forzamos redescarga


        result = {"context": context}
        filepath = None
        try:
            ensure_dir_exists(output_dir) # Asegura que el directorio exista
            logger.debug(f"Descargando imagen {image_index} desde {url}")

            response = self.session.get(url, headers=self.headers, timeout=30, stream=True) # stream=True para imágenes
            response.raise_for_status()

            content_type = response.headers.get('Content-Type', 'application/octet-stream').split(';')[0]
            # Extraer extensión o usar una por defecto
            extension = ".jpg" # Por defecto
            if '/' in content_type:
                 ext_candidate = content_type.split('/')[-1]
                 # Validar extensiones comunes, evitar cosas raras
                 valid_exts = ['jpeg', 'jpg', 'png', 'gif', 'bmp', 'webp', 'svg', 'tiff']
                 if ext_candidate in valid_exts:
                     extension = "." + ext_candidate.replace('jpeg', 'jpg') # Normalizar jpeg a jpg

            # Crear nombre de archivo único y seguro
            # Usar parte del hash de la URL para evitar colisiones si el índice no es suficiente
            url_hash_part = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"img_{image_index}_{url_hash_part}_{date_str}{extension}"
            filepath = os.path.join(output_dir, filename)

            # Descargar contenido
            downloaded_size = 0
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192): # Descargar en chunks
                    if chunk: # filter out keep-alive new chunks
                        f.write(chunk)
                        downloaded_size += len(chunk)

            logger.info(f"Imagen {image_index} guardada como '{filename}' en {output_dir} ({downloaded_size} bytes)")

            result.update({
                "filepath": filepath,
                "filename": filename,
                "content_type": content_type,
                "size": downloaded_size, # Tamaño real descargado
                "download_timestamp": datetime.now().isoformat()
            })

            # Guardar resultado en caché si es exitoso
            if self.cache_dir:
                save_to_cache(self.cache_dir, cache_key, result)

            # Pausa
            time.sleep(random.uniform(0.2, 0.8))


        except requests.exceptions.Timeout:
            logger.warning(f"Timeout descargando imagen {url}")
            result["error"] = "Timeout"
        except requests.exceptions.HTTPError as e:
             logger.warning(f"Error HTTP {e.response.status_code} descargando imagen {url}: {e}")
             result["error"] = f"HTTP Error: {e.response.status_code}"
        except requests.exceptions.RequestException as e:
            logger.warning(f"Error de red descargando imagen {url}: {e}")
            result["error"] = f"Network Error: {str(e)}"
        except Exception as e:
            logger.error(f"Error inesperado descargando imagen {url}: {e}", exc_info=True)
            result["error"] = f"Unexpected Error: {str(e)}"
            # Si hubo error y se creó archivo parcial, eliminarlo
            if filepath and os.path.exists(filepath):
                 try:
                     os.remove(filepath)
                     logger.debug(f"Archivo parcial eliminado: {filepath}")
                 except OSError:
                      logger.warning(f"No se pudo eliminar el archivo parcial: {filepath}")


        return url, result

    def download_images_parallel(self, image_links, date_str):
        """
        Descarga una lista de imágenes (diccionarios de link_info) en paralelo.
        Retorna un diccionario {url: metadata} de las imágenes descargadas.
        """
        if not image_links:
            logger.info("No hay enlaces de imágenes para descargar.")
            return {}

        total_images = len(image_links)
        processed_count = 0
        downloaded_metadata = {}
        start_time = time.time()

        logger.info(f"Iniciando descarga paralela de {total_images} imágenes para la fecha {date_str}...")
        output_json_path = self.paths.get("image_links_json") # Path para guardar metadata

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {
                # Pasar índice y fecha a la función de descarga
                executor.submit(self.download_single_image, link_info, idx, date_str): link_info
                for idx, link_info in enumerate(image_links, 1)
            }

            for future in as_completed(future_to_url):
                link_info_orig = future_to_url[future]
                url_orig = link_info_orig.get("URL")
                processed_count += 1
                try:
                    url_processed, metadata = future.result()
                    downloaded_metadata[url_orig] = metadata # Usar URL original como clave
                    if "error" in metadata:
                        logger.warning(f"Error procesando imagen {url_orig}: {metadata['error']}")
                    else:
                        logger.debug(f"Procesada imagen {url_orig} exitosamente.")

                except Exception as e:
                    logger.error(f"Error procesando futuro de imagen para {url_orig}: {e}", exc_info=True)
                    downloaded_metadata[url_orig] = {"error": f"Future processing failed: {str(e)}", "context": link_info_orig.get("Context")}

                if processed_count % 10 == 0 or processed_count == total_images:
                    elapsed = time.time() - start_time
                    logger.info(f"Progreso descarga imágenes: {processed_count}/{total_images} en {elapsed:.2f} seg.")

        # Guardar la metadata de las imágenes descargadas (o con error)
        if output_json_path:
            save_to_json(downloaded_metadata, output_json_path)
        else:
             logger.warning("No se especificó ruta para guardar metadata de imágenes descargadas.")

        end_time = time.time()
        logger.info(f"Descarga de imágenes completada para {processed_count}/{total_images} URLs en {end_time - start_time:.2f} segundos.")

        return downloaded_metadata

    def process_downloaded_images_with_api(self, downloaded_metadata):
        """
        Procesa las imágenes que se descargaron correctamente utilizando la API externa.
        Gestiona caché basado en el hash del contenido de la imagen.
        Procesa máximo 3 imágenes y hace una pausa de 60 segundos entre lotes.
        Retorna una lista de resultados de la API.
        """
        if not self.api_client:
             logger.warning("Cliente API no inicializado. Saltando procesamiento de texto de imágenes.")
             return []
        if not downloaded_metadata:
             logger.info("No hay metadatos de imágenes descargadas para procesar con API.")
             return []

        images_to_process = []
        for url, meta in downloaded_metadata.items():
             if "error" not in meta and meta.get("filepath") and os.path.exists(meta["filepath"]):
                 images_to_process.append(meta) # Añadir metadatos completos

        if not images_to_process:
             logger.info("No se encontraron imágenes descargadas válidas para procesar con API.")
             return []

        total_images = len(images_to_process)
        processed_count = 0
        api_results = []
        start_time = time.time()
        batch_start_time = time.time()

        logger.info(f"Iniciando procesamiento con API para {total_images} imágenes...")
        output_json_path = self.paths.get("image_api_results_json") # Path para guardar resultados API

        # Procesar imágenes en lotes de 3 (o 2 si el procesamiento es extenso)
        max_batch_size = 3
        current_batch = []
        batch_number = 1
        
        # Clasificar imágenes por tamaño para estimar complejidad
        small_images = []
        large_images = []
        for meta in images_to_process:
            # Si el tamaño está disponible en los metadatos
            file_size_mb = meta.get('size', 0) / (1024 * 1024) if 'size' in meta else 0
            
            # Si no está disponible, intentar obtener del sistema de archivos
            if file_size_mb <= 0 and os.path.exists(meta.get('filepath', '')):
                try:
                    file_size_mb = os.path.getsize(meta['filepath']) / (1024 * 1024)
                except:
                    # Si falla, asumir que es una imagen grande
                    file_size_mb = 5  # Asumir 5MB

            # Clasificar
            if file_size_mb > 1.5:  # Si es mayor a 1.5MB, considerar "grande"
                large_images.append(meta)
            else:
                small_images.append(meta)
        
        # Primero procesar imágenes pequeñas (en lotes de 3)
        logger.info(f"Procesando primero {len(small_images)} imágenes pequeñas (en lotes de 3)...")
        for meta in small_images:
            current_batch.append(meta)
            
            # Procesar el lote cuando alcanza el tamaño máximo o es el último elemento
            if len(current_batch) >= max_batch_size or meta == small_images[-1]:
                logger.info(f"Procesando lote #{batch_number} con {len(current_batch)} imágenes pequeñas")
                batch_results = []
                
                # Procesar cada imagen en el lote
                for batch_meta in current_batch:
                    result = self._process_single_image_api_with_cache(batch_meta)
                    processed_count += 1
                    
                    if result:
                        batch_results.append(result)
                        api_results.append(result)
                        
                        if result.get("error"):
                            logger.warning(f"Error de API procesando {batch_meta.get('filename', 'N/A')}: {result['error']}")
                        else:
                            logger.info(f"[{processed_count}/{total_images}] Procesada imagen con API: {batch_meta.get('filename', 'N/A')}")
                
                # Verificar y mostrar progreso
                batch_duration = time.time() - batch_start_time
                logger.info(f"Lote #{batch_number} completado en {batch_duration:.2f} seg. ({len(batch_results)} imágenes)")
                
                # Pausa de 60 segundos entre lotes, excepto en el último lote de imágenes pequeñas
                if meta != small_images[-1] or len(large_images) > 0:
                    logger.info(f"Pausa de 60 segundos antes del próximo lote...")
                    time.sleep(60)
                
                # Reiniciar para el próximo lote
                current_batch = []
                batch_number += 1
                batch_start_time = time.time()
        
        # Luego procesar imágenes grandes (en lotes de 2)
        if large_images:
            logger.info(f"Procesando {len(large_images)} imágenes grandes (en lotes de 2)...")
            max_batch_size = 2  # Reducir tamaño del lote para imágenes grandes
            current_batch = []
            
            for meta in large_images:
                current_batch.append(meta)
                
                # Procesar el lote cuando alcanza el tamaño máximo o es el último elemento
                if len(current_batch) >= max_batch_size or meta == large_images[-1]:
                    logger.info(f"Procesando lote #{batch_number} con {len(current_batch)} imágenes grandes")
                    batch_results = []
                    
                    # Procesar cada imagen en el lote
                    for batch_meta in current_batch:
                        result = self._process_single_image_api_with_cache(batch_meta)
                        processed_count += 1
                        
                        if result:
                            batch_results.append(result)
                            api_results.append(result)
                            
                            if result.get("error"):
                                logger.warning(f"Error de API procesando {batch_meta.get('filename', 'N/A')}: {result['error']}")
                            else:
                                logger.info(f"[{processed_count}/{total_images}] Procesada imagen grande con API: {batch_meta.get('filename', 'N/A')}")
                    
                    # Verificar y mostrar progreso
                    batch_duration = time.time() - batch_start_time
                    logger.info(f"Lote #{batch_number} completado en {batch_duration:.2f} seg. ({len(batch_results)} imágenes grandes)")
                    
                    # Pausa de 60 segundos entre lotes, excepto en el último lote
                    if meta != large_images[-1]:
                        logger.info(f"Pausa de 60 segundos antes del próximo lote...")
                        time.sleep(60)
                    
                    # Reiniciar para el próximo lote
                    current_batch = []
                    batch_number += 1
                    batch_start_time = time.time()

        # Guardar los resultados de la API
        if output_json_path and api_results:
             save_to_json(api_results, output_json_path)
             logger.info(f"Resultados de API guardados en: {output_json_path}")
        else:
              logger.warning("No se especificó ruta para guardar resultados de la API de imágenes o no hay resultados.")

        end_time = time.time()
        logger.info(f"Procesamiento API completado para {processed_count}/{total_images} imágenes en {end_time - start_time:.2f} segundos.")

        return api_results

    def _process_single_image_api_with_cache(self, image_meta):
         """
         Wrapper para llamar a la API para una imagen, usando caché basado en hash de archivo.
         """
         filepath = image_meta.get("filepath")
         if not filepath or not os.path.exists(filepath):
              logger.warning(f"Archivo no encontrado para procesar con API: {filepath}")
              return None # O un dict de error

         # Calcular hash del contenido del archivo para la clave de caché
         try:
             with open(filepath, 'rb') as f:
                 image_bytes = f.read()
             if not image_bytes:
                  logger.warning(f"Archivo de imagen vacío: {filepath}")
                  return None
             cache_key = get_cache_key(image_bytes) # Clave basada en contenido
         except Exception as e:
              logger.error(f"Error leyendo archivo o calculando hash para {filepath}: {e}")
              return None # No se puede procesar sin hash

         # Verificar caché
         if self.cache_dir and self.cache_expiry is not None:
              cached_result = load_from_cache(self.cache_dir, f"gemini_{cache_key}", self.cache_expiry) # Prefijo específico para Gemini
              if cached_result:
                  # Comprobar si es un error permanente (imagen demasiado pesada)
                  if cached_result.get("_permanent_error"):
                      logger.info(f"OMITIENDO PERMANENTEMENTE: Imagen {image_meta.get('filename')} - {cached_result.get('_error_reason', 'Marcada como no procesable')}")
                  else:
                      logger.debug(f"Usando caché API para imagen {image_meta.get('filename')}")
                  
                  # Asegurar que campos esperados estén presentes
                  cached_result.setdefault('image_filename', image_meta.get('filename'))
                  cached_result.setdefault('processed_date', datetime.today().strftime('%d%m%Y'))
                  cached_result.setdefault('extracted_text', '')
                  cached_result.setdefault('error', None)
                  return cached_result

         # Si no está en caché, llamar a la API
         logger.debug(f"Llamando a API de Gemini para imagen {image_meta.get('filename')} (no en caché o expirado)")
         api_result = self.api_client.extract_text_from_image(filepath)

         # Implementar pacing para Gemini API (evitar límites de cuota)
         wait_time = random.uniform(5, 15)  # Entre 5 y 15 segundos entre solicitudes
         logger.debug(f"Esperando {wait_time:.2f} segundos antes de la siguiente solicitud a Gemini API")
         time.sleep(wait_time)

         # Guardar en caché tanto éxitos como errores
         if self.cache_dir and api_result:
             # Cachear por tiempo diferente según éxito o error
             if api_result.get("error"):
                 error_msg = api_result.get("error", "").lower()
                 # Verificar si el error indica que la imagen es demasiado pesada
                 image_too_large = any(term in error_msg for term in [
                     "timeout", "too large", "too big", "size limit", 
                     "demasiado grande", "demasiado pesada", "limits exceeded",
                     "memory", "memoria", "out of", "unable to process",
                     "quota", "rate limit", "rate-limit"
                 ])
                 
                 # Marcar en el cache que esto es un error
                 api_result["_cache_error"] = True
                 
                 if image_too_large:
                     # Para imágenes demasiado pesadas, cachear permanentemente (10 años en segundos)
                     permanent_seconds = 315360000  # 10 años
                     api_result["_permanent_error"] = True
                     api_result["_error_reason"] = "Imagen demasiado pesada o compleja para procesar"
                     logger.warning(f"Imagen {image_meta.get('filename')} marcada como PERMANENTEMENTE no procesable (demasiado pesada/compleja)")
                     save_to_cache(self.cache_dir, f"gemini_{cache_key}", api_result, expiry_seconds=permanent_seconds)
                 else:
                     # Errores normales se cachean temporalmente (1 hora)
                     one_hour_seconds = 3600
                     logger.debug(f"Cacheando error de API para {image_meta.get('filename')} por 1 hora")
                     save_to_cache(self.cache_dir, f"gemini_{cache_key}", api_result, expiry_seconds=one_hour_seconds)
             else:
                 logger.debug(f"Cacheando respuesta exitosa de API para {image_meta.get('filename')}")
                 save_to_cache(self.cache_dir, f"gemini_{cache_key}", api_result)

         return api_result
    
    def list_permanently_skipped_images(self):
        """
        Lista todas las imágenes que están marcadas como permanentemente no procesables.
        Útil para diagnóstico o para decidir si forzar su reprocesamiento.
        
        Returns:
            list: Lista de diccionarios con información sobre imágenes omitidas permanentemente
        """
        if not self.cache_dir or not os.path.exists(self.cache_dir):
            logger.warning("Directorio de caché no encontrado")
            return []
        
        skipped_images = []
        try:
            # Buscar todos los archivos de caché de API (gemini_ o api_)
            for filename in os.listdir(self.cache_dir):
                if (filename.startswith("gemini_") or filename.startswith("api_")) and filename.endswith(".json"):
                    cache_path = os.path.join(self.cache_dir, filename)
                    try:
                        with open(cache_path, 'r', encoding='utf-8') as f:
                            cache_data = json.load(f)
                            content = cache_data.get('content', {})
                            # Verificar si es un error permanente
                            if content and content.get('_permanent_error'):
                                skipped_images.append({
                                    "cache_file": filename,
                                    "image_filename": content.get('image_filename', 'Desconocido'),
                                    "reason": content.get('_error_reason', 'Razón no especificada'),
                                    "error": content.get('error', 'Error no especificado'),
                                    "timestamp": cache_data.get('timestamp'),
                                    "api_type": "gemini" if filename.startswith("gemini_") else "agentic"
                                })
                    except Exception as e:
                        logger.debug(f"Error leyendo archivo de caché {filename}: {e}")
            
            return skipped_images
        except Exception as e:
            logger.error(f"Error listando imágenes omitidas: {e}")
            return []
    
    def clear_skipped_image(self, image_filename):
        """
        Elimina una imagen de la lista de permanentemente omitidas para permitir su reprocesamiento.
        
        Args:
            image_filename: Nombre del archivo de imagen a eliminar de la lista
            
        Returns:
            bool: True si se encontró y eliminó, False en caso contrario
        """
        if not self.cache_dir or not os.path.exists(self.cache_dir):
            return False
        
        try:
            skipped_images = self.list_permanently_skipped_images()
            for img_info in skipped_images:
                if img_info["image_filename"] == image_filename:
                    cache_path = os.path.join(self.cache_dir, img_info["cache_file"])
                    if os.path.exists(cache_path):
                        os.remove(cache_path)
                        logger.info(f"Eliminada imagen {image_filename} de la lista de omitidas permanentemente")
                        return True
            
            logger.warning(f"No se encontró {image_filename} en la lista de omitidas permanentemente")
            return False
        except Exception as e:
            logger.error(f"Error eliminando imagen de la lista de omitidas: {e}")
            return False


# Import hashlib aquí si no está global
import hashlib
import json  # Asegurar que json está importado
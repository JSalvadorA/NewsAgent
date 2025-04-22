# codigo/lib/image_processor.py
import os
import requests
import logging
import time
import random
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import imghdr
import imagehash
from PIL import Image
import hashlib
import json

# Importar utilidades locales
from .cache_utils import get_cache_key, load_from_cache, save_to_cache
from .file_manager import save_to_json, ensure_dir_exists
from .api_client import ImageTextExtractorAPI # Importar cliente API
from .request_utils import get_session

# Verificaciones rápidas de tipo de archivo de imagen y hash

def is_valid_image(filepath):
    """
    Verifica rápidamente si un archivo es una imagen válida.
    Retorna una tupla (es_imagen, formato_detectado)
    """
    try:
        # Verificación rápida usando imghdr (más eficiente que abrir la imagen completa)
        img_format = imghdr.what(filepath)
        if img_format:
            return True, img_format
        
        # Verificación secundaria con PIL si imghdr no lo reconoce
        try:
            with Image.open(filepath) as img:
                return True, img.format.lower()
        except Exception:
            pass
        
        # No es una imagen reconocible
        return False, None
    except Exception as e:
        return False, str(e)

def fast_hash_file(filepath):
    """
    Calcula un hash rápido para un archivo.
    Usa un método más eficiente para archivos grandes combinando 'head+tail'.
    Retorna el hash como string o None si hay error.
    """
    try:
        # Para archivos pequeños (<1MB), usar hash completo
        file_size = os.path.getsize(filepath)
        
        if file_size < 1024 * 1024:  # 1MB
            # Hash completo para archivos pequeños
            hasher = hashlib.md5()
            with open(filepath, 'rb') as f:
                buf = f.read(65536)  # Leer en chunks de 64KB
                while len(buf) > 0:
                    hasher.update(buf)
                    buf = f.read(65536)
            return hasher.hexdigest()
        else:
            # Para archivos grandes, combinar hash de inicio + fin + tamaño
            # Esto es mucho más rápido y sigue siendo efectivo para detección de duplicados
            hasher = hashlib.md5()
            with open(filepath, 'rb') as f:
                # Leer primeros 256KB
                head = f.read(262144)
                hasher.update(head)
                
                # Saltar al final y leer últimos 256KB
                f.seek(-262144, os.SEEK_END)
                tail = f.read(262144)
                hasher.update(tail)
                
                # Añadir el tamaño del archivo al hash para diferenciación
                hasher.update(str(file_size).encode())
                
            return hasher.hexdigest()
    except Exception as e:
        logger.debug(f"Error calculando hash para {filepath}: {e}")
        return None

def identify_file_type(filepath):
    """
    Identifica el tipo de archivo basado en el contenido/cabecera.
    Más preciso que depender solo de la extensión.
    """
    try:
        # Verificar si es imagen primero
        is_img, format_detected = is_valid_image(filepath)
        if is_img:
            return f"image/{format_detected.lower()}"
            
        # Leer los primeros bytes para identificar tipo
        with open(filepath, 'rb') as f:
            header = f.read(16)  # Primeros 16 bytes para identificación
            
        # Identificar por firmas de archivo comunes
        signatures = {
            b'%PDF': 'application/pdf',
            b'PK\x03\x04': 'application/zip',
            b'\xff\xd8\xff': 'image/jpeg',
            b'\x89PNG\r\n\x1a\n': 'image/png',
            b'GIF87a': 'image/gif',
            b'GIF89a': 'image/gif',
            b'RIFF': 'audio/wav',  # También podría ser video/avi
            b'ID3': 'audio/mpeg',
            b'\x00\x00\x00 ftypmp4': 'video/mp4',
            b'\x1aE\xdf\xa3': 'video/webm',
        }
        
        for signature, mime_type in signatures.items():
            if header.startswith(signature):
                return mime_type
                
        # Si no se reconoce, intentar por extensión
        ext = os.path.splitext(filepath)[1].lower()
        ext_to_mime = {
            '.txt': 'text/plain',
            '.csv': 'text/csv',
            '.json': 'application/json',
            '.html': 'text/html',
            '.htm': 'text/html',
            '.xml': 'application/xml',
            '.mp3': 'audio/mpeg',
            '.mp4': 'video/mp4',
            '.avi': 'video/x-msvideo',
            '.mov': 'video/quicktime',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.pdf': 'application/pdf',
        }
        
        if ext in ext_to_mime:
            return ext_to_mime[ext]
            
        # En último caso, retornar tipo genérico
        return 'application/octet-stream'
    except Exception as e:
        logger.debug(f"Error identificando tipo de archivo {filepath}: {e}")
        return 'application/octet-stream'

logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self, config):
        self.config = config
        self.paths = config.get('paths', {})
        self.cache_dir = self.paths.get('cache_dir')
        self.cache_expiry = config.get('cache_expiry')
        self.session = get_session()  # Usar sesión global compartida
        self.headers = config.get('headers', {}) # Usar headers de config (User-Agent)
        self.max_workers = config.get('max_workers', 5)

        # Inicializar cliente Gemini API
        try:
            # Obtener configuración de API desde config
            api_config = config.get('api', {})
            api_key = api_config.get('key')
            model_name = api_config.get('model', 'gemini-1.5-pro-latest')
            prompt_key = api_config.get('prompt_key', 'detallado')
            
            # Inicializar cliente API de Gemini
            self.api_client = ImageTextExtractorAPI(
                api_key=api_key,
                model_name=model_name,
                prompt_key=prompt_key
            )
            logger.info(f"Cliente Gemini API inicializado con modelo {model_name}")
        except Exception as e:
            self.api_client = None
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
            
            # Verificar si el tipo de contenido es efectivamente una imagen
            is_image = False
            if content_type.startswith('image/'):
                is_image = True
            elif content_type in ['application/octet-stream', 'binary/octet-stream']:
                # Si el servidor no especifica bien el tipo, intentamos adivinar por la extensión
                path_lower = urlparse(url).path.lower()
                is_image = any(path_lower.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'])
            
            # Si definitivamente NO es una imagen, registrar un error
            if not is_image and any(content_type.startswith(prefix) for prefix in ['audio/', 'video/']):
                logger.warning(f"URL {url} contiene {content_type}, no una imagen. Se registrará como tipo no válido.")
                result["error"] = f"Content type '{content_type}' is not an image"
                result["content_type"] = content_type
                # No retornamos aqui - seguimos con la descarga pero registramos que no es imagen
            
            # Determinar mejor extensión basada en el content-type y la URL
            extension = ".jpg"  # Por defecto
            
            # 1. Primero intentar extraer de content-type
            if '/' in content_type:
                mime_type = content_type.split('/')[-1]
                # Mapa de tipos MIME a extensiones
                mime_to_ext = {
                    'jpeg': '.jpg',
                    'jpg': '.jpg',
                    'png': '.png',
                    'gif': '.gif',
                    'bmp': '.bmp',
                    'webp': '.webp',
                    'tiff': '.tiff',
                    'svg+xml': '.svg',
                    # Tipos de audio (en caso de que se descarguen)
                    'mpeg': '.mp3',
                    'mp3': '.mp3',
                    'ogg': '.ogg',
                    'wav': '.wav',
                    'x-wav': '.wav',
                    'x-m4a': '.m4a',
                    'mp4': '.mp4',
                }
                
                if mime_type in mime_to_ext:
                    extension = mime_to_ext[mime_type]
            
            # 2. Si no es conclusivo, intentar extraer de la URL
            url_path = urlparse(url).path.lower()
            url_extensions = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".tiff",
                              ".mp3", ".wav", ".ogg", ".m4a", ".mp4"]
            
            for ext in url_extensions:
                if url_path.endswith(ext):
                    # Si es .jpeg, normalizarlo a .jpg
                    if ext == ".jpeg":
                        extension = ".jpg"
                    else:
                        extension = ext
                    break

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
        
        # Detector de URLs duplicadas
        url_to_index = {}  # Mapeo de URL a índice para detectar duplicados
        processed_urls = set()  # URLs ya procesadas
        
        start_time = time.time()

        logger.info(f"Iniciando descarga paralela de {total_images} imágenes para la fecha {date_str}...")
        output_json_path = self.paths.get("image_links_json") # Path para guardar metadata
        
        # Primero identificar duplicados para evitar descargas múltiples
        for idx, link_info in enumerate(image_links, 1):
            url = link_info.get("URL")
            if url in url_to_index:
                logger.warning(f"URL duplicada detectada: {url}. Primera ocurrencia: #{url_to_index[url]}, segunda: #{idx}")
            else:
                url_to_index[url] = idx

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {}
            
            # Solo procesar URLs únicas
            for idx, link_info in enumerate(image_links, 1):
                url_orig = link_info.get("URL")
                
                # Saltarse URLs duplicadas ya procesadas
                if url_orig in processed_urls:
                    logger.info(f"Omitiendo URL duplicada #{idx}: {url_orig}")
                    continue
                    
                processed_urls.add(url_orig)
                future_to_url[executor.submit(self.download_single_image, link_info, idx, date_str)] = link_info

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
        Procesa imágenes descargadas usando API de extracción de texto de imágenes.
        Implementa procesamiento adaptativo con control de batch_size y reintentos.
        
        Args:
            downloaded_metadata (dict): Metadatos de imágenes descargadas {url: {filepath, filename, ...}}
            
        Returns:
            list: Lista de resultados de API para cada imagen
        """
        if not downloaded_metadata:
            logger.warning("No hay metadatos de imágenes para procesar con la API.")
            return []
            
        if not self.api_client:
            logger.error("API de extracción de texto de imágenes no inicializada. Verifica la clave API.")
            # Devolver errores estructurados para todas las imágenes
            return [
                {
                    "image_filename": meta.get("filename", os.path.basename(meta.get("filepath", "unknown"))),
                    "processed_date": datetime.today().strftime('%d%m%Y'),
                    "extracted_text": "",
                    "error": "API client not initialized. Check if API key is valid and configured.",
                    "_cache_error": True,
                    "_api_configuration_error": True
                }
                for url, meta in downloaded_metadata.items()
            ]

        # Verificar disponibilidad de API con imagen de prueba
        api_available = self._verify_api_availability()
        if not api_available:
            logger.error("API de Gemini no está disponible o la clave API es inválida. Las imágenes no serán procesadas correctamente.")
            # Devolver errores estructurados para todas las imágenes
            return [
                {
                    "image_filename": meta.get("filename", os.path.basename(meta.get("filepath", "unknown"))),
                    "processed_date": datetime.today().strftime('%d%m%Y'),
                    "extracted_text": "",
                    "error": "API key not valid or service unavailable. Check your API configuration.",
                    "_cache_error": True,
                    "_api_configuration_error": True
                }
                for url, meta in downloaded_metadata.items()
            ]
        
        # Resto del código sin cambios
        start_time = time.time()
        total_images = len(downloaded_metadata)
        processed_count = 0
        
        # Recuperar configuración de API desde config
        api_config = self.config.get('api', {})
        batch_size = int(api_config.get('batch_size', 3))
        pause_seconds = int(api_config.get('pause_seconds', 60))
        
        # Asegurar valores razonables
        batch_size = max(1, min(batch_size, 5))  # Entre 1 y 5
        pause_seconds = max(10, min(pause_seconds, 300))  # Entre 10 y 300 segundos
        
        logger.info(f"Procesando {total_images} imágenes con API (batch_size={batch_size}, pausa={pause_seconds}s)")
        api_results = []
        
        # Dividir en batches secuenciales para procesamiento adaptativo
        items = list(downloaded_metadata.items())
        batch_count = 0
        
        # Seguimiento de imágenes que fallaron en primer intento (para reintentar)
        failed_items = []
        
        # Procesar en batches secuenciales
        while items:
            batch_count += 1
            current_batch = items[:batch_size]
            items = items[batch_size:]
            
            logger.info(f"Procesando batch {batch_count} ({len(current_batch)} imágenes)")
            batch_results = []
            
            # Procesar cada imagen en el batch
            for url, meta in current_batch:
                filepath = meta.get("filepath")
                filename = meta.get("filename")
                
                if not filepath or not os.path.exists(filepath):
                    logger.warning(f"Archivo no encontrado: {filepath}")
                    result = {
                        "image_filename": filename if filename else "unknown",
                        "processed_date": datetime.today().strftime('%d%m%Y'),
                        "extracted_text": "",
                        "error": "File not found",
                        "_cache_error": True
                    }
                else:
                    logger.info(f"Procesando imagen con API: {filename}")
                    result = self._process_single_image_api_with_cache(meta)
                    
                # Verificar resultado
                if result.get("error"):
                    logger.warning(f"Error procesando imagen {filename}: {result.get('error')}")
                else:
                    processed_count += 1
                    logger.info(f"Imagen procesada exitosamente: {filename}")
                
                # Añadir a resultados
                result["url"] = url
                batch_results.append(result)
                
                # Opcional: pequeña pausa entre imágenes del mismo batch
                time.sleep(random.uniform(0.5, 1))
            
            # Añadir resultados del batch
            api_results.extend(batch_results)
            
            # Verificar si hay más batches o reintentos pendientes
            is_last_batch = not items and not failed_items
            
            if not is_last_batch:
                wait_time = pause_seconds
                logger.info(f"Pausa de {wait_time}s antes del siguiente batch...")
                time.sleep(wait_time)
                
                # Si no hay más items pero hay fallos, procesar reintentos
                if not items and failed_items:
                    logger.info(f"Reintentando {len(failed_items)} imágenes que fallaron...")
                    items = failed_items
                    failed_items = []
        
        # Guardar resultados en archivo JSON
        output_json_path = self.paths.get("image_api_results_json")
        if output_json_path:
            # Eliminar las URLs de resultados finales (no son necesarias en el archivo)
            clean_results = []
            for res in api_results:
                res_copy = res.copy()
                if "url" in res_copy:
                    del res_copy["url"]
                clean_results.append(res_copy)
                
            save_to_json(clean_results, output_json_path)
            logger.info(f"Resultados de API guardados en: {output_json_path}")
        else:
              logger.warning("No se especificó ruta para guardar resultados de la API de imágenes o no hay resultados.")

        end_time = time.time()
        logger.info(f"Procesamiento API completado para {processed_count}/{total_images} imágenes en {end_time - start_time:.2f} segundos.")

        return api_results
        
    def _verify_api_availability(self):
        """
        Verifica que la API de Gemini esté disponible con una pequeña imagen de prueba.
        Esto detecta problemas de configuración de API antes de procesar todas las imágenes.
        
        Returns:
            bool: True si la API está disponible, False si no
        """
        if not self.api_client:
            logger.error("Cliente API no inicializado")
            return False
            
        try:
            # Crear una pequeña imagen de prueba en memoria
            from PIL import Image, ImageDraw
            import tempfile
            
            # Crear imagen temporal de prueba
            temp_img = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            temp_path = temp_img.name
            temp_img.close()
            
            try:
                # Crear una imagen simple de 100x100 píxeles
                img = Image.new('RGB', (100, 100), color=(255, 255, 255))
                draw = ImageDraw.Draw(img)
                draw.text((10, 40), "TEST", fill=(0, 0, 0))
                img.save(temp_path)
                
                # Intentar procesar la imagen de prueba
                test_result = self.api_client.extract_text_from_image(temp_path)
                
                # Verificar el resultado
                if test_result.get("error"):
                    if "API key not valid" in str(test_result.get("error")):
                        logger.error("Error de API key inválida: " + str(test_result.get("error")))
                        return False
                    else:
                        logger.warning(f"Error en prueba de API, pero no parece ser de configuración: {test_result.get('error')}")
                        return True  # Continuamos porque podría ser un error específico de la imagen
                return True
            finally:
                # Limpiar archivo temporal
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except Exception:
                    pass
                    
        except Exception as e:
            logger.error(f"Error verificando disponibilidad de API: {e}")
            return False
    
    def check_results_have_only_errors(self, results):
        """
        Verifica si un conjunto de resultados de API contiene solo errores.
        
        Args:
            results (list): Lista de resultados de API
            
        Returns:
            tuple: (solo_errores, errores_api_key)
                - solo_errores: True si todos los resultados contienen errores
                - errores_api_key: True si hay errores específicos de API key
        """
        if not results:
            return False, False
            
        all_have_errors = all('error' in result for result in results)
        api_key_errors = any("API key not valid" in str(result.get('error', '')) for result in results)
        
        return all_have_errors, api_key_errors

    def _process_single_image_api_with_cache(self, image_meta):
         """
         Wrapper optimizado para llamar a la API para una imagen, usando caché basado en hash de archivo.
         Implementa comprobaciones eficientes de imágenes y cachés mejorados.
         """
         filepath = image_meta.get("filepath")
         if not filepath or not os.path.exists(filepath):
              logger.warning(f"Archivo no encontrado para procesar con API: {filepath}")
              return {
                 "image_filename": os.path.basename(filepath) if filepath else "desconocido",
                 "processed_date": datetime.today().strftime('%d%m%Y'),
                 "extracted_text": "",
                 "error": "File not found",
                 "_cache_error": True
              }
        
         # Verificar el tamaño antes de procesar (evitar procesamiento innecesario)
         try:
             file_size = os.path.getsize(filepath)
             # Umbral para imágenes demasiado grandes (10MB para este ejemplo)
             if file_size > 10 * 1024 * 1024:
                 logger.warning(f"Archivo demasiado grande para procesar eficientemente: {filepath} ({file_size/1024/1024:.2f} MB)")
                 return {
                     "image_filename": os.path.basename(filepath),
                     "processed_date": datetime.today().strftime('%d%m%Y'),
                     "extracted_text": "",
                     "error": "Image file too large",
                     "_cache_error": True,
                     "_permanent_error": True,
                     "_error_reason": "Imagen demasiado grande (>10MB)",
                     "file_size_mb": round(file_size/1024/1024, 2)
                 }
         except Exception as e:
             logger.warning(f"Error comprobando tamaño de archivo {filepath}: {e}")
        
         # Verificar si el archivo es realmente una imagen válida usando la utilidad optimizada
         is_image, image_format = is_valid_image(filepath)
         if not is_image:
             logger.warning(f"Archivo no es una imagen válida: {filepath} (formato detectado: {image_format})")
             return {
                 "image_filename": os.path.basename(filepath),
                 "processed_date": datetime.today().strftime('%d%m%Y'),
                 "extracted_text": "",
                 "error": "File is not a valid image",
                 "_cache_error": True,
                 "_permanent_error": True,  # Marcar como error permanente
                 "_error_reason": "Archivo no es una imagen válida",
                 "detected_type": image_format
             }
         
         # Calcular hash perceptual para imágenes (para detectar duplicados visuales)
         # Y usarlo además del hash de contenido para el caché
         perceptual_hash = None
         try:
             with Image.open(filepath) as img:
                 # Redimensionar para análisis más rápido si la imagen es muy grande
                 if max(img.size) > 1000:
                     img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
                 # Calcular hash perceptual (es resistente a cambios menores)
                 perceptual_hash = str(imagehash.phash(img))
         except Exception as e:
             logger.debug(f"No se pudo calcular hash perceptual: {e}")

         # Calcular hash eficiente del archivo para la clave de caché primaria
         content_hash = fast_hash_file(filepath)
         if not content_hash:
              logger.warning(f"No se pudo calcular hash para archivo: {filepath}")
              return {
                 "image_filename": os.path.basename(filepath),
                 "processed_date": datetime.today().strftime('%d%m%Y'),
                 "extracted_text": "",
                 "error": "Failed to calculate file hash",
                 "_cache_error": True
              }
              
         # Usar hash de contenido como clave principal, pero guardar el hash perceptual
         cache_key = content_hash
         
         # Si tenemos hash perceptual, buscar también por él (para encontrar imágenes visualmente similares)
         if perceptual_hash and self.cache_dir and self.cache_expiry is not None:
             # Primero buscar por hash perceptual
             perceptual_cache_key = f"perceptual_{perceptual_hash}"
             perceptual_cached_result = load_from_cache(self.cache_dir, perceptual_cache_key, self.cache_expiry)
             if perceptual_cached_result:
                 # Si encontramos coincidencia perceptual, registrarla pero continuar con hash de contenido
                 logger.info(f"Imagen {os.path.basename(filepath)} visualmente similar a otra ya procesada")

         # Verificar caché principal (por hash de contenido)
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
                  # Añadir hash perceptual si lo tenemos y no estaba en el caché
                  if perceptual_hash and 'perceptual_hash' not in cached_result:
                      cached_result['perceptual_hash'] = perceptual_hash
                  return cached_result

         # Si no está en caché, llamar a la API
         logger.debug(f"Llamando a API de Gemini para imagen {image_meta.get('filename')} (no en caché o expirado)")
         api_result = None
         
         try:
             # Verificar dimensiones antes de enviar a la API
             try:
                 with Image.open(filepath) as img:
                     width, height = img.size
                     pixels = width * height
                     # Si la imagen es extremadamente grande (más de 8MP), podría causar problemas
                     if pixels > 8000000:  # 8 megapíxeles
                         logger.warning(f"Imagen {image_meta.get('filename')} es muy grande ({width}x{height}={pixels} píxeles). Intentando redimensionar.")
                         # Redimensionar temporalmente para API si es muy grande
                         temp_resized_path = filepath + ".resized.jpg"
                         try:
                             # Calcular nueva dimensión manteniendo proporción
                             ratio = (width / height)
                             if ratio > 1:  # Más ancha que alta
                                 new_width = min(2500, width)
                                 new_height = int(new_width / ratio)
                             else:  # Más alta que ancha
                                 new_height = min(2500, height)
                                 new_width = int(new_height * ratio)
                                 
                             # Crear versión redimensionada
                             img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                             img_resized.save(temp_resized_path, "JPEG", quality=85)
                             logger.info(f"Imagen redimensionada a {new_width}x{new_height} para API")
                             
                             # Usar la versión redimensionada para la API
                             api_result = self.api_client.extract_text_from_image(temp_resized_path)
                             
                             # Eliminar archivo temporal después de usarlo
                             try:
                                 os.remove(temp_resized_path)
                             except:
                                 pass
                         except Exception as resize_err:
                             logger.warning(f"Error al redimensionar imagen: {resize_err}. Usando original.")
                             api_result = self.api_client.extract_text_from_image(filepath)
                     else:
                         # Imagen de tamaño razonable, usar directamente
                         api_result = self.api_client.extract_text_from_image(filepath)
             except Exception as img_err:
                 logger.warning(f"Error al verificar dimensiones de imagen: {img_err}. Intentando directamente con API.")
                 api_result = self.api_client.extract_text_from_image(filepath)
         except Exception as api_err:
             logger.error(f"Error en llamada a API para imagen {image_meta.get('filename')}: {api_err}")
             api_result = {
                 "image_filename": os.path.basename(filepath),
                 "processed_date": datetime.today().strftime('%d%m%Y'),
                 "extracted_text": "",
                 "error": f"API error: {str(api_err)}",
                 "_cache_error": True
             }

         # Implementar pacing para Gemini API (evitar límites de cuota)
         wait_time = random.uniform(1, 3)  # Entre 1 y 3 segundos entre solicitudes
         logger.debug(f"Esperando {wait_time:.2f} segundos antes de la siguiente solicitud a Gemini API")
         time.sleep(wait_time)

         # Guardar en caché tanto éxitos como errores
         if self.cache_dir and api_result:
             # Añadir hash perceptual al resultado si lo tenemos
             if perceptual_hash:
                 api_result['perceptual_hash'] = perceptual_hash
                 
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
                     
                     # Si tenemos hash perceptual, guardar también referencia cruzada
                     if perceptual_hash:
                         save_to_cache(self.cache_dir, f"perceptual_{perceptual_hash}", {
                             "content_hash": cache_key,
                             "permanent_error": True,
                             "reason": api_result.get("_error_reason")
                         }, expiry_seconds=permanent_seconds)
                 else:
                     # Errores normales se cachean temporalmente (1 hora)
                     one_hour_seconds = 3600
                     logger.debug(f"Cacheando error de API para {image_meta.get('filename')} por 1 hora")
                     save_to_cache(self.cache_dir, f"gemini_{cache_key}", api_result, expiry_seconds=one_hour_seconds)
             else:
                 logger.debug(f"Cacheando respuesta exitosa de API para {image_meta.get('filename')}")
                 save_to_cache(self.cache_dir, f"gemini_{cache_key}", api_result)
                 
                 # Si tenemos hash perceptual, guardar también referencia cruzada para imágenes similares
                 if perceptual_hash:
                     save_to_cache(self.cache_dir, f"perceptual_{perceptual_hash}", {
                         "content_hash": cache_key,
                         "success": True
                     })

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
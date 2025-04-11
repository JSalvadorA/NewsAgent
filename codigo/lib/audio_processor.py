# codigo/lib/audio_processor.py
import os
import requests
import logging
import time
import random
import json
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Importar utilidades locales
from .cache_utils import get_cache_key, load_from_cache, save_to_cache
from .file_manager import save_to_json, ensure_dir_exists
from .api_client import ImageTextExtractorAPI  # Podemos usar el mismo cliente de API para transcribir
from .request_utils import get_session  # Importar sistema centralizado de sesiones
from .file_utils import is_valid_audio, fast_hash_file, identify_file_type

logger = logging.getLogger(__name__)

class AudioProcessor:
    def __init__(self, config):
        self.config = config
        self.paths = config.get('paths', {})
        self.cache_dir = self.paths.get('cache_dir')
        self.cache_expiry = config.get('cache_expiry')
        self.session = get_session()  # Usar sesión compartida para todos los servicios
        self.headers = config.get('headers', {})
        self.max_workers = config.get('max_workers', 5)
        
        # Inicializar cliente API para transcripción
        try:
            api_config = config.get('api', {})
            api_key = api_config.get('key')
            model_name = api_config.get('model', 'gemini-1.5-pro-latest')
            prompt_key = api_config.get('prompt_key', 'detallado')
            
            self.api_client = ImageTextExtractorAPI(
                api_key=api_key,
                model_name=model_name,
                prompt_key=prompt_key
            )
            logger.info(f"Cliente API inicializado para transcripción de audio")
        except Exception as e:
            self.api_client = None
            logger.warning(f"No se pudo inicializar API para transcripción: {e}")
    
    def download_single_audio(self, url_info, audio_index, date_str):
        """
        Descarga un único archivo de audio desde una URL.
        Gestiona caché basado en la URL.
        Retorna la URL y un diccionario con metadatos o error.
        """
        url = url_info.get("URL")
        context = url_info.get("Context", "")
        output_dir = self.paths.get("audio_dir")
        
        if not url or not output_dir:
            return url, {"error": "URL o directorio de salida inválido", "context": context}
        
        cache_key = get_cache_key(url)
        if self.cache_dir and self.cache_expiry is not None:
            cached_result = load_from_cache(self.cache_dir, cache_key, self.cache_expiry)
            if cached_result:
                if cached_result.get("filepath") and os.path.exists(cached_result["filepath"]):
                    logger.debug(f"Usando caché para audio {url}")
                    if cached_result.get("context") != context:
                        cached_result["context"] = context
                    return url, cached_result
        
        result = {"context": context}
        filepath = None
        
        try:
            ensure_dir_exists(output_dir)
            logger.debug(f"Descargando audio {audio_index} desde {url}")
            
            response = self.session.get(url, headers=self.headers, timeout=30, stream=True)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', 'application/octet-stream').split(';')[0]
            
            # Verificar si el content-type concuerda con un tipo de audio
            is_audio = False
            if content_type.startswith('audio/'):
                is_audio = True
            elif content_type in ['application/octet-stream', 'binary/octet-stream']:
                # Si el servidor no especifica bien el tipo, intentamos adivinar por la extensión
                path_lower = urlparse(url).path.lower()
                is_audio = any(path_lower.endswith(ext) for ext in ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.opus'])
            
            # Si definitivamente NO es un audio, agregamos una advertencia pero continuamos
            if not is_audio and not any(content_type.startswith(prefix) for prefix in ['audio/']):
                logger.warning(f"URL {url} tiene tipo de contenido {content_type}, puede no ser un archivo de audio. Se continuará la descarga.")
                result["warning"] = f"Content type '{content_type}' may not be audio"
            
            # Determinar la extensión del archivo usando utilidades mejoradas
            extension = ".mp3"  # Por defecto
            
            # 1. Intentar extraer de content-type
            mime_to_ext = {
                'mpeg': '.mp3',
                'mp3': '.mp3',
                'wav': '.wav',
                'x-wav': '.wav',
                'ogg': '.ogg',
                'x-m4a': '.m4a',
                'aac': '.aac',
                'opus': '.opus',
                'x-opus': '.opus',
            }
            
            if '/' in content_type:
                ext_candidate = content_type.split('/')[-1]
                if ext_candidate in mime_to_ext:
                    extension = mime_to_ext[ext_candidate]
            
            # 2. Si no se pudo determinar por content-type, intentar por URL
            if extension == ".mp3":
                path = urlparse(url).path.lower()
                if path.endswith('.wav'):
                    extension = '.wav'
                elif path.endswith('.ogg'):
                    extension = '.ogg'
                elif path.endswith('.m4a'):
                    extension = '.m4a'
                elif path.endswith('.aac'):
                    extension = '.aac'
                elif path.endswith('.opus'):
                    extension = '.opus'
            
            # Crear nombre de archivo único
            url_hash_part = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"audio_{audio_index}_{url_hash_part}_{date_str}{extension}"
            filepath = os.path.join(output_dir, filename)
            
            # Descargar contenido
            downloaded_size = 0
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
            
            logger.info(f"Audio {audio_index} guardado como '{filename}' en {output_dir} ({downloaded_size} bytes)")
            
            result.update({
                "filepath": filepath,
                "filename": filename,
                "content_type": content_type,
                "size": downloaded_size,
                "download_timestamp": datetime.now().isoformat()
            })
            
            # Guardar en caché
            if self.cache_dir:
                save_to_cache(self.cache_dir, cache_key, result)
            
            time.sleep(random.uniform(0.2, 0.8))
            
        except Exception as e:
            logger.warning(f"Error descargando audio {url}: {str(e)}")
            result["error"] = f"Error: {str(e)}"
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    logger.debug(f"Archivo parcial eliminado: {filepath}")
                except:
                    pass
        
        return url, result
    
    def download_audio_parallel(self, audio_links, date_str):
        """
        Descarga una lista de archivos de audio en paralelo.
        Guarda los archivos en la carpeta configurada en las rutas.
        Retorna un diccionario {url: metadata} de los archivos descargados.
        """
        if not audio_links:
            logger.info("No hay enlaces de audio para descargar.")
            return {}
        
        total_audios = len(audio_links)
        processed_count = 0
        downloaded_metadata = {}
        
        # Detector de URLs duplicadas
        url_to_index = {}
        processed_urls = set()
        
        start_time = time.time()
        
        # Asegurar que exista el directorio para guardar los audios
        audio_dir = self.paths.get('audio_dir')
        if not audio_dir:
            logger.error("No se ha configurado el directorio para guardar archivos de audio.")
            return {}
        ensure_dir_exists(audio_dir)
        
        logger.info(f"Iniciando descarga paralela de {total_audios} archivos de audio para fecha {date_str}...")
        output_json_path = self.paths.get("audio_metadata_json") # Path para guardar metadata
        
        # Identificar duplicados
        for idx, link_info in enumerate(audio_links, 1):
            url = link_info.get("URL")
            if url in url_to_index:
                logger.warning(f"URL duplicada detectada: {url}. Primera ocurrencia: #{url_to_index[url]}, segunda: #{idx}")
            else:
                url_to_index[url] = idx
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_url = {}
            
            # Solo procesar URLs únicas
            for idx, link_info in enumerate(audio_links, 1):
                url_orig = link_info.get("URL")
                
                if url_orig in processed_urls:
                    logger.info(f"Omitiendo URL duplicada #{idx}: {url_orig}")
                    continue
                
                processed_urls.add(url_orig)
                future_to_url[executor.submit(self.download_single_audio, link_info, idx, date_str)] = link_info
            
            for future in as_completed(future_to_url):
                link_info_orig = future_to_url[future]
                url_orig = link_info_orig.get("URL")
                processed_count += 1
                
                try:
                    url_processed, metadata = future.result()
                    downloaded_metadata[url_orig] = metadata
                    
                    if "error" in metadata:
                        logger.warning(f"Error procesando audio {url_orig}: {metadata['error']}")
                    else:
                        logger.debug(f"Procesado audio {url_orig} exitosamente.")
                
                except Exception as e:
                    logger.error(f"Error procesando futuro de audio para {url_orig}: {e}")
                    downloaded_metadata[url_orig] = {
                        "error": f"Future processing failed: {str(e)}",
                        "context": link_info_orig.get("Context")
                    }
                
                if processed_count % 5 == 0 or processed_count == total_audios:
                    elapsed = time.time() - start_time
                    logger.info(f"Progreso descarga audio: {processed_count}/{total_audios} en {elapsed:.2f} seg.")
        
        # Guardar metadata
        if output_json_path and downloaded_metadata:
            save_to_json(downloaded_metadata, output_json_path)
            logger.info(f"Metadata de archivos de audio guardada en: {output_json_path}")
        elif not downloaded_metadata:
            logger.warning("No hay metadatos de audio para guardar.")
        else:
            logger.warning("No se especificó ruta para guardar metadata de audios descargados.")
        
        end_time = time.time()
        logger.info(f"Descarga de archivos de audio completada: {processed_count}/{total_audios} en {end_time - start_time:.2f} segundos.")
        
        return downloaded_metadata
    
    def get_audio_duration(self, audio_path):
        """
        Obtiene la duración de un archivo de audio en segundos.
        Utiliza múltiples métodos para mayor compatibilidad.
        
        Args:
            audio_path: Ruta al archivo de audio
            
        Returns:
            int/float: Duración en segundos o None si no se puede determinar
        """
        if not os.path.exists(audio_path):
            logger.warning(f"Archivo de audio no encontrado: {audio_path}")
            return None
            
        # Verificar primero que sea un archivo de audio válido
        is_audio, audio_format = is_valid_audio(audio_path)
        if not is_audio:
            logger.warning(f"El archivo {audio_path} no es un audio válido (detectado: {audio_format})")
            return None
        
        try:
            # Método 1: FFmpeg (más rápido y confiable cuando está disponible)
            try:
                import subprocess
                result = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 
                     'default=noprint_wrappers=1:nokey=1', audio_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return float(result.stdout.strip())
            except (ImportError, subprocess.SubprocessError, ValueError, FileNotFoundError) as e:
                logger.debug(f"FFmpeg no disponible o falló: {e}")
                pass
            
            # Método 2: Librosa (más preciso pero más lento)
            try:
                import librosa
                duration = librosa.get_duration(path=audio_path)
                return duration
            except ImportError:
                logger.debug("Librosa no disponible")
                pass
            except Exception as e:
                logger.debug(f"Error al usar librosa: {e}")
                pass
            
            # Método 3: Pydub (buena compatibilidad)
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_file(audio_path)
                return audio.duration_seconds
            except ImportError:
                logger.debug("Pydub no disponible")
                pass
            except Exception as e:
                logger.debug(f"Error al usar pydub: {e}")
                pass
            
            # Si llegamos aquí, no se pudo determinar la duración
            logger.warning(f"No se pudo determinar la duración del audio: {audio_path} (ninguna biblioteca disponible)")
            # Asumir una duración por defecto que permita el procesamiento (10 minutos)
            logger.info(f"Asumiendo duración estándar de 600 segundos para permitir procesamiento")
            return 600
        
        except Exception as e:
            logger.error(f"Error obteniendo duración del audio {audio_path}: {e}")
            return None
            
    def _transcribe_with_available_tool(self, audio_path):
        """
        Intenta transcribir un archivo de audio usando las herramientas disponibles.
        Prueba con Whisper, Google Speech-to-Text u otras herramientas si están instaladas.
        
        Args:
            audio_path: Ruta al archivo de audio a transcribir
            
        Returns:
            dict: Diccionario con la transcripción y metadatos adicionales,
                 o None si no hay herramientas disponibles
        """
        # Método 1: Whisper (OpenAI) - la mejor opción cuando está disponible
        try:
            import whisper
            logger.info(f"Transcribiendo {os.path.basename(audio_path)} con Whisper...")
            
            # Cargar modelo (tiny, base, small, medium, large)
            model = whisper.load_model("base")
            
            # Transcribir
            result = model.transcribe(audio_path)
            
            return {
                "text": result["text"],
                "segments": result.get("segments", []),
                "language": result.get("language", "es"),
                "tool": "whisper"
            }
        except ImportError:
            logger.debug("Whisper no disponible")
        except Exception as e:
            logger.warning(f"Error al transcribir con Whisper: {e}")
        
        # Método 2: Google Speech-to-Text (requiere API key)
        try:
            from google.cloud import speech
            
            # Verificar si hay credenciales disponibles
            if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                logger.info(f"Transcribiendo {os.path.basename(audio_path)} con Google Speech-to-Text...")
                
                client = speech.SpeechClient()
                
                # Leer archivo
                with open(audio_path, "rb") as audio_file:
                    content = audio_file.read()
                
                audio = speech.RecognitionAudio(content=content)
                config = speech.RecognitionConfig(
                    encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=16000,
                    language_code="es-ES",  # Ajustar según necesidades
                    enable_automatic_punctuation=True
                )
                
                # Transcribir
                response = client.recognize(config=config, audio=audio)
                
                # Extraer transcripción
                full_text = ""
                for result in response.results:
                    full_text += result.alternatives[0].transcript + " "
                
                return {
                    "text": full_text.strip(),
                    "tool": "google_speech"
                }
            else:
                logger.debug("Credenciales de Google no configuradas")
        except ImportError:
            logger.debug("Google Speech-to-Text no disponible")
        except Exception as e:
            logger.warning(f"Error al transcribir con Google Speech-to-Text: {e}")
        
        # Método 3: SpeechRecognition con reconocedor local (vosk/sphinx)
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            
            logger.info(f"Transcribiendo {os.path.basename(audio_path)} con reconocedor local...")
            
            # Convertir archivo a formato compatible si es necesario
            with sr.AudioFile(audio_path) as source:
                audio_data = recognizer.record(source)
                
                # Intentar con reconocedor local (sphinx)
                text = recognizer.recognize_sphinx(audio_data)
                
                return {
                    "text": text,
                    "tool": "sphinx"
                }
        except ImportError:
            logger.debug("Speech Recognition no disponible")
        except Exception as e:
            logger.warning(f"Error al transcribir con reconocedor local: {e}")
        
        # Si llegamos aquí, no hay herramientas disponibles o todas fallaron
        logger.warning(f"No se pudo transcribir {os.path.basename(audio_path)} con ninguna herramienta disponible")
        return None
    
    def transcribe_audio(self, audio_metadata, date_str, max_duration_minutes=12):
        """
        Transcribe los archivos de audio descargados utilizando la API.
        Solo procesa archivos menores a max_duration_minutes.
        
        Args:
            audio_metadata: Diccionario con metadatos de los archivos de audio
            date_str: Fecha en formato DDMMYYYY
            max_duration_minutes: Duración máxima en minutos para procesar un archivo
            
        Returns:
            list: Lista de resultados con las transcripciones
        """
        if not self.api_client:
            logger.warning("Cliente API no inicializado. No se puede transcribir audio.")
            return []
        
        if not audio_metadata:
            logger.info("No hay metadatos de audio para transcribir.")
            return []
        
        # Organizar y filtrar archivos para transcripción
        audios_to_process = []
        for url, meta in audio_metadata.items():
            if "error" not in meta and meta.get("filepath") and os.path.exists(meta["filepath"]):
                # Verificar que el archivo sea realmente un audio
                audio_path = meta["filepath"]
                is_audio, audio_format = is_valid_audio(audio_path)
                
                if not is_audio:
                    logger.warning(f"Archivo {meta.get('filename')} no es un audio válido (formato: {audio_format}). No se transcribirá.")
                    continue
                    
                # Verificar duración del archivo
                duration = self.get_audio_duration(audio_path)
                
                if duration is None:
                    # Si no se puede determinar la duración, usamos un valor predeterminado
                    duration = 600  # 10 minutos
                    logger.warning(f"Duración desconocida para {meta.get('filename')}. Asumiendo {duration} segundos.")
                
                if duration <= max_duration_minutes * 60:
                    # Solo procesar si es menor al límite de duración
                    logger.info(f"Audio {meta.get('filename')} aceptado para transcripción (duración: {duration:.1f} seg)")
                    audios_to_process.append((meta, duration, url))
                else:
                    logger.warning(f"Audio {meta.get('filename')} excede duración máxima ({duration:.1f} seg > {max_duration_minutes*60} seg). No se transcribirá.")
        
        if not audios_to_process:
            logger.info("No hay archivos de audio válidos para transcribir.")
            return []
        
        total_audios = len(audios_to_process)
        processed_count = 0
        transcription_results = []
        
        logger.info(f"Iniciando transcripción de {total_audios} archivos de audio...")
        output_json_path = os.path.join(self.paths.get("base_dir", ""), "audio", f"audio_transcriptions_{date_str}.json")
        
        # Procesar archivos de audio secuencialmente (uno a la vez)
        for meta, duration, url in audios_to_process:
            audio_path = meta["filepath"]
            filename = meta.get("filename", os.path.basename(audio_path))
            
            logger.info(f"Transcribiendo audio: {filename} (duración: {duration:.1f} seg)")
            
            # Verificar caché
            cache_key = f"audio_transcription_{fast_hash_file(audio_path)}"
            cached_result = None
            if self.cache_dir and self.cache_expiry is not None:
                cached_result = load_from_cache(self.cache_dir, cache_key, self.cache_expiry)
                if cached_result:
                    logger.info(f"Usando transcripción en caché para {filename}")
                    transcription_results.append(cached_result)
                    processed_count += 1
                    continue
            
            # Preparar resultado inicial
            result = {
                "audio_filename": filename,
                "processed_date": date_str,
                "transcription": "",
                "duration_seconds": duration,
                "error": None,
                "context": meta.get("context", ""),
                "url": url
            }
            
            try:
                # Intentar transcribir con Whisper u otra herramienta de transcripción
                transcription = self._transcribe_with_available_tool(audio_path)
                
                if transcription and transcription.get("text"):
                    result["transcription"] = transcription.get("text")
                    if "segments" in transcription:
                        result["segments"] = transcription.get("segments")
                    if "language" in transcription:
                        result["language"] = transcription.get("language")
                    logger.info(f"Transcripción completada para {filename} ({len(result['transcription'])} caracteres)")
                else:
                    # Si no hay herramientas disponibles, usar mensaje por defecto
                    result["transcription"] = f"[Este es un archivo de audio de {int(duration)} segundos. No se pudo transcribir automáticamente.]"
                    logger.warning(f"No hay herramientas de transcripción disponibles para {filename}")
                
            except Exception as e:
                logger.error(f"Error transcribiendo audio {filename}: {e}")
                result["error"] = f"Transcription error: {str(e)}"
                result["transcription"] = f"[Error al transcribir archivo de audio: {str(e)}]"
            
            transcription_results.append(result)
            processed_count += 1
            
            # Guardar en caché
            if self.cache_dir and not result["error"]:
                save_to_cache(self.cache_dir, cache_key, result)
            
            # Mostrar progreso
            logger.info(f"Progreso transcripción: {processed_count}/{total_audios}")
            
            # Pausa entre archivos (necesaria para API)
            time.sleep(2)
        
        # Guardar resultados
        if output_json_path and transcription_results:
            ensure_dir_exists(os.path.dirname(output_json_path))
            save_to_json(transcription_results, output_json_path)
            logger.info(f"Resultados de transcripción guardados en: {output_json_path}")
        
        return transcription_results

# Importar hashlib para generar hashes
import hashlib
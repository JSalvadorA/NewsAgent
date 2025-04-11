# lib/file_utils.py
import os
import logging
import hashlib

logger = logging.getLogger(__name__)

# Diccionario de firmas de archivos (magic bytes)
FILE_SIGNATURES = {
    # Imágenes
    b'\xff\xd8\xff': {'type': 'image', 'format': 'jpeg', 'ext': '.jpg'},
    b'\x89PNG\r\n\x1a\n': {'type': 'image', 'format': 'png', 'ext': '.png'},
    b'GIF87a': {'type': 'image', 'format': 'gif', 'ext': '.gif'},
    b'GIF89a': {'type': 'image', 'format': 'gif', 'ext': '.gif'},
    b'RIFF': {'type': 'image', 'format': 'webp', 'ext': '.webp'}, # WEBP comienza con RIFF
    b'II*\x00': {'type': 'image', 'format': 'tiff', 'ext': '.tiff'},
    b'MM\x00*': {'type': 'image', 'format': 'tiff', 'ext': '.tiff'},
    b'BM': {'type': 'image', 'format': 'bmp', 'ext': '.bmp'},
    
    # Audio
    b'ID3': {'type': 'audio', 'format': 'mp3', 'ext': '.mp3'}, # MP3 con ID3v2
    b'\xff\xfb': {'type': 'audio', 'format': 'mp3', 'ext': '.mp3'}, # MP3 sin ID3
    b'RIFF....WAVE': {'type': 'audio', 'format': 'wav', 'ext': '.wav'}, # WAV
    b'OggS': {'type': 'audio', 'format': 'ogg', 'ext': '.ogg'}, # OGG
    
    # Video
    b'\x00\x00\x00\x18ftypmp42': {'type': 'video', 'format': 'mp4', 'ext': '.mp4'}, # MP4
    b'\x00\x00\x00\x1cftypisom': {'type': 'video', 'format': 'mp4', 'ext': '.mp4'}, # MP4 ISO
    
    # Documentos
    b'%PDF': {'type': 'document', 'format': 'pdf', 'ext': '.pdf'}, # PDF
    b'PK\x03\x04': {'type': 'document', 'format': 'zip/office', 'ext': '.zip'}, # ZIP/DOCX/XLSX
}

def get_file_signature(filepath, bytes_to_read=16):
    """
    Obtiene los primeros bytes de un archivo para identificar su tipo.
    
    Args:
        filepath: Ruta al archivo
        bytes_to_read: Número de bytes a leer del inicio del archivo
        
    Returns:
        Bytes leídos del inicio del archivo
    """
    try:
        with open(filepath, 'rb') as f:
            return f.read(bytes_to_read)
    except Exception as e:
        logger.error(f"Error leyendo firma de archivo {filepath}: {e}")
        return b''

def identify_file_type(filepath):
    """
    Identifica el tipo de archivo basado en su firma (magic bytes).
    
    Args:
        filepath: Ruta al archivo
        
    Returns:
        Tuple (tipo, formato, extensión) o (None, None, None) si no se puede identificar
    """
    if not os.path.exists(filepath) or os.path.getsize(filepath) < 4:
        return None, None, None
    
    try:
        signature = get_file_signature(filepath, 16)
        
        # Comprobar cada firma conocida
        for sig, info in FILE_SIGNATURES.items():
            # Manejar firmas parciales (como RIFF que requiere posiciones específicas)
            if sig == b'RIFF':
                if signature.startswith(b'RIFF') and b'WEBP' in signature:
                    return 'image', 'webp', '.webp'
                elif signature.startswith(b'RIFF') and b'WAVE' in signature:
                    return 'audio', 'wav', '.wav'
            # Firmas estándar
            elif signature.startswith(sig):
                return info['type'], info['format'], info['ext']
        
        # Si llegamos aquí, no se ha podido identificar el tipo
        return None, None, None
    except Exception as e:
        logger.error(f"Error identificando tipo de archivo {filepath}: {e}")
        return None, None, None

def is_valid_image(filepath):
    """
    Verifica si un archivo es una imagen válida basado en su firma.
    
    Args:
        filepath: Ruta al archivo de imagen
        
    Returns:
        Tuple (bool, formato) indicando si es una imagen válida y su formato
    """
    file_type, format_type, _ = identify_file_type(filepath)
    return (file_type == 'image', format_type)

def is_valid_audio(filepath):
    """
    Verifica si un archivo es un audio válido basado en su firma.
    
    Args:
        filepath: Ruta al archivo de audio
        
    Returns:
        Tuple (bool, formato) indicando si es un audio válido y su formato
    """
    file_type, format_type, _ = identify_file_type(filepath)
    return (file_type == 'audio', format_type)

def fast_hash_file(filepath, algorithm='md5', chunk_size=65536):
    """
    Calcula un hash eficiente del archivo por bloques sin cargar todo el archivo en memoria.
    
    Args:
        filepath: Ruta al archivo
        algorithm: 'md5' (por defecto) para compatibilidad
        chunk_size: Tamaño de bloque para procesar en bytes
        
    Returns:
        Hash hexadecimal del archivo o None si ocurre un error
    """
    if not os.path.exists(filepath):
        logger.warning(f"Archivo no encontrado para hash: {filepath}")
        return None
    
    try:
        hasher = hashlib.md5()
        
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(chunk_size), b''):
                hasher.update(chunk)
                
        return hasher.hexdigest()
        
    except Exception as e:
        logger.error(f"Error calculando hash para {filepath}: {e}")
        return None

# Intenta importar e implementar xxHash si está disponible (mucho más rápido)
try:
    import xxhash
    
    def xxhash_file(filepath, chunk_size=65536):
        """
        Calcula un xxHash del archivo (mucho más rápido que MD5).
        
        Args:
            filepath: Ruta al archivo
            chunk_size: Tamaño de bloque para procesar en bytes
            
        Returns:
            Hash hexadecimal del archivo
        """
        if not os.path.exists(filepath):
            return None
            
        try:
            hasher = xxhash.xxh64()
            
            with open(filepath, 'rb') as f:
                for chunk in iter(lambda: f.read(chunk_size), b''):
                    hasher.update(chunk)
                    
            return hasher.hexdigest()
            
        except Exception as e:
            logger.error(f"Error calculando xxhash para {filepath}: {e}")
            return None
    
    # Reemplazar la implementación por defecto con xxHash si está disponible
    fast_hash_file = xxhash_file
    logger.info("xxHash disponible y activado como algoritmo de hash predeterminado")
    
except ImportError:
    logger.info("xxHash no disponible, usando MD5 como algoritmo de hash predeterminado")

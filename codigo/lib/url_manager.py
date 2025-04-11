# codigo/lib/url_manager.py
from urllib.parse import urlparse, unquote
import logging
import re

logger = logging.getLogger(__name__)

# Dominios comunes de redes sociales (lista más completa)
SOCIAL_DOMAINS = {
    'facebook.com', 'www.facebook.com',
    'twitter.com', 'x.com', # Incluir x.com
    'instagram.com', 'www.instagram.com',
    'linkedin.com', 'www.linkedin.com',
    'youtube.com', 'www.youtube.com', 'youtu.be',
    'pinterest.com', 'www.pinterest.com',
    'tiktok.com', 'www.tiktok.com',
    'whatsapp.com', # Enlaces wa.me
    't.me', # Telegram
    'reddit.com', 'www.reddit.com',
    # Añadir más si es necesario
}

# Extensiones comunes de imágenes y patrones en URL
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.tiff', '.ico'}
IMAGE_PATH_PATTERNS = ['/uploads/', '/images/', '/img/', '/static/images/', '/media/']

# Extensiones y patrones de audio
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.opus'}
AUDIO_PATH_PATTERNS = ['/audio/', '/sound/', '/music/', '/podcast/', '/media/audio/']

# Extensiones y patrones de video
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.flv', '.wmv', '.webm', '.mkv'}
VIDEO_PATH_PATTERNS = ['/video/', '/media/video/']

def is_valid_url(url):
    """Verifica si una URL tiene esquema y dominio."""
    if not isinstance(url, str) or not url:
        return False
    try:
        parsed = urlparse(url)
        # Requiere esquema (http, https) y netloc (dominio)
        return bool(parsed.scheme) and bool(parsed.netloc)
    except ValueError:
        # URL inválida que causa error en urlparse
        return False

def is_image_url(url):
    """
    Determina si una URL probablemente apunta a una imagen basado en la extensión
    o patrones comunes en la ruta.
    """
    if not is_valid_url(url):
        return False

    try:
        parsed = urlparse(unquote(url)) # Decodificar %20 etc.
        path_lower = parsed.path.lower()
        
        # Primero verificar si es un tipo de archivo de audio o video
        if any(path_lower.endswith(ext) for ext in AUDIO_EXTENSIONS.union(VIDEO_EXTENSIONS)):
            logger.debug(f"URL '{url}' clasificada como NO imagen por extensión de audio/video")
            return False
            
        # Verificar patrones que indican archivos de audio o video
        if any(pattern in path_lower for pattern in AUDIO_PATH_PATTERNS + VIDEO_PATH_PATTERNS):
            logger.debug(f"URL '{url}' clasificada como NO imagen por patrón de ruta de audio/video")
            return False

        # Comprobar extensión de imagen
        if any(path_lower.endswith(ext) for ext in IMAGE_EXTENSIONS):
            return True

        # Comprobar patrones en la ruta que sugieren imagen
        if any(pattern in path_lower for pattern in IMAGE_PATH_PATTERNS):
            return True

    except Exception as e:
        logger.warning(f"Error analizando URL '{url}' para imagen: {e}")
        return False

    return False

def is_audio_url(url):
    """
    Determina si una URL probablemente apunta a un archivo de audio.
    """
    if not is_valid_url(url):
        return False

    try:
        parsed = urlparse(unquote(url))
        path_lower = parsed.path.lower()
        
        # Verificar extensiones comunes de audio
        if any(path_lower.endswith(ext) for ext in AUDIO_EXTENSIONS):
            return True
            
        # Verificar patrones en la ruta que indican audio
        if any(pattern in path_lower for pattern in AUDIO_PATH_PATTERNS):
            return True

    except Exception as e:
        logger.warning(f"Error analizando URL '{url}' para audio: {e}")
        return False

    return False

def is_video_url(url):
    """
    Determina si una URL probablemente apunta a un archivo de video.
    """
    if not is_valid_url(url):
        return False

    try:
        parsed = urlparse(unquote(url))
        path_lower = parsed.path.lower()
        
        # Verificar extensiones comunes de video
        if any(path_lower.endswith(ext) for ext in VIDEO_EXTENSIONS):
            return True
            
        # Verificar patrones en la ruta que indican video
        if any(pattern in path_lower for pattern in VIDEO_PATH_PATTERNS):
            return True

    except Exception as e:
        logger.warning(f"Error analizando URL '{url}' para video: {e}")
        return False

    return False

def is_social_media_url(url):
    """Determina si una URL pertenece a un dominio de red social conocido."""
    if not is_valid_url(url):
        return False
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Manejar subdominios (e.g., m.facebook.com)
        return any(domain == social_domain or domain.endswith('.' + social_domain) for social_domain in SOCIAL_DOMAINS)
    except Exception as e:
         logger.warning(f"Error analizando URL '{url}' para red social: {e}")
         return False


def classify_urls(links):
    """
    Clasifica una lista de diccionarios de enlaces (con clave 'URL')
    en categorías: 'html', 'images', 'audio', 'video', 'social', 'other'.
    Valida las URLs antes de clasificarlas.
    """
    categories = {
        'html': [], 
        'images': [], 
        'audio': [],
        'video': [],
        'social': [], 
        'other': []
    }
    invalid_count = 0
    processed_count = 0

    for link_info in links:
        url = link_info.get("URL")
        processed_count += 1

        if not is_valid_url(url):
            logger.debug(f"URL inválida o vacía omitida: '{url}'")
            invalid_count += 1
            continue

        # Clasificación prioritaria basada en el tipo de contenido:
        if is_audio_url(url):
            categories['audio'].append(link_info)
        elif is_video_url(url):
            categories['video'].append(link_info)
        elif is_image_url(url):
            categories['images'].append(link_info)
        elif is_social_media_url(url):
            categories['social'].append(link_info)
        else:
            # Si no es un tipo específico, asumimos HTML
            if urlparse(url).scheme in ['http', 'https']: # Asegurar que sea web
                categories['html'].append(link_info)
            else: # Otros esquemas (ftp, etc.) o casos no manejados
                categories['other'].append(link_info)

    logger.info(f"Clasificación de {processed_count} URLs:")
    for category, items in categories.items():
        if items: # Solo mostrar si hay elementos
            logger.info(f" - {category.upper()}: {len(items)}")
    if invalid_count > 0:
         logger.warning(f" - Inválidas/Omitidas: {invalid_count}")

    return categories

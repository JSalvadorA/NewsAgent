# lib/request_utils.py
import requests
import random
import logging
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# Singleton para mantener una única sesión global con reintentos
_global_session = None

def get_session(retries=3, backoff_factor=0.5, status_forcelist=(500, 502, 503, 504), 
                pool_connections=20, pool_maxsize=20, pool_block=False):
    """
    Obtiene o crea una sesión global con reintentos configurados.
    
    Args:
        retries: Número de reintentos para solicitudes fallidas
        backoff_factor: Factor para el tiempo de espera entre reintentos
        status_forcelist: Códigos de estado HTTP que deben provocar un reintento
        pool_connections: Número de conexiones a mantener en el pool
        pool_maxsize: Número máximo de conexiones en el pool
        pool_block: Si se debe bloquear cuando no hay conexiones disponibles
        
    Returns:
        Una sesión de requests configurada con reintentos
    """
    global _global_session
    
    if _global_session is None:
        _global_session = requests.Session()
        
        # Configurar estrategia de reintentos
        retry_strategy = Retry(
            total=retries,
            read=retries, 
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
            # Agregar jitter aleatorio para evitar peticiones sincronizadas
            backoff_jitter=random.uniform(0, 0.1)
        )
        
        # Crear y montar adaptadores con la estrategia de reintentos
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            pool_block=pool_block
        )
        
        _global_session.mount("http://", adapter)
        _global_session.mount("https://", adapter)
        
        logger.info("Sesión global con reintentos inicializada")
    
    return _global_session

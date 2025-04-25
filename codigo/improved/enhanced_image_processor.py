"""
enhanced_image_processor.py
Versión mejorada del procesador de imágenes con capacidades avanzadas de:
- Análisis de complejidad más preciso
- Pre-procesamiento de imágenes para optimizar el rendimiento con Gemini
- Gestión de cuotas y backoff exponencial
- Fallback a OCR local cuando Gemini no está disponible
"""
import os
import sys
import json
import time
import logging
import hashlib
import math
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from collections import defaultdict
import cv2
import threading
import shutil

# Agregar el directorio lib al path para importaciones
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
lib_path = os.path.join(parent_dir, 'lib')
project_root = os.path.abspath(os.path.join(parent_dir, '..'))
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

# Configurar logging si no está configurado
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'enhanced_image_processor.log')

logger = logging.getLogger("enhanced_image_processor")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# Importar componentes del sistema original
try:
    from lib.config_unified import get_config
    from lib.image_processor import ImageProcessor
    from lib.gemini_image_extractor import GeminiImageExtractor, PREDEFINED_PROMPTS
except ImportError as e:
    logger.error(f"Error importando módulos originales: {e}")
    logger.error("Asegúrate de que los módulos originales existan en el directorio 'lib'")
    raise

# Intenta importar pytesseract para OCR local
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    logger.warning("Pytesseract no disponible. OCR local desactivado.")
    TESSERACT_AVAILABLE = False


class QuotaManager:
    """Administra el uso de cuota de API para evitar errores 429"""
    
    def __init__(self, daily_limit=50, reset_hour=0):
        self.daily_limit = daily_limit
        self.reset_hour = reset_hour
        self.usage_count = 0
        self.last_reset = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.error_count = 0
        self.backoff_time = 1  # Segundos iniciales de backoff
        self.last_usage = datetime.now() - timedelta(minutes=10)  # Iniciar con tiempo disponible
        self.lock = threading.Lock()
        self.quota_state_file = os.path.join(project_root, 'cache', 'quota_state.json')
        self._load_state()
        
    def _load_state(self):
        """Carga estado de uso desde archivo"""
        try:
            if os.path.exists(self.quota_state_file):
                with open(self.quota_state_file, 'r') as f:
                    state = json.load(f)
                    self.usage_count = state.get('usage_count', 0)
                    self.error_count = state.get('error_count', 0)
                    self.last_reset = datetime.fromisoformat(state.get('last_reset', self.last_reset.isoformat()))
                    self.last_usage = datetime.fromisoformat(state.get('last_usage', self.last_usage.isoformat()))
                    logger.info(f"Estado de cuota cargado: {self.usage_count}/{self.daily_limit} usos")
        except Exception as e:
            logger.warning(f"Error cargando estado de cuota: {e}")
    
    def _save_state(self):
        """Guarda estado de uso en archivo"""
        try:
            os.makedirs(os.path.dirname(self.quota_state_file), exist_ok=True)
            with open(self.quota_state_file, 'w') as f:
                state = {
                    'usage_count': self.usage_count,
                    'error_count': self.error_count,
                    'last_reset': self.last_reset.isoformat(),
                    'last_usage': self.last_usage.isoformat(),
                    'daily_limit': self.daily_limit
                }
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando estado de cuota: {e}")
    
    def reset_if_needed(self):
        """Resetea el contador si es un nuevo día"""
        with self.lock:
            now = datetime.now()
            reset_time = now.replace(hour=self.reset_hour, minute=0, second=0, microsecond=0)
            
            if now >= reset_time and self.last_reset < reset_time:
                self.usage_count = 0
                self.error_count = 0
                self.backoff_time = 1
                self.last_reset = reset_time
                self._save_state()
                logger.info(f"Cuota reseteada. Nuevo período iniciado.")
                return True
            return False
        
    def check_quota_available(self):
        """Verifica si hay cuota disponible"""
        with self.lock:
            self.reset_if_needed()
            return self.usage_count < self.daily_limit
    
    def wait_for_rate_limit(self):
        """Espera si se realizó una solicitud muy recientemente"""
        with self.lock:
            now = datetime.now()
            time_since_last = (now - self.last_usage).total_seconds()
            
            # Mínimo 1 segundo entre solicitudes
            if time_since_last < 1:
                wait_time = 1 - time_since_last
                time.sleep(max(0, wait_time))
            
            # Actualizar tiempo de último uso
            self.last_usage = datetime.now()
        
    def record_usage(self, success=True):
        """Registra un uso de la API"""
        with self.lock:
            if success:
                self.usage_count += 1
                self.error_count = max(0, self.error_count - 1)  # Reducir errores (no a cero)
                self.backoff_time = max(1, self.backoff_time / 1.5)  # Reduce backoff time gradually
            else:
                self.error_count += 1
                self.backoff_time = min(300, self.backoff_time * 1.5)  # Exponential backoff, max 5 min
            
            self._save_state()
            
    def get_recommended_wait_time(self):
        """Obtiene tiempo recomendado de espera basado en errores"""
        with self.lock:
            if self.error_count > 5:
                return min(1800, self.backoff_time * self.error_count)  # Max 30 min
            elif self.error_count > 3:
                return min(300, self.backoff_time * self.error_count)  # Max 5 min
            elif self.error_count > 0:
                return self.backoff_time
            return 1  # Mínimo 1 segundo entre solicitudes
        
    def is_quota_exhausted(self):
        """Determina si la cuota parece estar agotada"""
        with self.lock:
            return self.error_count >= 5 or self.usage_count >= self.daily_limit
    
    def get_status(self):
        """Devuelve estado actual de la cuota"""
        with self.lock:
            return {
                'usage': self.usage_count,
                'limit': self.daily_limit,
                'errors': self.error_count,
                'is_exhausted': self.is_quota_exhausted(),
                'next_reset': (self.last_reset + timedelta(days=1)).replace(hour=self.reset_hour).isoformat()
            }


class ApiKeyRotator:
    """Gestiona rotación de múltiples claves API para maximizar disponibilidad"""
    
    def __init__(self, api_keys=None):
        """
        Inicializa el rotador de API keys
        
        Args:
            api_keys: Lista de claves API o None para buscar en .env
        """
        if not api_keys:
            api_keys = self._load_api_keys()
            
        self.api_keys = api_keys if isinstance(api_keys, list) else [api_keys]
        self.current_index = 0
        self.key_usage = {key: 0 for key in self.api_keys}
        self.key_errors = {key: 0 for key in self.api_keys}
        self.lock = threading.Lock()
        self.state_file = os.path.join(project_root, 'cache', 'apikey_state.json')
        self._load_state()
    
    def _load_api_keys(self):
        """Carga claves API desde variables de entorno o .env"""
        from dotenv import load_dotenv
        
        # Determinar posibles ubicaciones del archivo .env
        dotenv_paths = [
            os.path.join(project_root, 'credentials', '.env'),
            os.path.join(project_root, '.env')
        ]
        
        # Verificar cada ubicación
        found_keys = []
        for dotenv_path in dotenv_paths:
            if os.path.exists(dotenv_path):
                load_dotenv(dotenv_path=dotenv_path)
                
                # Buscar claves en varios formatos
                primary_key = os.getenv("GOOGLE_API_KEY")
                if primary_key:
                    found_keys.append(primary_key)
                
                # Buscar claves numeradas (GOOGLE_API_KEY_1, GOOGLE_API_KEY_2, etc.)
                for i in range(1, 10):
                    key = os.getenv(f"GOOGLE_API_KEY_{i}")
                    if key:
                        found_keys.append(key)
        
        if not found_keys:
            logger.warning("No se encontraron claves API en archivos .env")
            return ["dummy_key"]  # Clave ficticia para que el sistema no falle
        
        logger.info(f"Cargadas {len(found_keys)} claves API")
        return found_keys
    
    def _load_state(self):
        """Carga estado de uso de claves desde archivo"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    self.current_index = state.get('current_index', 0) % len(self.api_keys)
                    self.key_usage = state.get('key_usage', {})
                    self.key_errors = state.get('key_errors', {})
                    
                    # Asegurar que todas las claves estén en los diccionarios
                    for key in self.api_keys:
                        if key not in self.key_usage:
                            self.key_usage[key] = 0
                        if key not in self.key_errors:
                            self.key_errors[key] = 0
        except Exception as e:
            logger.warning(f"Error cargando estado de claves API: {e}")
    
    def _save_state(self):
        """Guarda estado de uso de claves en archivo"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w') as f:
                state = {
                    'current_index': self.current_index,
                    'key_usage': self.key_usage,
                    'key_errors': self.key_errors
                }
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Error guardando estado de claves API: {e}")
    
    def get_current_key(self):
        """Obtiene la clave API actual"""
        with self.lock:
            return self.api_keys[self.current_index]
    
    def rotate_key(self):
        """Rota a la siguiente clave API disponible"""
        with self.lock:
            # Buscar una clave con pocos errores
            initial_index = self.current_index
            while True:
                self.current_index = (self.current_index + 1) % len(self.api_keys)
                key = self.api_keys[self.current_index]
                
                # Si esta clave tiene menos de 5 errores, usarla
                if self.key_errors.get(key, 0) < 5:
                    break
                
                # Si ya revisamos todas las claves, usar la que tenga menos errores
                if self.current_index == initial_index:
                    min_errors = min(self.key_errors.values())
                    for i, k in enumerate(self.api_keys):
                        if self.key_errors.get(k, 0) == min_errors:
                            self.current_index = i
                            break
                    break
            
            logger.info(f"Rotando a clave API #{self.current_index+1}")
            self._save_state()
            return self.get_current_key()
    
    def mark_usage(self, key, success=True):
        """Registra uso de una clave API"""
        with self.lock:
            if key in self.key_usage:
                self.key_usage[key] += 1
            else:
                self.key_usage[key] = 1
                
            if not success and key in self.key_errors:
                self.key_errors[key] += 1
            elif not success:
                self.key_errors[key] = 1
            elif success and key in self.key_errors:
                self.key_errors[key] = max(0, self.key_errors[key] - 1)
                
            self._save_state()
    
    def mark_error(self, key):
        """Registra un error con una clave API y rota si es necesario"""
        with self.lock:
            if key in self.key_errors:
                self.key_errors[key] += 1
            else:
                self.key_errors[key] = 1
                
            # Si hay demasiados errores, rotar automáticamente
            if key == self.get_current_key() and self.key_errors[key] >= 3:
                return self.rotate_key()
                
            self._save_state()
            return key
    
    def get_status(self):
        """Devuelve estadísticas de uso de claves"""
        with self.lock:
            return {
                'total_keys': len(self.api_keys),
                'active_key': self.current_index + 1,
                'usage_stats': self.key_usage,
                'error_stats': self.key_errors
            }

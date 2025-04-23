#!/usr/bin/env python3
"""
Módulo de configuración para la aplicación.
Implementa un patrón Singleton para centralizar la configuración.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class Configuration:
    """
    Clase de configuración que implementa el patrón Singleton.
    Lee y proporciona acceso a la configuración del sistema.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Obtiene la instancia única de la configuración."""
        if cls._instance is None:
            cls._instance = Configuration()
        return cls._instance
    
    def __init__(self):
        """Inicializa la configuración desde los archivos y variables de entorno."""
        self.config: Dict[str, Any] = {}
        self.load_default_config()
        self.load_env_vars()
        logger.debug("Configuración cargada")
    
    def load_default_config(self):
        """Carga la configuración desde archivos JSON."""
        config_paths = [
            Path("config/default.json"),
            Path("credentials/config.json"),
            Path("credentials/api_keys.json"),
        ]
        
        for path in config_paths:
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        config_data = json.load(f)
                        self._merge_config(config_data)
                    logger.debug(f"Configuración cargada desde {path}")
                except Exception as e:
                    logger.error(f"Error al cargar configuración desde {path}: {e}")
    
    def load_env_vars(self):
        """Carga configuración desde variables de entorno."""
        # Variables de entorno específicas
        env_mappings = {
            "API_KEY": ("api", "key"),
            "API_URL": ("api", "url"),
            "DEBUG": ("app", "debug"),
        }
        
        for env_var, config_path in env_mappings.items():
            if env_var in os.environ:
                self._set_nested_value(self.config, config_path, os.environ[env_var])
                logger.debug(f"Configuración cargada desde variable de entorno {env_var}")
    
    def _merge_config(self, config_data: Dict[str, Any]):
        """Combina la configuración nueva con la existente."""
        for key, value in config_data.items():
            if key in self.config and isinstance(self.config[key], dict) and isinstance(value, dict):
                self._merge_config_dict(self.config[key], value)
            else:
                self.config[key] = value
    
    def _merge_config_dict(self, target: Dict[str, Any], source: Dict[str, Any]):
        """Combina diccionarios de configuración de manera recursiva."""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._merge_config_dict(target[key], value)
            else:
                target[key] = value
    
    def _set_nested_value(self, config_dict: Dict[str, Any], path_parts, value):
        """Establece un valor en un diccionario anidado."""
        if len(path_parts) == 1:
            config_dict[path_parts[0]] = value
            return
        
        key = path_parts[0]
        if key not in config_dict:
            config_dict[key] = {}
        
        self._set_nested_value(config_dict[key], path_parts[1:], value)
    
    def get(self, key: str, default=None) -> Any:
        """Obtiene un valor de configuración por su clave."""
        return self.config.get(key, default)
    
    def get_nested(self, *keys, default=None) -> Any:
        """Obtiene un valor anidado de configuración."""
        current = self.config
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

# Ejemplo de uso
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    config = Configuration.get_instance()
    print(f"API Key: {config.get_nested('api', 'key', default='No configurado')}")
    print(f"Configuración completa: {config.config}") 
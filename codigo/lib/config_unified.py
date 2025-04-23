#!/usr/bin/env python3
"""
Módulo unificado de configuración para la aplicación.
Combina funcionalidades de config.py y config_manager.py en una única interfaz coherente.
Implementa un patrón Singleton para centralizar la configuración.
"""

import os
import json
import logging
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union

logger = logging.getLogger(__name__)

class ConfigurationManager:
    """
    Gestor de configuración unificado que implementa el patrón Singleton.
    Lee y proporciona acceso a la configuración del sistema, y genera rutas
    derivadas basadas en la configuración.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls, project_root: Optional[str] = None):
        """
        Obtiene la instancia única del gestor de configuración.
        
        Args:
            project_root: Ruta raíz del proyecto (opcional, solo en la primera llamada)
            
        Returns:
            Instancia de ConfigurationManager
        """
        if cls._instance is None:
            if project_root is None:
                # Si no se proporciona project_root, intentar inferirlo
                import inspect
                frame = inspect.stack()[1]
                caller_path = frame.filename
                project_root = os.path.abspath(os.path.join(os.path.dirname(caller_path), '..', '..'))
                logger.debug(f"Inferido project_root desde la ubicación del llamador: {project_root}")
            cls._instance = ConfigurationManager(project_root)
        return cls._instance
    
    def __init__(self, project_root: str):
        """
        Inicializa la configuración desde archivos y variables de entorno.
        
        Args:
            project_root: Ruta raíz del proyecto para resolución de rutas relativas
        """
        self.project_root = os.path.abspath(project_root)
        self.config: Dict[str, Any] = {}
        self.paths: Dict[str, str] = {}
        
        # Cargar configuración base
        self._load_config_files()
        self._load_env_vars()
        
        logger.debug("Configuración unificada cargada")
    
    def _load_config_files(self):
        """
        Carga la configuración desde archivos JSON y YAML.
        Busca configuración en ubicaciones estándar y específicas.
        """
        # Rutas de configuración ordenadas por prioridad (las últimas tienen mayor precedencia)
        config_paths = [
            Path(self.project_root) / "config" / "default.json",
            Path(self.project_root) / "config" / "config.json",
            Path(self.project_root) / "config" / "config.yaml",
            Path(self.project_root) / "config" / "config.yml",
            Path(self.project_root) / "credentials" / "config.json",
            Path(self.project_root) / "credentials" / "api_keys.json",
            Path(self.project_root) / "credentials" / "api_keys.yaml",
        ]
        
        for path in config_paths:
            if path.exists():
                try:
                    if path.suffix in ['.json']:
                        with open(path, 'r', encoding='utf-8') as f:
                            config_data = json.load(f)
                    elif path.suffix in ['.yaml', '.yml']:
                        with open(path, 'r', encoding='utf-8') as f:
                            import yaml
                            config_data = yaml.safe_load(f)
                    else:
                        logger.warning(f"Tipo de archivo no soportado: {path}")
                        continue
                        
                    self._merge_config(config_data)
                    logger.debug(f"Configuración cargada desde {path}")
                except Exception as e:
                    logger.error(f"Error al cargar configuración desde {path}: {e}")
    
    def _load_env_vars(self):
        """
        Carga configuración desde variables de entorno y archivos .env
        """
        # Cargar variables desde .env si existe
        env_path = Path(self.project_root) / "credentials" / ".env"
        if env_path.exists():
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        
                        if '=' in line:
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            
                            # Eliminar comillas si están presentes
                            if (value.startswith('"') and value.endswith('"')) or \
                               (value.startswith("'") and value.endswith("'")):
                                value = value[1:-1]
                                
                            os.environ[key] = value
                logger.debug(f"Variables de entorno cargadas desde {env_path}")
            except Exception as e:
                logger.error(f"Error cargando variables de entorno desde {env_path}: {e}")
        
        # Variables de entorno específicas a mapear a la configuración
        env_mappings = {
            "API_KEY": ("api", "key"),
            "API_URL": ("api", "url"),
            "DEBUG": ("app", "debug"),
            "GOOGLE_API_KEY": ("google", "api_key"),
            "CACHE_DIR": ("paths", "cache_dir"),
        }
        
        for env_var, config_path in env_mappings.items():
            if env_var in os.environ:
                self._set_nested_value(self.config, config_path, os.environ[env_var])
                logger.debug(f"Configuración cargada desde variable de entorno {env_var}")
    
    def _merge_config(self, config_data: Dict[str, Any]):
        """
        Combina la configuración nueva con la existente de forma recursiva.
        
        Args:
            config_data: Nuevos datos de configuración a combinar
        """
        for key, value in config_data.items():
            if key in self.config and isinstance(self.config[key], dict) and isinstance(value, dict):
                self._merge_config_dict(self.config[key], value)
            else:
                self.config[key] = value
    
    def _merge_config_dict(self, target: Dict[str, Any], source: Dict[str, Any]):
        """
        Combina diccionarios de configuración de manera recursiva.
        
        Args:
            target: Diccionario destino
            source: Diccionario fuente
        """
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._merge_config_dict(target[key], value)
            else:
                target[key] = value
    
    def _set_nested_value(self, config_dict: Dict[str, Any], path_parts, value):
        """
        Establece un valor en un diccionario anidado.
        
        Args:
            config_dict: Diccionario de configuración
            path_parts: Partes de la ruta para la ubicación anidada
            value: Valor a establecer
        """
        if isinstance(path_parts, str):
            path_parts = [path_parts]
            
        if len(path_parts) == 1:
            config_dict[path_parts[0]] = value
            return
        
        key = path_parts[0]
        if key not in config_dict:
            config_dict[key] = {}
        
        self._set_nested_value(config_dict[key], path_parts[1:], value)
    
    def generate_paths(self, custom_date: Optional[str] = None) -> Dict[str, str]:
        """
        Genera rutas derivadas basadas en la configuración y fecha proporcionada.
        
        Args:
            custom_date: Fecha en formato ddmmyyyy (opcional)
            
        Returns:
            Diccionario con las rutas generadas
        """
        from datetime import datetime
        
        # Usar fecha proporcionada o fecha actual
        date_str = custom_date if custom_date else datetime.today().strftime('%d%m%Y')
        
        # Base de directorios configurados o por defecto
        base_dir = self.config.get('paths', {}).get('base_dir', os.path.join(self.project_root, 'base'))
        output_dir = self.config.get('paths', {}).get('output_dir', os.path.join(self.project_root, 'output'))
        cache_dir = self.config.get('paths', {}).get('cache_dir', os.path.join(self.project_root, 'cache'))
        
        # PDF de entrada
        pdf_input = os.path.join(base_dir, f"{date_str}.pdf")
        
        # Carpetas específicas para la fecha
        date_output_dir = os.path.join(output_dir, date_str)
        
        # Crear directorios si no existen
        os.makedirs(date_output_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        
        # Rutas de archivos derivados
        paths = {
            # Directorios principales
            'project_root': self.project_root,
            'base_dir': base_dir,
            'output_dir': output_dir,
            'cache_dir': cache_dir,
            'date_output_dir': date_output_dir,
            
            # Archivo PDF de entrada
            'pdf_input': pdf_input,
            
            # Archivos de salida
            'links_extracted_csv': os.path.join(date_output_dir, 'links_extracted.csv'),
            'image_links_json': os.path.join(date_output_dir, 'image_links.json'),
            'social_links_json': os.path.join(date_output_dir, 'social_links.json'),
            'scraped_texts_json': os.path.join(date_output_dir, 'scraped_texts.json'),
            'processing_stats_json': os.path.join(date_output_dir, 'processing_stats.json'),
            
            # Directorios específicos
            'image_download_dir': os.path.join(date_output_dir, 'images'),
            'history_file': os.path.join(cache_dir, 'history.json'),
            
            # Archivos adicionales
            'pdf_text_output': os.path.join(date_output_dir, f'texto_{date_str}.json'),
        }
        
        # Crear directorios adicionales derivados
        os.makedirs(paths['image_download_dir'], exist_ok=True)
        
        # Actualizar caché de rutas y devolver
        self.paths = paths
        return paths
    
    def get(self, key: str, default=None) -> Any:
        """
        Obtiene un valor de configuración por su clave.
        
        Args:
            key: Clave de configuración
            default: Valor por defecto si la clave no existe
            
        Returns:
            Valor de configuración o valor por defecto
        """
        return self.config.get(key, default)
    
    def get_nested(self, *keys, default=None) -> Any:
        """
        Obtiene un valor anidado de configuración.
        
        Args:
            *keys: Secuencia de claves para navegar en la configuración anidada
            default: Valor por defecto si la ruta no existe
            
        Returns:
            Valor de configuración anidado o valor por defecto
        """
        current = self.config
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current
    
    def get_path(self, key: str) -> Optional[str]:
        """
        Obtiene una ruta generada por su clave.
        
        Args:
            key: Clave de la ruta
            
        Returns:
            Ruta o None si no existe
        """
        return self.paths.get(key)
    
    def update_config(self, new_config: Dict[str, Any]):
        """
        Actualiza la configuración con nuevos valores.
        
        Args:
            new_config: Nuevos valores de configuración
        """
        self._merge_config(new_config)
        logger.debug("Configuración actualizada dinámicamente")

# Función auxiliar para obtener la configuración más fácilmente
def get_config(project_root: Optional[str] = None) -> ConfigurationManager:
    """
    Obtiene la instancia del gestor de configuración.
    
    Args:
        project_root: Ruta raíz del proyecto (opcional, solo en la primera llamada)
        
    Returns:
        Instancia de ConfigurationManager
    """
    return ConfigurationManager.get_instance(project_root)

# Ejemplo de uso
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Obtener instancia de configuración
    config_manager = get_config()
    
    # Generar rutas para la fecha actual
    paths = config_manager.generate_paths()
    
    print("Configuración cargada:")
    print(json.dumps(config_manager.config, indent=2))
    
    print("\nRutas generadas:")
    print(json.dumps(paths, indent=2)) 
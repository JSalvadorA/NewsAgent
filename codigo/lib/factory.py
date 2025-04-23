#!/usr/bin/env python3
"""
Fábrica de componentes para el sistema NewsAgent.
Implementa un patrón Factory para administrar la creación y configuración de componentes.
"""

import os
import logging
from typing import Dict, Any, Type, Optional, List, Union
import importlib

from codigo.lib.config_unified import ConfigurationManager
from codigo.lib.api_client import APIClient

logger = logging.getLogger(__name__)

class ComponentFactory:
    """
    Factory que administra la creación y recuperación de componentes del sistema.
    Implementa un patrón Singleton modificado para mantener una única instancia de la fábrica
    pero permitir diferentes instancias configurables de componentes.
    """
    
    _instance = None
    _components = {}
    _config = None
    _default_api_client = None
    
    def __new__(cls, *args, **kwargs):
        """Implementación del patrón Singleton."""
        if cls._instance is None:
            cls._instance = super(ComponentFactory, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Inicializa la fábrica de componentes con la configuración proporcionada.
        
        Args:
            config: Configuración para la fábrica. Si es None, usa la configuración global.
        """
        if self._initialized:
            return
            
        # Inicializar con configuración
        if config is None:
            self._config = ConfigurationManager.get_instance().config
        else:
            self._config = config
            
        # Inicializar colecciones
        self._components = {}
        self._component_types = {}
        
        logger.info("Fábrica de componentes inicializada")
        self._initialized = True
    
    def _get_default_api_client(self) -> APIClient:
        """
        Obtiene o crea el cliente API por defecto.
        
        Returns:
            Instancia del cliente API
        """
        if self._default_api_client is None:
            self._default_api_client = APIClient(self._config)
            logger.debug("Cliente API por defecto creado")
        return self._default_api_client
    
    def register_component_type(self, component_type: str, component_class: Type) -> None:
        """
        Registra un tipo de componente para ser creado por la fábrica.
        
        Args:
            component_type: Nombre del tipo de componente
            component_class: Clase del componente
        """
        self._component_types[component_type] = component_class
        logger.debug(f"Tipo de componente '{component_type}' registrado: {component_class.__name__}")
    
    def register_component(self, component_id: str, component: Any) -> None:
        """
        Registra un componente existente en la fábrica.
        
        Args:
            component_id: Identificador único del componente
            component: Instancia del componente
        """
        if component_id in self._components:
            logger.warning(f"Reemplazando componente existente: {component_id}")
        
        self._components[component_id] = component
        logger.debug(f"Componente registrado: {component_id}")
    
    def create_component(self, component_type: str, component_id: str = None, 
                         config: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        """
        Crea una nueva instancia de un componente del tipo especificado.
        
        Args:
            component_type: Tipo de componente a crear
            component_id: Identificador único para el componente (opcional)
            config: Configuración específica para este componente
            **kwargs: Argumentos adicionales para la inicialización del componente
            
        Returns:
            Instancia del componente creado
            
        Raises:
            ValueError: Si el tipo de componente no está registrado
        """
        # Verificar que el tipo de componente existe
        if component_type not in self._component_types:
            raise ValueError(f"Tipo de componente no registrado: {component_type}")
        
        # Generar ID si no se proporcionó
        if component_id is None:
            component_id = f"{component_type}_{len(self._components) + 1}"
        
        # Combinar configuración general con específica
        component_config = self._config.copy()
        if config:
            # Actualizar solo la sección pertinente al componente si existe
            if component_type in component_config:
                component_config[component_type].update(config)
            else:
                component_config[component_type] = config
        
        # Crear instancia del componente
        try:
            component_class = self._component_types[component_type]
            if 'api_client' not in kwargs:
                kwargs['api_client'] = self._get_default_api_client()
                
            component = component_class(config=component_config, **kwargs)
            
            # Registrar el componente si tiene ID
            if component_id:
                self._components[component_id] = component
                
            logger.info(f"Componente '{component_type}' creado con ID: {component_id}")
            return component
            
        except Exception as e:
            logger.error(f"Error creando componente '{component_type}': {str(e)}")
            raise
    
    def get_component(self, component_id: str) -> Any:
        """
        Obtiene un componente registrado por su ID.
        
        Args:
            component_id: Identificador del componente
            
        Returns:
            El componente solicitado
            
        Raises:
            KeyError: Si el componente no existe
        """
        if component_id not in self._components:
            raise KeyError(f"Componente no encontrado: {component_id}")
        
        return self._components[component_id]
    
    def load_component_module(self, module_path: str) -> bool:
        """
        Carga dinámicamente un módulo de componentes y registra los tipos disponibles.
        
        Args:
            module_path: Ruta al módulo de componentes (ej. 'codigo.components.transcriber')
            
        Returns:
            True si el módulo se cargó correctamente
        """
        try:
            module = importlib.import_module(module_path)
            
            # Buscar y registrar componentes en el módulo
            components_registered = 0
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                # Verificar si es una clase y tiene el atributo COMPONENT_TYPE
                if isinstance(attr, type) and hasattr(attr, 'COMPONENT_TYPE'):
                    self.register_component_type(attr.COMPONENT_TYPE, attr)
                    components_registered += 1
            
            logger.info(f"Módulo cargado: {module_path} ({components_registered} componentes)")
            return True
            
        except ImportError as e:
            logger.error(f"Error cargando módulo de componentes {module_path}: {e}")
            return False
    
    def list_components(self) -> Dict[str, Any]:
        """
        Lista todos los componentes registrados.
        
        Returns:
            Diccionario de componentes registrados
        """
        return self._components.copy()
    
    def list_component_types(self) -> List[str]:
        """
        Lista todos los tipos de componentes disponibles.
        
        Returns:
            Lista de tipos de componentes
        """
        return list(self._component_types.keys())

# Ejemplo de uso básico
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Crear fábrica
    factory = ComponentFactory()
    
    # Ejemplo de creación de un componente (sería necesario registrar el tipo primero)
    try:
        # Suponiendo que ya existe un tipo de componente 'transcriber'
        factory.register_component_type('transcriber', object)  # Aquí normalmente se registraría una clase real
        
        transcriber = factory.create_component('transcriber', 'mi_transcriptor')
        print(f"Componente creado: {transcriber}")
    except Exception as e:
        print(f"Error en el ejemplo: {e}") 
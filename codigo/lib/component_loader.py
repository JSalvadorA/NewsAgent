#!/usr/bin/env python3
"""
Módulo para cargar y registrar automáticamente componentes en la fábrica.
Proporciona una interfaz unificada para integrar componentes con el sistema principal.
"""

import os
import importlib
import logging
import inspect
from pathlib import Path
from typing import Dict, Any, List, Optional, Type, Set

from codigo.lib.factory import ComponentFactory

logger = logging.getLogger(__name__)

class ComponentLoader:
    """
    Cargador de componentes que descubre y registra automáticamente 
    los componentes disponibles en la fábrica.
    """
    
    def __init__(self, factory: Optional[ComponentFactory] = None):
        """
        Inicializa el cargador de componentes.
        
        Args:
            factory: Instancia opcional de ComponentFactory, se creará una nueva si no se proporciona
        """
        self.factory = factory if factory is not None else ComponentFactory()
        self.loaded_modules: Set[str] = set()
        self.available_components: Dict[str, Type] = {}
        
        logger.debug("ComponentLoader inicializado")
    
    def discover_components(self, base_package: str = 'codigo.components') -> Dict[str, str]:
        """
        Descubre automáticamente los componentes disponibles en el paquete especificado.
        
        Args:
            base_package: Paquete base donde buscar componentes
            
        Returns:
            Diccionario de tipos de componentes y sus rutas de módulo
        """
        logger.info(f"Descubriendo componentes en {base_package}")
        components_found: Dict[str, str] = {}
        
        try:
            # Importar el paquete base para obtener su ruta en el sistema de archivos
            base_module = importlib.import_module(base_package)
            base_path = Path(inspect.getfile(base_module)).parent
            
            # Buscar archivos Python que podrían contener componentes
            for file_path in base_path.glob('*.py'):
                if file_path.name.startswith('__'):
                    continue
                    
                module_name = file_path.stem
                full_module_path = f"{base_package}.{module_name}"
                
                try:
                    # Intentar cargar el módulo para ver si tiene componentes
                    module = importlib.import_module(full_module_path)
                    
                    # Buscar clases en el módulo que tengan COMPONENT_TYPE
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and 
                            hasattr(attr, 'COMPONENT_TYPE') and 
                            attr.__module__ == full_module_path):
                            
                            component_type = getattr(attr, 'COMPONENT_TYPE')
                            components_found[component_type] = full_module_path
                            logger.debug(f"Componente encontrado: {component_type} en {full_module_path}")
                
                except (ImportError, AttributeError) as e:
                    logger.warning(f"Error al explorar módulo {full_module_path}: {e}")
                    
            logger.info(f"Se encontraron {len(components_found)} componentes en {base_package}")
            return components_found
            
        except ImportError as e:
            logger.error(f"No se pudo importar el paquete base {base_package}: {e}")
            return {}
    
    def load_all_components(self, base_package: str = 'codigo.components') -> int:
        """
        Carga y registra todos los componentes disponibles en el paquete especificado.
        
        Args:
            base_package: Paquete base donde buscar componentes
            
        Returns:
            Número de componentes cargados
        """
        components = self.discover_components(base_package)
        total_loaded = 0
        
        for component_type, module_path in components.items():
            if self.load_component_module(module_path):
                total_loaded += 1
                
        logger.info(f"Se cargaron {total_loaded} componentes de {len(components)} descubiertos")
        return total_loaded
    
    def load_component_module(self, module_path: str) -> bool:
        """
        Carga un módulo de componentes y registra sus tipos en la fábrica.
        
        Args:
            module_path: Ruta al módulo (p.ej. 'codigo.components.transcriber')
            
        Returns:
            True si se cargó algún componente, False en caso contrario
        """
        if module_path in self.loaded_modules:
            logger.debug(f"Módulo {module_path} ya cargado anteriormente")
            return True
            
        try:
            success = self.factory.load_component_module(module_path)
            if success:
                self.loaded_modules.add(module_path)
                logger.debug(f"Módulo {module_path} cargado correctamente")
                return True
            else:
                logger.warning(f"No se encontraron componentes en {module_path}")
                return False
                
        except Exception as e:
            logger.error(f"Error cargando módulo {module_path}: {e}")
            return False
    
    def create_component(self, component_type: str, component_id: Optional[str] = None, 
                        config: Optional[Dict[str, Any]] = None, **kwargs) -> Any:
        """
        Crea un componente del tipo especificado con la configuración proporcionada.
        
        Args:
            component_type: Tipo de componente a crear
            component_id: ID opcional para el componente
            config: Configuración específica para el componente
            **kwargs: Argumentos adicionales para la inicialización
            
        Returns:
            Instancia del componente creado
            
        Raises:
            ValueError: Si el componente no se puede crear
        """
        # Si el tipo no está registrado, intentar cargarlo automáticamente
        if component_type not in self.factory.list_component_types():
            components = self.discover_components()
            if component_type in components:
                logger.info(f"Cargando automáticamente el componente {component_type}")
                self.load_component_module(components[component_type])
            else:
                raise ValueError(f"Tipo de componente no encontrado: {component_type}")
        
        # Crear el componente
        return self.factory.create_component(component_type, component_id, config, **kwargs)
    
    def list_available_components(self) -> Dict[str, str]:
        """
        Lista todos los componentes disponibles para cargar.
        
        Returns:
            Diccionario con los tipos de componentes y sus rutas de módulo
        """
        return self.discover_components()
    
    def list_loaded_components(self) -> List[str]:
        """
        Lista los tipos de componentes ya cargados en la fábrica.
        
        Returns:
            Lista de tipos de componentes
        """
        return self.factory.list_component_types()

# Función auxiliar para obtener el cargador
def get_component_loader(factory: Optional[ComponentFactory] = None) -> ComponentLoader:
    """
    Obtiene una instancia del cargador de componentes.
    
    Args:
        factory: Instancia opcional de ComponentFactory
        
    Returns:
        Instancia de ComponentLoader
    """
    return ComponentLoader(factory)

# Ejemplo de uso
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Crear cargador
    loader = get_component_loader()
    
    # Descubrir componentes disponibles
    available = loader.discover_components()
    print(f"Componentes disponibles: {available}")
    
    # Cargar todos los componentes
    loaded_count = loader.load_all_components()
    print(f"Componentes cargados: {loaded_count}")
    
    # Listar tipos de componentes cargados
    component_types = loader.list_loaded_components()
    print(f"Tipos de componentes: {component_types}")
    
    # Ejemplo de creación de un componente
    if 'transcriber' in component_types:
        try:
            transcriber = loader.create_component('transcriber', 'my_transcriber')
            print(f"Componente creado: {transcriber}")
        except Exception as e:
            print(f"Error creando componente: {e}") 
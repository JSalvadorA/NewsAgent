# Sistema NewsAgent - Mejoras y Documentación

Este documento describe las mejoras implementadas en el sistema NewsAgent y proporciona instrucciones para su uso.

## Descripción General

El sistema NewsAgent es una plataforma para procesar y analizar contenido de diferentes fuentes, incluyendo archivos PDF, sitios web, imágenes y ahora archivos de audio. El sistema se ha refactorizado para mejorar su modularidad, reutilización de código y facilidad de mantenimiento.

## Mejoras Implementadas

### 1. Configuración Unificada

Se ha implementado un gestor de configuración unificado (`ConfigurationManager`) que combina las funcionalidades previamente dispersas en diferentes archivos:

- **Patrón Singleton**: Asegura una única instancia de configuración en todo el sistema
- **Carga desde múltiples fuentes**: Archivos JSON, YAML y variables de entorno
- **Generación de rutas**: Crea y asegura la existencia de directorios necesarios

### 2. Sistema de Componentes Mejorado

Se ha mejorado el patrón Factory para la gestión de componentes:

- **Carga dinámica**: Los componentes se descubren automáticamente
- **Registro automático**: Los componentes se registran en la fábrica basándose en su atributo `COMPONENT_TYPE`
- **Inyección de dependencias**: Permite pasar clientes API y configuración a los componentes

### 3. Nuevos Componentes

Se han agregado nuevos componentes al sistema:

- **Transcriber**: Componente para transcribir archivos de audio
- **Analyzer**: Componente para analizar texto extraído de diferentes fuentes

### 4. Script de Procesamiento de Audio

Se ha creado un script dedicado para procesar archivos de audio:

- **Modos de procesamiento**: Procesar todos los archivos, solo nuevos, o solo los que faltan
- **Procesamiento por lotes**: Para controlar el consumo de recursos
- **Análisis integrado**: Opción para analizar automáticamente las transcripciones
- **Seguimiento de historial**: Mantiene registro de los archivos ya procesados

## Estructura del Proyecto

```
codigo/
  ├── components/         # Componentes específicos del sistema
  │   ├── transcriber.py  # Componente para transcripción de audio
  │   └── analyzer.py     # Componente para análisis de texto
  ├── lib/                # Bibliotecas y utilidades compartidas
  │   ├── api_client.py   # Cliente para comunicación con APIs
  │   ├── config_unified.py  # Gestor de configuración unificado
  │   ├── component_loader.py  # Cargador dinámico de componentes
  │   ├── factory.py      # Fábrica de componentes
  │   └── ... (otros módulos)
  ├── main.py             # Punto de entrada principal
  └── process_audio.py    # Script para procesamiento de audio
```

## Uso del Sistema

### Configuración

El sistema utiliza archivos de configuración en formato JSON o YAML, y variables de entorno:

1. **Archivos de configuración**:
   - `config/default.json`: Configuración base
   - `credentials/api_keys.json` o `credentials/api_keys.yaml`: Claves de API

2. **Variables de entorno**:
   - `API_KEY`: Clave de API principal
   - `GOOGLE_API_KEY`: Clave para servicios de Google
   - Otras variables definidas en `credentials/.env`

### Procesamiento de Audio

Para procesar archivos de audio, use el script `process_audio.py`:

```bash
# Procesar todos los archivos de audio en un directorio
python codigo/process_audio.py --input carpeta/audio --output carpeta/salida --mode all

# Procesar solo nuevos archivos
python codigo/process_audio.py --input carpeta/audio --output carpeta/salida --mode new

# Procesar y analizar transcripciones
python codigo/process_audio.py --input carpeta/audio --output carpeta/salida --analyze
```

Opciones disponibles:
- `--input`, `-i`: Directorio o archivo de entrada
- `--output`, `-o`: Directorio de salida
- `--mode`, `-m`: Modo de procesamiento (`all`, `new`, `missing`)
- `--batch-size`, `-b`: Número de archivos a procesar en paralelo
- `--pause`, `-p`: Segundos de pausa entre lotes
- `--test`, `-t`: Modo de prueba (no realiza cambios)
- `--analyze`, `-a`: Analiza las transcripciones

### Uso de Componentes en Scripts Personalizados

Para utilizar los componentes en scripts personalizados:

```python
from codigo.lib.component_loader import get_component_loader
from codigo.lib.config_unified import get_config

# Obtener configuración
config = get_config()

# Cargar componentes
loader = get_component_loader()
loader.load_all_components()

# Crear instancias de componentes
transcriber = loader.create_component('transcriber', 'mi_transcriptor')
analyzer = loader.create_component('analyzer', 'mi_analizador')

# Usar componentes
success, result = transcriber.transcribe_file('ruta/a/archivo.mp3')
if success:
    analysis = analyzer.analyze_transcription(result)
```

## Extensión del Sistema

### Crear un Nuevo Componente

Para crear un nuevo componente:

1. Crear un nuevo archivo en la carpeta `codigo/components/`
2. Implementar una clase con el atributo `COMPONENT_TYPE`
3. El componente será automáticamente descubierto y registrado

Ejemplo:

```python
class MiNuevoComponente:
    # Identificador para registro automático
    COMPONENT_TYPE = "mi_tipo"
    
    def __init__(self, config, api_client=None):
        self.config = config
        # Inicialización
```

## Recomendaciones para Desarrollo Futuro

1. **Pruebas unitarias**: Implementar pruebas para asegurar la calidad del código
2. **Documentación**: Mantener documentación actualizada para cada componente
3. **Monitoreo**: Agregar sistema de monitoreo para seguimiento de ejecuciones
4. **Procesamiento asíncrono**: Considerar procesamiento asíncrono para tareas largas
5. **Interfaz web**: Desarrollar una interfaz web para control y visualización

## Solución de Problemas

### Componentes no encontrados

Si un componente no se encuentra:

1. Verificar que el componente tenga el atributo `COMPONENT_TYPE` definido
2. Asegurar que el archivo esté en la carpeta `codigo/components/`
3. Comprobar permisos de lectura en los archivos

### Errores de configuración

Si hay problemas con la configuración:

1. Verificar la existencia de los archivos de configuración
2. Asegurar que los archivos JSON/YAML sean válidos
3. Comprobar que las variables de entorno estén correctamente definidas

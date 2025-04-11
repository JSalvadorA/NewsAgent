# Sistema de Procesamiento de Documentos con OCR

Este sistema permite extraer y procesar información de PDFs, incluyendo la extracción de texto de imágenes mediante API de inteligencia artificial.

## Formas de Ejecución

Existen varias formas de ejecutar el sistema:

### 1. Usando el Notebook Interactivo (Para Usuarios No Técnicos)

El método más sencillo es utilizar el archivo `NewsAg.ipynb` que proporciona una interfaz gráfica con opciones configurables:

1. Abrir `NewsAg.ipynb` en Jupyter Notebook o VS Code
2. Ejecutar las celdas del notebook
3. Usar el panel interactivo con los controles visuales para configurar y ejecutar

### 2. Usando el Script de Opciones desde Terminal

Para ejecución desde terminal con parámetros personalizados:

```bash
python run_with_options.py DDMMYYYY [--batch-size N] [--pause-seconds N] [--prompt TIPO]
```

Ejemplos:
```bash
# Ejecución básica con valores predeterminados
python run_with_options.py 01042025

# Configurando tamaño de lote y pausa
python run_with_options.py 01042025 --batch-size 2 --pause-seconds 90

# Cambiando el tipo de prompt
python run_with_options.py 01042025 --prompt simple
```

### 3. Ejecución Directa desde Terminal

Para usuarios avanzados que prefieren ejecutar el script principal directamente:

```bash
python codigo/main.py DDMMYYYY
```

## Procesamiento Adaptativo de Imágenes

El sistema ahora cuenta con un procesamiento adaptativo de imágenes que:

1. **Procesa secuencialmente**: Procesa imágenes en lotes de tamaño configurable (1-3 recomendado)
2. **Reintenta automáticamente**: Las imágenes que fallen en el primer intento se reintentan una sola vez en el siguiente lote
3. **Evita bloqueos**: Si una imagen falla definitivamente después del reintento, el proceso continúa con las demás
4. **Es configurable**: Permite ajustar el tamaño de lote y la pausa entre lotes según necesidades específicas

### Configuración Recomendada

- **batch_size=3**: Para colecciones de imágenes ligeras
- **batch_size=2**: Para colecciones con algunas imágenes pesadas/complejas
- **batch_size=1**: Para colecciones de imágenes muy pesadas o complejas
- **pause_seconds=60**: Pausa estándar entre lotes para evitar límites de API

## Herramientas Adicionales

### Gestión de Imágenes Omitidas

Si algunas imágenes son marcadas como "demasiado pesadas" para procesar, puede usar la herramienta de gestión:

```bash
python codigo/manage_skipped_images.py
```

Esta herramienta permite:
- Listar imágenes omitidas permanentemente
- Eliminar imágenes específicas de la lista para reintentar su procesamiento
- Limpiar toda la lista de imágenes omitidas

## Requisitos

- Python 3.7+
- Google Gemini API (configurada en credentials/.env)
- Bibliotecas: consulte requirements.txt

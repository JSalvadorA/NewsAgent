# NewsAgent - Optimización del Procesamiento de Imágenes

Esta carpeta contiene módulos mejorados para optimizar el procesamiento de imágenes en el sistema NewsAgent, enfocados principalmente en:

1. Análisis de complejidad más preciso para imágenes
2. Preprocesamiento adaptativo de imágenes grandes o complejas
3. Gestión mejorada de cuotas de API y manejo de errores
4. Implementación de fallback a OCR local (Tesseract) cuando Gemini falla

## Problema Resuelto

El sistema original tenía limitaciones a la hora de analizar correctamente la complejidad de imágenes, lo que resultaba en:

- Tiempos de procesamiento excesivamente largos para imágenes complejas
- Errores de timeout y cuota agotada con la API de Gemini
- Falta de optimización para imágenes grandes
- Clasificación incorrecta de imágenes que requerían procesamiento individual

La nueva implementación utiliza un análisis multifactorial avanzado que evalúa:
- Tamaño del archivo
- Resolución de la imagen
- Densidad de texto (mediante análisis de bordes)
- Heterogeneidad (variabilidad entre diferentes sectores de la imagen)
- Presencia de estructuras tipo tabla
- Textura y complejidad general

## Archivos Incluidos

1. **complexity_analyzer.py**: 
   - Implementación del análisis de complejidad mejorado
   - Funciones de preprocesamiento para optimizar imágenes

2. **optimize_image_processing.py**: 
   - Script completo para procesar imágenes con el nuevo enfoque
   - Integra análisis de complejidad, preprocesamiento y extracción de texto
   - Puede usarse de forma independiente o integrarse al sistema existente

## Uso Independiente

Para usar la optimización de forma independiente:

```bash
python optimize_image_processing.py --dir C:\ruta\a\directorio\imagenes --output C:\ruta\resultados --date 24042025 --workers 2 --pause 30 --tesseract
```

Parámetros:
- `--dir`: Directorio con las imágenes (obligatorio)
- `--output`: Directorio de salida para resultados (opcional)
- `--date`: Fecha en formato ddmmyyyy para nombrar archivos (opcional)
- `--workers`: Número de trabajadores en paralelo para imágenes simples (defecto: 2)
- `--pause`: Segundos de pausa entre procesamiento (defecto: 30)
- `--tesseract`: Usar Tesseract OCR como fallback cuando Gemini falla

## Integración con el Sistema Existente

Para integrar estas mejoras con el sistema existente de NewsAgent, tienes dos opciones:

### Opción 1: Usar directamente el script optimizado

En `main_with_dedup.py`, cuando llegues a la sección de procesamiento de imágenes, puedes reemplazar el código existente por:

```python
# --- 6. Procesar Imágenes (Descarga) ---
logger.info("--- Paso 4: Procesando Imágenes (Descarga) ---")
image_links = categories.get('images', [])
if image_links:
    # Primero descargar las imágenes como antes
    img_down_start = time.time()
    downloaded_image_metadata = image_processor.download_images_parallel(image_links, today_date_for_filename)
    img_down_duration = time.time() - img_down_start
    logger.info(f"Descarga de imágenes completada en {img_down_duration:.2f} seg.")
    
    if downloaded_image_metadata:
        history_tracker.add_processed_urls(list(downloaded_image_metadata.keys()))
        
        # Usar el optimizador mejorado para procesar las imágenes
        from improved.optimize_image_processing import optimize_and_process_images
        
        # Directorio de imágenes para esta fecha
        image_dir = os.path.join(project_root, 'output', today_date_for_filename, 'images')
        
        # Procesar con optimizaciones
        img_api_start = time.time()
        results = optimize_and_process_images(
            image_dir=image_dir,
            output_dir=image_dir,
            date_str=today_date_for_filename,
            max_workers=2,
            pause_seconds=30,
            use_tesseract=True  # Activar fallback a Tesseract
        )
        img_api_duration = time.time() - img_api_start
        
        # Actualizar processed_data con los resultados
        processed_data["images_api"] = results
        
        logger.info(f"Procesamiento optimizado de imágenes completado en {img_api_duration:.2f} seg.")
else:
    logger.info("No hay nuevas URLs de imágenes para descargar.")
```

### Opción 2: Reemplazar solo el análisis de complejidad

Si prefieres mantener más de la estructura original, puedes reemplazar solo el método `estimate_image_complexity` en la clase `EnhancedImageProcessor`:

1. Importa el analizador mejorado:
```python
from improved.complexity_analyzer import analyze_image_complexity, preprocess_image
```

2. Modifica el método en la clase:
```python
def estimate_image_complexity(self, image_path):
    """Versión mejorada que usa el analizador avanzado"""
    try:
        # Usar el analizador mejorado
        complexity_score, text_estimate, needs_individual = analyze_image_complexity(image_path)
        
        # Para compatibilidad con el sistema original
        logger.info(f"Complejidad de imagen {os.path.basename(image_path)}: "
                   f"score={complexity_score:.2f}, texto_est={text_estimate}, "
                   f"individual={needs_individual}")
        
        return complexity_score, text_estimate, needs_individual
            
    except Exception as e:
        logger.error(f"Error estimando complejidad de imagen {image_path}: {e}")
        # En caso de error, asumir que es compleja para ser conservadores
        return 0.7, 3000, True
```

3. Agrega preprocesamiento de imágenes en `process_image`:
```python
def process_image(self, img_path):
    # Verificar si tenemos resultados en caché para imágenes similares
    cached_result = self._find_cached_result(img_path)
    if cached_result:
        logger.info(f"Usando resultado en caché para imagen similar: {os.path.basename(img_path)}")
        return cached_result
    
    # Preprocesar imagen si es necesario
    if self.enable_preprocessing:
        preprocessed_dir = os.path.join(os.path.dirname(img_path), "preprocessed")
        os.makedirs(preprocessed_dir, exist_ok=True)
        proc_path, was_processed = preprocess_image(img_path, preprocessed_dir, self.max_image_size_mb)
        path_to_use = proc_path if was_processed else img_path
    else:
        path_to_use = img_path
        
    # Resto del código original...
```

## Requisitos

Para utilizar todas las funcionalidades:

- Python 3.7+
- OpenCV (`pip install opencv-python`)
- NumPy (`pip install numpy`)
- Pillow (`pip install pillow`)
- Pytesseract (opcional, para fallback OCR: `pip install pytesseract`)
- Tesseract OCR instalado en el sistema (opcional, para fallback)

## Notas de Implementación

- Los umbrales de complejidad se han ajustado para clasificar correctamente más imágenes como "complejas"
- Se añadió preprocesamiento automático para imágenes grandes (>1.5MB)
- Se reducen imágenes grandes manteniendo la calidad óptima para OCR
- Se mejora el contraste y nitidez para optimizar la detección de texto
- Se implementó fallback a Tesseract OCR cuando la API de Gemini falla

Esta implementación debería resolver los problemas observados con imágenes complejas y mejorar significativamente la robustez del sistema.

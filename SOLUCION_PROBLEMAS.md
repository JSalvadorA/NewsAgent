# Solución de Problemas en el Sistema NewsAg

## Problemas Identificados

Después de analizar el código y el sistema, se han identificado los siguientes problemas:

1. **No se genera el archivo `scraped_texts_ddmmyyyy.json`**: El sistema no está generando correctamente los archivos de texto extraídos de sitios web.

2. **No se están descargando las imágenes**: Las imágenes no se están descargando correctamente y no aparecen en el directorio correspondiente.

3. **No se están generando archivos en `Out`**: Los archivos de salida no se están creando en las ubicaciones esperadas.

## Causas Probables

1. **Cache limpio**: Al eliminar todas las salidas y el caché, el sistema puede tener problemas para reconocer qué URLs ya se han procesado.

2. **Filtrado de historial**: El sistema está filtrando URLs que ya han sido procesadas anteriormente, lo que impide su reprocesamiento.

3. **Problemas de permisos**: Puede haber problemas de permisos de escritura en algunas carpetas clave.

## Soluciones

Se han creado dos scripts específicos para solucionar estos problemas:

### 1. Verificar el Sistema

El script `verificar_sistema.py` comprueba:
- La estructura de directorios necesaria
- El archivo de historial
- Los permisos de escritura
- La configuración de rutas
- Los módulos Python necesarios
- Los datos de salida existentes

Para ejecutarlo:
```
python verificar_sistema.py
```

### 2. Forzar el Reprocesamiento

El script `reprocesar.py` permite ejecutar el pipeline ignorando el historial, lo que fuerza el reprocesamiento de todas las URLs, independientemente de si ya fueron procesadas antes.

Para reprocesar una fecha específica:
```
python reprocesar.py 05032025
```

Parámetros opcionales:
- `--prompt`: Tipo de prompt para la API (simple, detallado, estructurado, anti-ruido)
- `--batch-size`: Tamaño del lote de imágenes (1-5)
- `--pause`: Pausa entre lotes en segundos (10-300)

Ejemplo con parámetros:
```
python reprocesar.py 05032025 --prompt detallado --batch-size 3 --pause 60
```

## Instrucciones Paso a Paso

Para resolver los problemas identificados, siga estos pasos:

1. **Verificar el sistema**:
   ```
   python verificar_sistema.py
   ```
   Esto comprobará y corregirá problemas básicos, creando carpetas y verificando permisos.

2. **Reprocesar la fecha problemática**:
   ```
   python reprocesar.py 05032025
   ```
   Esto forzará el procesamiento completo de todas las URLs para la fecha 05032025, ignorando el historial.

3. **Verificar los resultados**: Una vez completado el reprocesamiento, compruebe:
   - Si se ha creado el archivo `input/Out/scraped_texts_05032025.json`
   - Si hay imágenes en `input/Images/downloads/05032025`
   - Si se ha generado el archivo `output/consolidated_05032025.json`

## Notas Importantes

- El reprocesamiento puede llevar tiempo, especialmente si hay muchas URLs para procesar.
- Se creará un backup de archivos importantes antes de realizar cambios.
- Los archivos existentes no se eliminarán, pero pueden ser sobrescritos durante el reprocesamiento.
- Si después del reprocesamiento sigue habiendo problemas, puede ser necesario revisar el código de las funciones específicas que fallan.

## Modificaciones Realizadas al Sistema

Para solucionar el problema, se han realizado las siguientes modificaciones:

1. Se ha añadido la capacidad de ignorar el historial mediante una variable de entorno:
   ```python
   # En history_tracker.py
   def get_unprocessed_links(self, all_links, current_date):
       import os
       ignorar_historial = os.environ.get("IGNORAR_HISTORIAL", "").lower() == "true"
       
       if ignorar_historial:
           logger.info("MODO REPROCESAMIENTO: Ignorando historial de URLs")
           return all_links
       # ...
   ```

2. Se han creado scripts independientes (`verificar_sistema.py` y `reprocesar.py`) para facilitar la solución de problemas sin modificar el código principal.

3. Se mantiene la compatibilidad con el notebook `NewsAg.ipynb` original, que sigue funcionando normalmente.

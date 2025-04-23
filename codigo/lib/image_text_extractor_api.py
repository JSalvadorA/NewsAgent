#!/usr/bin/env python3
"""
Adaptador para el módulo GeminiImageExtractor.
Proporciona una interfaz compatible con el ImageProcessor.
"""

import os
import logging
import json
from datetime import datetime
from pathlib import Path

# Importar el módulo de extracción de imágenes de Gemini
from .gemini_image_extractor import GeminiImageExtractor

logger = logging.getLogger(__name__)

class ImageTextExtractorAPI:
    """
    Clase adaptadora para extraer texto de imágenes usando Gemini API.
    Se implementa como un wrapper alrededor de GeminiImageExtractor.
    """
    
    def __init__(self, api_key=None, model_name='gemini-1.5-pro-latest', prompt_key='detallado'):
        """
        Inicializa el extractor de texto de imágenes.
        
        Args:
            api_key: API key para Gemini (si es None, se buscará en variables de entorno)
            model_name: Nombre del modelo de Gemini a utilizar
            prompt_key: Clave del prompt predefinido a usar
        """
        self.model_name = model_name
        self.prompt_key = prompt_key
        
        try:
            self.extractor = GeminiImageExtractor(
                api_key=api_key,
                prompt_key=prompt_key,
                model_name=model_name
            )
            logger.info(f"ImageTextExtractorAPI inicializado con modelo {model_name}")
        except Exception as e:
            error_msg = f"Error al inicializar GeminiImageExtractor: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    def extract_text_from_image(self, image_path):
        """
        Extrae texto de una imagen usando Gemini.
        
        Args:
            image_path: Ruta al archivo de imagen
            
        Returns:
            dict: Diccionario con resultados o error
        """
        try:
            # Verificar que el archivo existe
            if not os.path.exists(image_path):
                logger.error(f"Imagen no encontrada: {image_path}")
                return {
                    "error": "Archivo no encontrado",
                    "image_filename": os.path.basename(image_path),
                    "processed_date": datetime.now().strftime('%d%m%Y')
                }
            
            # Extraer texto usando el extractor de Gemini
            extracted_text = self.extractor.extract_text_from_image(image_path)
            
            # Crear estructura de respuesta
            result = {
                "image_filename": os.path.basename(image_path),
                "processed_date": datetime.now().strftime('%d%m%Y'),
                "extracted_text": extracted_text if extracted_text else "",
                "model_used": self.model_name,
                "prompt_type": self.prompt_key
            }
            
            # Si hay texto extraído, considerar exitoso
            if extracted_text:
                return result
            else:
                # Si no se extrajo texto, marcar como error
                result["error"] = "No se pudo extraer texto de la imagen"
                return result
                
        except Exception as e:
            logger.error(f"Error al extraer texto de {os.path.basename(image_path)}: {str(e)}")
            return {
                "error": f"Error de procesamiento: {str(e)}",
                "image_filename": os.path.basename(image_path),
                "processed_date": datetime.now().strftime('%d%m%Y'),
                "extracted_text": ""
            }
    
    def process_batch(self, image_paths, output_path=None):
        """
        Procesa un lote de imágenes.
        
        Args:
            image_paths: Lista de rutas a imágenes
            output_path: Ruta donde guardar resultados (opcional)
            
        Returns:
            list: Lista de resultados para cada imagen
        """
        results = []
        
        for idx, image_path in enumerate(image_paths, 1):
            logger.info(f"Procesando imagen {idx}/{len(image_paths)}: {os.path.basename(image_path)}")
            result = self.extract_text_from_image(image_path)
            results.append(result)
            
            # Hacer una pausa para no sobrecargar la API
            if idx < len(image_paths):
                import time
                time.sleep(2)  # 2 segundos entre imágenes
        
        # Guardar resultados si se especificó una ruta
        if output_path and results:
            try:
                # Asegurar que el directorio existe
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, ensure_ascii=False, indent=4)
                logger.info(f"Resultados guardados en: {output_path}")
            except Exception as e:
                logger.error(f"Error al guardar resultados en {output_path}: {str(e)}")
        
        return results

# Ejemplo de uso
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    try:
        # Crear extractor
        extractor = ImageTextExtractorAPI()
        
        # Ejemplo de procesamiento de una imagen
        example_image = "ruta/a/imagen.jpg"
        if os.path.exists(example_image):
            result = extractor.extract_text_from_image(example_image)
            print(f"Resultado: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print(f"Imagen de ejemplo no encontrada: {example_image}")
    except Exception as e:
        print(f"Error en ejemplo: {e}")

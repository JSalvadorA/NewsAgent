"""
complexity_analyzer.py
Implementación mejorada del análisis de complejidad de imágenes para el sistema NewsAgent.
Este módulo se encarga de evaluar la complejidad de las imágenes para determinar si necesitan
procesamiento individual o en lotes.
"""

import os
import cv2
import numpy as np
import logging
from PIL import Image, ImageFilter, ImageEnhance
import math

# Configurar logging
logger = logging.getLogger("complexity_analyzer")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

def analyze_image_complexity(image_path):
    """
    Analiza la complejidad de una imagen basada en múltiples criterios.
    
    Args:
        image_path: Ruta a la imagen a analizar
        
    Returns:
        tuple: (score_complejidad, texto_estimado, necesita_procesamiento_individual)
    """
    try:
        # 1. Tamaño del archivo como primer indicador
        file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
        
        # Si la imagen es muy grande, automáticamente es compleja
        if file_size_mb > 2.0:
            logger.info(f"Imagen {os.path.basename(image_path)} clasificada como compleja por tamaño ({file_size_mb:.2f}MB)")
            return 0.75, 5000, True
            
        # 2. Intentamos abrir y analizar la imagen
        try:
            img = cv2.imread(image_path)
            if img is None:
                logger.warning(f"No se pudo leer la imagen: {os.path.basename(image_path)}")
                return 0.7, 3000, True  # Asumimos que es compleja si no podemos leerla
        except Exception as img_err:
            logger.error(f"Error al abrir imagen {os.path.basename(image_path)}: {img_err}")
            return 0.7, 3000, True
            
        # Verificamos las dimensiones de la imagen
        height, width = img.shape[:2]
        resolution = width * height
        
        # Si la resolución es muy alta, considerarla compleja
        if resolution > 4000000:  # Más de 4 megapíxeles
            logger.info(f"Imagen {os.path.basename(image_path)} clasificada como compleja por resolución ({width}x{height})")
            return 0.7, 4000, True
        
        # Convertir a escala de grises para análisis
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 3. Análisis avanzado de características
        
        # a) Detección de bordes con dos umbrales diferentes
        edges_loose = cv2.Canny(gray, 50, 150)  # Detecta más bordes (sensible)
        edges_tight = cv2.Canny(gray, 100, 200)  # Solo bordes definidos
        
        # Más diferencia entre bordes sueltos y definidos indica contenido complejo
        edge_ratio_loose = np.count_nonzero(edges_loose) / edges_loose.size
        edge_ratio_tight = np.count_nonzero(edges_tight) / edges_tight.size
        edge_complexity = edge_ratio_loose - edge_ratio_tight
        
        # b) Análisis de textura (desviación estándar)
        texture_score = np.std(gray) / 128.0  # Normalizado a aproximadamente 0-1
        
        # c) Análisis de sectores para detectar heterogeneidad
        sector_h = 3  # Dividir en 3x3 = 9 sectores
        sector_w = 3
        
        sector_height = height // sector_h
        sector_width = width // sector_w
        
        sector_scores = []
        for y in range(0, height, sector_height):
            for x in range(0, width, sector_width):
                # Evitar sectores fuera de límites
                if y + sector_height <= height and x + sector_width <= width:
                    sector = gray[y:y+sector_height, x:x+sector_width]
                    if sector.size > 0:
                        sector_std = np.std(sector)
                        sector_scores.append(sector_std)
        
        # Calcular variabilidad entre sectores
        if sector_scores:
            sector_mean = np.mean(sector_scores)
            sector_variability = np.std(sector_scores) / sector_mean if sector_mean > 0 else 0
        else:
            sector_variability = 0
        
        # d) Detección de tablas y estructuras reticulares
        # Usamos transformada de Hough para detectar líneas rectas (indicativo de tablas)
        lines = cv2.HoughLinesP(edges_tight, 1, np.pi/180, 100, minLineLength=100, maxLineGap=10)
        has_table_structure = lines is not None and len(lines) > 5
        
        # 4. Calcular estimación de texto
        # Basado en bordes finos y textura (indicadores de texto)
        text_estimate = int((edge_ratio_tight * 1.5 + texture_score) * resolution / 40)
        
        # 5. Ponderar factores para score final
        size_score = min(file_size_mb / 3.0, 1.0)  # Normalizado a 3MB
        
        # Componentes de complejidad con diferentes pesos
        complexity_components = {
            "tamaño": size_score,
            "bordes": edge_ratio_tight,
            "textura": texture_score,
            "heterogeneidad": sector_variability,
            "tablas": 0.5 if has_table_structure else 0.0
        }
        
        # Ponderación final
        complexity_score = (
            0.15 * complexity_components["tamaño"] +
            0.25 * complexity_components["bordes"] +
            0.25 * complexity_components["textura"] +
            0.25 * complexity_components["heterogeneidad"] +
            0.10 * complexity_components["tablas"]
        )
        
        # Clasificar según criterios ajustados (umbrales más bajos)
        needs_individual_processing = (
            complexity_score > 0.5 or          # Score mayor a 0.5
            file_size_mb > 1.5 or              # Tamaño mayor a 1.5MB
            text_estimate > 4000 or            # Mucho texto estimado
            has_table_structure or             # Tiene estructuras tipo tabla
            sector_variability > 0.5           # Alta variabilidad entre sectores
        )
        
        # Añadir logging detallado para debug
        logger.info(f"Análisis de complejidad para {os.path.basename(image_path)}: "
                   f"score={complexity_score:.2f}, tamaño={file_size_mb:.2f}MB, "
                   f"texto_est={text_estimate}, bordes={edge_ratio_tight:.2f}, "
                   f"individual={needs_individual_processing}")
        
        return complexity_score, text_estimate, needs_individual_processing
        
    except Exception as e:
        logger.error(f"Error analizando complejidad de {os.path.basename(image_path)}: {e}")
        # En caso de error, asumimos que es compleja por seguridad
        return 0.7, 4000, True


def preprocess_image(image_path, output_dir=None, max_size_mb=1.5, prefix="preprocessed_"):
    """
    Preprocesa una imagen para mejorar su procesamiento con Gemini.
    Redimensiona, optimiza y mejora la imagen para obtener mejores resultados de OCR.
    
    Args:
        image_path: Ruta a la imagen original
        output_dir: Directorio para guardar imagen procesada (None=mismo directorio)
        max_size_mb: Tamaño máximo en MB para la imagen procesada
        prefix: Prefijo para el nombre de la imagen procesada
        
    Returns:
        tuple: (ruta_imagen_procesada, fue_procesada)
    """
    try:
        # 1. Verificar si la imagen necesita procesamiento
        file_size_mb = os.path.getsize(image_path) / (1024 * 1024)
        if file_size_mb <= max_size_mb:
            logger.info(f"Imagen {os.path.basename(image_path)} no necesita preprocesamiento ({file_size_mb:.2f}MB)")
            return image_path, False
        
        # 2. Determinar directorio de salida
        if not output_dir:
            output_dir = os.path.dirname(image_path)
        os.makedirs(output_dir, exist_ok=True)
        
        # 3. Generar nombre para la imagen procesada
        base_name = os.path.basename(image_path)
        processed_path = os.path.join(output_dir, f"{prefix}{base_name}")
        
        # 4. Abrir y procesar la imagen
        with Image.open(image_path) as img:
            # Convertir a RGB si es necesario
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Obtener dimensiones originales
            orig_width, orig_height = img.size
            
            # Calcular factor de escala para alcanzar el tamaño objetivo
            target_size_mb = max_size_mb * 0.9  # Margen de seguridad del 10%
            current_ratio = file_size_mb / target_size_mb
            scale_factor = 1.0 / math.sqrt(current_ratio)
            
            # Calcular nuevas dimensiones
            new_width = int(orig_width * scale_factor)
            new_height = int(orig_height * scale_factor)
            
            # Limitar dimensiones máximas (mayoría de APIs tienen límites)
            max_dimension = 2000
            if new_width > max_dimension or new_height > max_dimension:
                if new_width > new_height:
                    new_height = int(new_height * (max_dimension / new_width))
                    new_width = max_dimension
                else:
                    new_width = int(new_width * (max_dimension / new_height))
                    new_height = max_dimension
            
            # Redimensionar con algoritmo de alta calidad
            resized_img = img.resize((new_width, new_height), Image.LANCZOS)
            
            # Aplicar mejoras para OCR
            # 1. Nitidez aumentada para compensar redimensionamiento
            enhanced_img = resized_img.filter(ImageFilter.SHARPEN)
            
            # 2. Mejorar contraste ligeramente
            enhancer = ImageEnhance.Contrast(enhanced_img)
            contrast_img = enhancer.enhance(1.2)  # Aumentar contraste en 20%
            
            # 3. Guardar con compresión optimizada
            contrast_img.save(processed_path, optimize=True, quality=85)
            
            new_size_mb = os.path.getsize(processed_path) / (1024 * 1024)
            logger.info(f"Imagen preprocesada: {os.path.basename(image_path)} -> {os.path.basename(processed_path)}, "
                       f"tamaño: {file_size_mb:.2f}MB -> {new_size_mb:.2f}MB, "
                       f"dimensiones: {orig_width}x{orig_height} -> {new_width}x{new_height}")
            
            return processed_path, True
            
    except Exception as e:
        logger.error(f"Error preprocesando imagen {os.path.basename(image_path)}: {e}")
        return image_path, False  # Retornar original si hay error


if __name__ == "__main__":
    # Para pruebas desde línea de comandos
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Analiza y preprocesa imágenes")
    parser.add_argument("images", nargs="+", help="Rutas a imágenes para analizar")
    parser.add_argument("--preprocess", action="store_true", help="Preprocesar imágenes")
    parser.add_argument("--output-dir", help="Directorio para imágenes preprocesadas")
    
    args = parser.parse_args()
    
    for img_path in args.images:
        if not os.path.exists(img_path):
            print(f"Error: Imagen no encontrada: {img_path}")
            continue
            
        print(f"\nAnalizando imagen: {img_path}")
        score, text_est, is_complex = analyze_image_complexity(img_path)
        print(f"Resultado: score={score:.2f}, texto_estimado={text_est}, compleja={is_complex}")
        
        if args.preprocess:
            proc_path, was_processed = preprocess_image(img_path, args.output_dir)
            if was_processed:
                print(f"Imagen preprocesada guardada en: {proc_path}")
            else:
                print(f"No fue necesario preprocesar la imagen")

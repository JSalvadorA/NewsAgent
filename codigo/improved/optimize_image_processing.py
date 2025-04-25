"""
optimize_image_processing.py
Script para optimizar el procesamiento de imágenes en NewsAgent.
Puede utilizarse como módulo independiente o como punto de entrada para procesar imágenes.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Añadir directorio padre al path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
project_root = os.path.abspath(os.path.join(parent_dir, '..'))

if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Importar analizador de complejidad
from complexity_analyzer import analyze_image_complexity, preprocess_image

# Configurar logging
log_dir = os.path.join(project_root, 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'optimized_image_processing.log')

logger = logging.getLogger("optimize_image_processing")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

# Intenta importar los módulos originales de NewsAgent
try:
    from lib.gemini_image_extractor import GeminiImageExtractor
    GEMINI_AVAILABLE = True
except ImportError:
    logger.warning("No se pudo importar GeminiImageExtractor. Usando solo análisis de complejidad.")
    GEMINI_AVAILABLE = False

# Intenta importar pytesseract para OCR local
try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    logger.warning("Pytesseract no disponible. OCR local desactivado.")
    TESSERACT_AVAILABLE = False


def optimize_and_process_images(image_dir, output_dir=None, date_str=None, max_workers=2, 
                              pause_seconds=30, api_key=None, use_tesseract=False):
    """
    Optimiza y procesa imágenes con mejor manejo de complejidad y preprocesamiento.
    
    Args:
        image_dir: Directorio con las imágenes a procesar
        output_dir: Directorio para guardar resultados (None=mismo directorio)
        date_str: Fecha en formato ddmmyyyy para nombrar archivos
        max_workers: Número máximo de trabajadores en paralelo
        pause_seconds: Segundos de pausa entre procesamiento de imágenes
        api_key: Clave API de Gemini (None=buscar en .env)
        use_tesseract: Si es True, usar Tesseract para OCR local
        
    Returns:
        dict: Resultados del procesamiento
    """
    # Verificar y preparar directorios
    if not os.path.exists(image_dir):
        logger.error(f"Directorio de imágenes no encontrado: {image_dir}")
        return {}
    
    if not output_dir:
        output_dir = image_dir
    os.makedirs(output_dir, exist_ok=True)
    
    # Preparar directorio para imágenes preprocesadas
    preprocessed_dir = os.path.join(output_dir, "preprocessed")
    os.makedirs(preprocessed_dir, exist_ok=True)
    
    # Usar fecha actual si no se proporciona
    if not date_str:
        date_str = datetime.now().strftime('%d%m%Y')
    
    # Buscar imágenes en el directorio
    images = []
    for file in os.listdir(image_dir):
        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
            images.append(os.path.join(image_dir, file))
    
    if not images:
        logger.warning(f"No se encontraron imágenes en {image_dir}")
        return {}
    
    logger.info(f"Encontradas {len(images)} imágenes para procesar en {image_dir}")
    
    # Inicializar extractor de Gemini si está disponible
    gemini_extractor = None
    if GEMINI_AVAILABLE:
        try:
            gemini_extractor = GeminiImageExtractor(api_key=api_key)
            logger.info("Extractor Gemini inicializado correctamente")
        except Exception as e:
            logger.error(f"Error inicializando Gemini: {e}")
    
    # Analizar complejidad de todas las imágenes
    complex_images = []
    simple_images = []
    
    for img_path in images:
        try:
            score, text_est, is_complex = analyze_image_complexity(img_path)
            if is_complex:
                complex_images.append(img_path)
            else:
                simple_images.append(img_path)
        except Exception as e:
            logger.error(f"Error analizando {os.path.basename(img_path)}: {e}")
            # Si hay error en el análisis, clasificarla como compleja
            complex_images.append(img_path)
    
    logger.info(f"Clasificación: {len(complex_images)} imágenes complejas, {len(simple_images)} imágenes simples")
    
    # Preprocesar todas las imágenes (tanto complejas como simples)
    preprocessed_map = {}  # Mapa de original -> preprocesada
    
    for img_path in images:
        try:
            proc_path, was_processed = preprocess_image(img_path, preprocessed_dir)
            preprocessed_map[img_path] = proc_path
        except Exception as e:
            logger.error(f"Error al preprocesar {os.path.basename(img_path)}: {e}")
            preprocessed_map[img_path] = img_path  # Usar original si falla
    
    # Función para procesar una imagen con Gemini o Tesseract
    def process_image(img_path):
        start_time = time.time()
        img_name = os.path.basename(img_path)
        
        # Usar versión preprocesada si existe
        path_to_use = preprocessed_map.get(img_path, img_path)
        
        # Resultado por defecto
        result = {
            "image_path": img_path,
            "processed_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "file_size_mb": round(os.path.getsize(img_path) / (1024 * 1024), 2),
            "detected_text": "",
            "success": False,
            "processing_time_seconds": 0
        }
        
        try:
            # Intentar procesar con Gemini primero
            if gemini_extractor:
                logger.info(f"Procesando {img_name} con Gemini API")
                text = gemini_extractor.extract_text_from_image(path_to_use)
                if text:
                    result["detected_text"] = text
                    result["success"] = True
                    result["processor"] = "gemini"
            
            # Si Gemini falla o no está disponible, intentar Tesseract
            if not result["success"] and use_tesseract and TESSERACT_AVAILABLE:
                logger.info(f"Procesando {img_name} con Tesseract OCR local")
                text = pytesseract.image_to_string(
                    Image.open(path_to_use),
                    lang='spa+eng',  # Español e inglés
                    config='--psm 3'  # Modo de segmentación automática
                )
                if text:
                    result["detected_text"] = text.strip()
                    result["success"] = True
                    result["processor"] = "tesseract"
            
            # Si ambos métodos fallan
            if not result["success"]:
                logger.warning(f"No se pudo extraer texto de {img_name}")
                result["error"] = "No text detected by any processor"
                
        except Exception as e:
            logger.error(f"Error procesando {img_name}: {e}")
            result["error"] = str(e)
        
        # Registrar tiempo de procesamiento
        processing_time = time.time() - start_time
        result["processing_time_seconds"] = round(processing_time, 2)
        
        if result["success"]:
            chars_count = len(result["detected_text"])
            logger.info(f"Imagen {img_name} procesada exitosamente en {processing_time:.2f}s - {chars_count} caracteres")
        else:
            logger.warning(f"Imagen {img_name} procesada sin éxito en {processing_time:.2f}s")
            
        return result
    
    # Procesar primero las imágenes complejas de forma individual
    all_results = []
    
    if complex_images:
        logger.info(f"Procesando {len(complex_images)} imágenes complejas individualmente...")
        
        for idx, img_path in enumerate(complex_images, 1):
            logger.info(f"Procesando imagen compleja {idx}/{len(complex_images)}: {os.path.basename(img_path)}")
            result = process_image(img_path)
            all_results.append(result)
            
            # Guardar resultados parciales
            output_json = os.path.join(output_dir, f"text_extraction_results_{date_str}.json")
            try:
                with open(output_json, 'w', encoding='utf-8') as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error guardando resultados parciales: {e}")
            
            # Pausa entre imágenes complejas
            if idx < len(complex_images):
                logger.info(f"Pausa de {pause_seconds} segundos...")
                time.sleep(pause_seconds)
    
    # Procesar imágenes simples con ThreadPoolExecutor
    if simple_images:
        logger.info(f"Procesando {len(simple_images)} imágenes simples en paralelo...")
        
        # Calcular tamaño de lote óptimo
        batch_size = min(max_workers, len(simple_images))
        batches = [simple_images[i:i+batch_size] for i in range(0, len(simple_images), batch_size)]
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"Procesando lote {batch_idx}/{len(batches)} con {len(batch)} imágenes")
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_img = {executor.submit(process_image, img_path): img_path for img_path in batch}
                
                for future in as_completed(future_to_img):
                    result = future.result()
                    all_results.append(result)
            
            # Guardar resultados parciales
            output_json = os.path.join(output_dir, f"text_extraction_results_{date_str}.json")
            try:
                with open(output_json, 'w', encoding='utf-8') as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error guardando resultados parciales: {e}")
            
            # Pausa entre lotes
            if batch_idx < len(batches):
                logger.info(f"Pausa de {pause_seconds} segundos...")
                time.sleep(pause_seconds)
    
    # Guardar resultados finales
    output_json = os.path.join(output_dir, f"text_extraction_results_{date_str}.json")
    try:
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        logger.info(f"Resultados guardados en {output_json}")
    except Exception as e:
        logger.error(f"Error guardando resultados finales: {e}")
    
    # Generar estadísticas
    total_images = len(images)
    successful = sum(1 for r in all_results if r.get("success", False))
    avg_time = round(sum(r.get("processing_time_seconds", 0) for r in all_results) / total_images, 2) if total_images > 0 else 0
    total_chars = sum(len(r.get("detected_text", "")) for r in all_results)
    
    stats = {
        "date_processed": date_str,
        "total_images": total_images,
        "complex_images": len(complex_images),
        "simple_images": len(simple_images),
        "successful_extractions": successful,
        "success_rate": round(successful / total_images * 100, 2) if total_images > 0 else 0,
        "average_processing_time": avg_time,
        "total_characters_extracted": total_chars,
        "preprocessed_images": sum(1 for p in preprocessed_map.values() if p != list(preprocessed_map.keys())[list(preprocessed_map.values()).index(p)])
    }
    
    # Guardar estadísticas
    stats_file = os.path.join(output_dir, f"processing_stats_{date_str}.json")
    try:
        with open(stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        logger.info(f"Estadísticas guardadas en {stats_file}")
    except Exception as e:
        logger.error(f"Error guardando estadísticas: {e}")
    
    logger.info(f"Procesamiento completado: {successful}/{total_images} imágenes exitosas")
    
    return all_results


if __name__ == "__main__":
    # Configuración de línea de comandos
    parser = argparse.ArgumentParser(description="Optimiza y procesa imágenes en NewsAgent")
    parser.add_argument("--dir", required=True, help="Directorio con imágenes a procesar")
    parser.add_argument("--output", help="Directorio para resultados (defecto: mismo directorio)")
    parser.add_argument("--date", help="Fecha en formato ddmmyyyy (defecto: fecha actual)")
    parser.add_argument("--workers", type=int, default=2, help="Número de trabajadores para imágenes simples")
    parser.add_argument("--pause", type=int, default=30, help="Segundos de pausa entre lotes")
    parser.add_argument("--tesseract", action="store_true", help="Usar Tesseract como fallback")
    
    args = parser.parse_args()
    
    # Ejecutar procesamiento
    optimize_and_process_images(
        image_dir=args.dir,
        output_dir=args.output,
        date_str=args.date,
        max_workers=args.workers,
        pause_seconds=args.pause,
        use_tesseract=args.tesseract
    )

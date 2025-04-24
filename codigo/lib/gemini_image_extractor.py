# -*- coding: utf-8 -*-
"""
Módulo para extraer texto de imágenes mediante la API de Google Gemini.
Permite procesar imágenes individuales o lotes de imágenes desde archivos JSON.
"""

import google.generativeai as genai
from PIL import Image
import os
import json
import logging
from datetime import datetime, timedelta
import time

logger = logging.getLogger(__name__)

# Definición de Prompts Predefinidos
PREDEFINED_PROMPTS = {
    "simple": (
        "Extrae únicamente el texto legible que encuentres en esta imagen de documento escaneado. "
        "Ignora por completo cualquier logotipo, gráfico, figura, fotografía, diagrama o elemento visual similar. "
        "No describas la imagen, solo transcribe el texto."
    ),
    "detallado": (
        "Realiza una transcripción OCR precisa del contenido textual de esta imagen. Captura todo el texto visible incluyendo:"
        "- Titulares y subtítulos (respeta mayúsculas/minúsculas)"
        "- Párrafos completos (mantén la estructura original)"
        "- Pies de foto y leyendas (solo el texto)"
        "- Marcadores de viñetas y numeración"
        "- Información en cuadros de texto y destacados"
        "Preserva el formato original en cuanto a:"
        "- Separación entre párrafos"
        "- Estructura de columnas (transcribe de izquierda a derecha, columna por columna)"
        "- Jerarquía visual (títulos, subtítulos, cuerpo)"
        "Excluye elementos no textuales como imágenes, gráficos, bordes decorativos y logotipos."
        "No interpretes, resumas ni reorganices el contenido; transcribe fielmente como aparece."
        "Si algún texto es ilegible o dudoso, indícalo con [ilegible]."
    ),
    "estructurado": (
        "Analiza la estructura de esta página (probablemente un diario o documento similar) y extrae todo el texto de los artículos, titulares y bloques de texto. "
        "Omite deliberadamente cualquier imagen, publicidad gráfica, gráfico estadístico, o logotipo. "
        "Conserva los saltos de párrafo si es posible, pero enfócate en obtener solo el contenido escrito."
    ),
    "anti-ruido": (
        "Transcribe el texto principal de este documento. Presta especial atención a ignorar elementos visuales distractores como manchas, sellos superpuestos (si no son texto claro), firmas (si son ilegibles o puramente gráficas), y cualquier tipo de gráfico o ilustración. "
        "Devuelve solo el texto puro."
    )
}

class GeminiImageExtractor:
    """
    Clase que encapsula la funcionalidad para extraer texto de imágenes usando Gemini.
    """
    
    def __init__(self, api_key=None, prompt_key="detallado", model_name='gemini-1.5-pro-latest', batch_size=3, pause_seconds=60):
        """
        Inicializa el extractor de imágenes.
        
        Args:
            api_key: API key para Gemini (si es None, intentará cargar de variables de entorno)
            prompt_key: Clave del prompt predefinido a usar
            model_name: Nombre del modelo Gemini a utilizar
            batch_size: Número máximo de imágenes a procesar antes de pausar
            pause_seconds: Segundos de pausa entre lotes de imágenes
        """
        self.model_name = model_name
        self.batch_size = batch_size
        self.pause_seconds = pause_seconds
        
        # Seleccionar prompt
        if prompt_key in PREDEFINED_PROMPTS:
            self.prompt = PREDEFINED_PROMPTS[prompt_key]
        else:
            logger.warning(f"Prompt key '{prompt_key}' no válida, usando 'detallado'")
            self.prompt = PREDEFINED_PROMPTS["detallado"]
        
        # Configurar Gemini API
        if api_key is None:
            # Intentar obtener de variables de entorno
            import os
            from dotenv import load_dotenv
            
            # Determinar posibles ubicaciones del archivo .env
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, os.pardir, os.pardir))
            dotenv_paths = [
                os.path.join(project_root, 'credentials', '.env'),
                os.path.join(project_root, '.env')
            ]
            
            # Intentar cargar de cada ubicación
            api_key_loaded = False
            for dotenv_path in dotenv_paths:
                if os.path.exists(dotenv_path):
                    load_dotenv(dotenv_path=dotenv_path)
                    logger.debug(f"Cargado archivo .env desde: {dotenv_path}")
                    api_key = os.getenv("GOOGLE_API_KEY")
                    if api_key:
                        api_key_loaded = True
                        break
            
            if not api_key_loaded:
                error_msg = "No se encontró GOOGLE_API_KEY en variables de entorno"
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        # Asegurar que la API key sea válida
        try:
            # Si es un diccionario, intentar extraer la clave
            if isinstance(api_key, dict):
                if 'key' in api_key:
                    api_key = api_key['key']
                elif 'api_key' in api_key:
                    api_key = api_key['api_key']
                else:
                    api_key = str(api_key)
            
            # Asegurar que sea string y eliminar espacios en blanco
            if api_key is not None:
                api_key = str(api_key).strip()
            
            if not api_key:
                raise ValueError("API key vacía o inválida")
                
            # Configurar Gemini con la key limpia
            genai.configure(api_key=api_key)
            logger.info(f"API Gemini configurada correctamente con modelo: {model_name}")
        except Exception as e:
            error_msg = f"Error al configurar API Gemini: {e}"
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    def extract_text_from_image(self, image_path):
        """
        Extrae texto de una imagen usando Gemini.
        
        Args:
            image_path: Ruta al archivo de imagen
            
        Returns:
            str o None: Texto extraído o None si hay error
        """
        try:
            if not os.path.exists(image_path):
                logger.error(f"Imagen no encontrada: {image_path}")
                return None
            
            # Verificar y abrir la imagen
            try:
                with Image.open(image_path) as img:
                    img.verify()  # Verificar que es una imagen válida
                img = Image.open(image_path)  # Reabrir para uso
                
            except Exception as img_err:
                logger.error(f"Error al abrir/verificar imagen {os.path.basename(image_path)}: {img_err}")
                return None
            
            # Enviar a Gemini con manejo de excepciones mejorado
            try:
                # Crear modelo con timeout aumentado
                model = genai.GenerativeModel(
                    self.model_name,
                    safety_settings=[],  # Configuración de seguridad mínima
                    generation_config={"temperature": 0.0}  # Configuración para evitar creatividad
                )
                
                # Registrar información
                logger.info(f"Procesando con Gemini: {os.path.basename(image_path)}...")
                
                # Generar contenido con reintentos
                max_retries = 2
                retry_count = 0
                last_error = None
                
                while retry_count <= max_retries:
                    try:
                        # Aumentar timeout para imágenes grandes
                        response = model.generate_content(
                            [self.prompt, img],
                            request_options={'timeout': 240}  # 4 minutos de timeout
                        )
                        break  # Si llega aquí, se procesó correctamente
                    except Exception as retry_err:
                        last_error = retry_err
                        retry_count += 1
                        if retry_count <= max_retries:
                            logger.warning(f"Reintento {retry_count}/{max_retries} tras error: {type(retry_err).__name__}")
                            time.sleep(2)  # Breve pausa entre reintentos
                else:
                    # Si sale del bucle por agotarse los reintentos
                    raise last_error if last_error else ValueError("Error en todos los reintentos")
                
                # Procesar respuesta
                if response.parts:
                    if hasattr(response, 'text') and response.text:
                        return response.text.strip()
                    else:
                        logger.warning(f"Respuesta sin texto para {os.path.basename(image_path)}")
                        return None
                else:
                    reason = "Razón desconocida"
                    try:
                        if response.prompt_feedback and response.prompt_feedback.block_reason:
                            reason = f"Bloqueado por: {response.prompt_feedback.block_reason}"
                    except Exception:
                        pass
                    logger.warning(f"Respuesta sin partes de texto. {reason}")
                    return None
            
            except Exception as api_err:
                logger.error(f"Error de API Gemini: {type(api_err).__name__} - {api_err}")
                # Verificar si es un error de autenticación
                if "auth" in str(api_err).lower() or "key" in str(api_err).lower() or "credential" in str(api_err).lower():
                    logger.error("Posible problema con la clave API de Gemini. Verifique el formato en .env")
                raise api_err
                
        except Exception as e:
            logger.error(f"Error en API Gemini procesando {os.path.basename(image_path)}: {type(e).__name__} - {e}")
            return None
    
    def process_images_from_json(self, json_path, output_path=None, date_str=None):
        """
        Procesa imágenes desde un archivo JSON que contiene metadatos.
        
        Args:
            json_path: Ruta al archivo JSON con metadatos de imágenes
            output_path: Ruta para guardar los resultados (si es None, se genera automáticamente)
            date_str: Fecha en formato ddmmyyyy para nombrar archivos
            
        Returns:
            tuple: (éxito, lista de resultados, ruta del archivo de salida)
        """
        if not date_str:
            date_str = datetime.now().strftime('%d%m%Y')
        
        # Determinar la ruta de salida si no se proporciona
        if not output_path:
            output_dir = os.path.dirname(json_path)
            output_filename = f"extraction_results_{date_str}.json"
            output_path = os.path.join(output_dir, output_filename)
        
        # Cargar los datos del JSON
        try:
            with open(json_path, 'r', encoding='utf-8-sig') as f:
                image_data = json.load(f)
            
            if not image_data:
                logger.warning(f"Archivo JSON vacío o inválido: {json_path}")
                return False, [], None
            
            logger.info(f"Cargados datos de {len(image_data)} imágenes desde {json_path}")
        except Exception as e:
            logger.error(f"Error al cargar archivo JSON {json_path}: {e}")
            return False, [], None
        
        # Procesar imágenes en lotes
        all_results = []
        total_images = len(image_data)
        processed_count = 0
        batch_count = 0
        success_count = 0
        
        logger.info(f"Iniciando procesamiento de {total_images} imágenes en lotes de {self.batch_size}")
        
        for url_key, item_data in image_data.items():
            # Validar datos de la imagen
            if not isinstance(item_data, dict):
                logger.warning(f"Datos inválidos para URL '{url_key}'. Saltando.")
                continue
            
            filepath = item_data.get('filepath')
            filename = item_data.get('filename', f"unknown_filename_for_{url_key[:50]}")
            
            if not filepath or not isinstance(filepath, str):
                logger.warning(f"Ruta de archivo inválida para URL '{url_key}'. Saltando.")
                continue
            
            # Procesar la imagen
            processed_count += 1
            batch_count += 1
            
            logger.info(f"[{processed_count}/{total_images}] Procesando: {filename}")
            extracted_text = self.extract_text_from_image(filepath)
            
            # Guardar resultado
            result_entry = {
                "image_filename": filename,
                "processed_date": date_str,
                "extracted_text": extracted_text if extracted_text else ""
            }
            all_results.append(result_entry)
            
            if extracted_text:
                success_count += 1
            
            # Pausa cada N imágenes (tamaño del lote)
            if batch_count >= self.batch_size and processed_count < total_images:
                logger.info(f"Pausa de {self.pause_seconds} segundos después de procesar {batch_count} imágenes...")
                time.sleep(self.pause_seconds)
                batch_count = 0
        
        # Guardar todos los resultados
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(all_results, f, ensure_ascii=False, indent=4)
            logger.info(f"Resultados guardados en: {output_path}")
        except Exception as e:
            logger.error(f"Error al guardar resultados en {output_path}: {e}")
            return False, all_results, None
        
        # Resumen final
        logger.info(f"Procesamiento completado: {success_count} extracciones exitosas de {processed_count} imágenes")
        return True, all_results, output_path
    
    def process_date_range(self, start_date, end_date, base_dir=None, prompt_key=None):
        """
        Procesa imágenes para un rango de fechas.
        
        Args:
            start_date: Fecha inicial en formato ddmmyyyy
            end_date: Fecha final en formato ddmmyyyy
            base_dir: Directorio base donde buscar los JSON (si None, se usa el directorio predeterminado)
            prompt_key: Clave del prompt a usar (si None, se usa el predeterminado)
            
        Returns:
            dict: Resultados para cada fecha procesada
        """
        # Si se proporciona un nuevo prompt, actualizar
        if prompt_key and prompt_key in PREDEFINED_PROMPTS:
            self.prompt = PREDEFINED_PROMPTS[prompt_key]
        
        # Convertir fechas a objetos datetime
        try:
            start_dt = datetime.strptime(start_date, '%d%m%Y')
            end_dt = datetime.strptime(end_date, '%d%m%Y')
        except ValueError as e:
            logger.error(f"Formato de fecha inválido: {e}")
            return {}
        
        # Determinar directorio base
        if not base_dir:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, os.pardir, os.pardir))
            base_dir = os.path.join(project_root, 'input', 'Images')
        
        # Procesar cada fecha en el rango
        results = {}
        current_dt = start_dt
        while current_dt <= end_dt:
            date_str = current_dt.strftime('%d%m%Y')
            json_path = os.path.join(base_dir, f"image_links_{date_str}.json")
            
            if os.path.exists(json_path):
                logger.info(f"Procesando imágenes para fecha: {date_str}")
                success, _, output_path = self.process_images_from_json(json_path, date_str=date_str)
                results[date_str] = {
                    "success": success,
                    "output_path": output_path
                }
            else:
                logger.warning(f"No se encontró archivo JSON para fecha: {date_str}")
                results[date_str] = {
                    "success": False,
                    "error": "JSON not found"
                }
            
            # Avanzar al siguiente día
            current_dt += timedelta(days=1)
        
        return results

# Función auxiliar para parsear fechas
def parse_date_str(date_str):
    """
    Intenta parsear una fecha en formato DDMMYYYY.
    
    Args:
        date_str: Cadena con la fecha en formato DDMMYYYY
        
    Returns:
        datetime o None: Objeto datetime si la fecha es válida, None en caso contrario
    """
    try:
        return datetime.strptime(date_str, "%d%m%Y")
    except ValueError:
        return None

# Función de entrada para uso desde línea de comandos o importación
def extract_from_images(date=None, start_date=None, end_date=None, output_path=None, prompt_key="detallado", batch_size=3, pause_seconds=60, api_key=None):
    """
    Función principal para extraer texto de imágenes.
    
    Args:
        date: Fecha específica a procesar (formato DDMMYYYY)
        start_date: Inicio de rango de fechas (formato DDMMYYYY)
        end_date: Fin de rango de fechas (formato DDMMYYYY)
        output_path: Ruta de salida para los resultados
        prompt_key: Tipo de prompt a utilizar
        batch_size: Tamaño del lote de imágenes a procesar antes de pausar
        pause_seconds: Segundos de pausa entre lotes
        api_key: API key para Gemini (si es None, se busca en variables de entorno)
        
    Returns:
        bool: True si el proceso fue exitoso, False en caso contrario
    """
    try:
        # Inicializar extractor
        extractor = GeminiImageExtractor(
            api_key=api_key,
            prompt_key=prompt_key,
            batch_size=batch_size,
            pause_seconds=pause_seconds
        )
        
        # Determinar directorio base
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, os.pardir, os.pardir))
        base_dir = os.path.join(project_root, 'input', 'Images')
        
        # Procesar según los parámetros proporcionados
        if date:
            # Procesar una fecha específica
            json_path = os.path.join(base_dir, f"image_links_{date}.json")
            if os.path.exists(json_path):
                success, _, output_file = extractor.process_images_from_json(json_path, output_path, date)
                return success
            else:
                logger.error(f"Archivo JSON no encontrado para fecha {date}: {json_path}")
                return False
                
        elif start_date and end_date:
            # Procesar un rango de fechas
            results = extractor.process_date_range(start_date, end_date, base_dir, prompt_key)
            # Considerar éxito si al menos se procesó una fecha correctamente
            return any(result.get("success", False) for result in results.values())
            
        else:
            # Si no se especifica fecha, usar la fecha actual
            today_str = datetime.now().strftime('%d%m%Y')
            json_path = os.path.join(base_dir, f"image_links_{today_str}.json")
            
            if os.path.exists(json_path):
                success, _, output_file = extractor.process_images_from_json(json_path, output_path, today_str)
                return success
            else:
                logger.error(f"Archivo JSON no encontrado para fecha actual {today_str}: {json_path}")
                return False
                
    except Exception as e:
        logger.error(f"Error en procesamiento de imágenes: {e}")
        return False

# Punto de entrada para ejecución directa
if __name__ == "__main__":
    import argparse
    
    # Configuración básica de logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    # Configurar argumentos de línea de comandos
    parser = argparse.ArgumentParser(
        description="Extrae texto de imágenes usando Google Gemini",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Grupo de argumentos mutuamente excluyentes para fechas
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--date", type=str, help="Fecha específica a procesar (formato DDMMYYYY)")
    date_group.add_argument("--range", type=str, nargs=2, metavar=("START", "END"), 
                            help="Rango de fechas a procesar (formato DDMMYYYY)")
    
    # Otros argumentos
    parser.add_argument("--output", type=str, help="Ruta del archivo de salida")
    parser.add_argument("--prompt", choices=PREDEFINED_PROMPTS.keys(), default="detallado",
                        help="Tipo de prompt a utilizar")
    parser.add_argument("--batch-size", type=int, default=3, 
                        help="Número de imágenes a procesar antes de pausar")
    parser.add_argument("--pause", type=int, default=60,
                        help="Segundos de pausa entre lotes de imágenes")
    
    args = parser.parse_args()
    
    # Determinar parámetros según los argumentos
    date_param = None
    start_date_param = None
    end_date_param = None
    
    if args.date:
        date_param = args.date
    elif args.range:
        start_date_param, end_date_param = args.range
    
    # Ejecutar con los parámetros proporcionados
    success = extract_from_images(
        date=date_param,
        start_date=start_date_param,
        end_date=end_date_param,
        output_path=args.output,
        prompt_key=args.prompt,
        batch_size=args.batch_size,
        pause_seconds=args.pause
    )
    
    # Informar resultado
    if success:
        print("Procesamiento de imágenes completado exitosamente.")
    else:
        print("Error en el procesamiento de imágenes. Revise los logs para más detalles.")
        exit(1)

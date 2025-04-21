# -*- coding: utf-8 -*-
import openai
import pytesseract
from PIL import Image
import os
import argparse
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta

# --- Definición de Prompts Predefinidos (Sin cambios) ---
PREDEFINED_PROMPTS = {
    "simple": (
        "Extrae únicamente el texto legible que encuentres en esta imagen de documento escaneado. "
        "Ignora por completo cualquier logotipo, gráfico, figura, fotografía, diagrama o elemento visual similar. "
        "No describas la imagen, solo transcribe el texto."
    ),
    "detallado": (
        "Realiza una transcripción OCR del contenido textual de esta imagen. "
        "Tu objetivo es capturar todo el texto escrito, incluyendo titulares, párrafos, pies de foto (solo el texto), etc. "
        "Excluye explícitamente cualquier elemento no textual como imágenes, gráficos, bordes decorativos y logotipos. "
        "No interpretes ni resumas, solo transcribe."
    ),
    "estructurado": (
        "Analiza la estructura de esta página (probablemente un diario o documento similar) y extrae todo el texto de los artículos, titulares y bloques de texto. "
        "Omite deliberadamente cualquier imagen, publicidad gráfica, gráfico estadístico o logotipo. "
        "Conserva los saltos de párrafo si es posible, pero enfócate en obtener solo el contenido escrito."
    ),
    "anti-ruido": (
        "Transcribe el texto principal de este documento. Presta especial atención a ignorar elementos visuales distractores como manchas, sellos superpuestos (si no son texto claro), firmas (si son ilegibles o puramente gráficas) y cualquier tipo de gráfico o ilustración. "
        "Devuelve solo el texto puro."
    )
}

# --- Configuración (Carga de API Key y cálculo de rutas) ---
script_dir = os.path.dirname(os.path.abspath(__file__))  # Directorio 'codigo'
project_root = os.path.abspath(os.path.join(script_dir, os.pardir))  # Raíz 'scr1403'
dotenv_path = os.path.join(project_root, 'credentials', '.env')
# --- Ruta base para los JSON de entrada ---
input_images_base_dir = os.path.join(project_root, 'input', 'Images')  # Carpeta base

# --- Carga de .env ---
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    print(f"ERROR CRÍTICO: No se encontró el archivo .env en: {dotenv_path}")
    exit()

# Usaremos la API de OpenAI. Asegúrate de definir en tu .env la variable OPENAI_API_KEY
openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print(f"ERROR CRÍTICO: No se encontró la variable 'OPENAI_API_KEY' en {dotenv_path}.")
    exit()

openai.api_key = openai_api_key
print("API Key de OpenAI configurada exitosamente.")

# --- Función para extraer texto de la imagen con pytesseract y refinarlo con OpenAI ---
def extract_text_from_image(image_path: str, prompt: str) -> str | None:
    """Extrae texto de una imagen usando pytesseract y refina el resultado con la API de OpenAI.
    Devuelve el texto refinado o None en caso de error."""
    try:
        if not os.path.exists(image_path):
            print(f"   Error - Archivo no encontrado: {image_path}")
            return None
        try:
            # Verificar que la imagen se pueda abrir
            with Image.open(image_path) as img:
                img.verify()
            img = Image.open(image_path)
        except FileNotFoundError:
            print(f"   Error crítico - Archivo no encontrado al abrir: {image_path}")
            return None
        except (IOError, SyntaxError) as img_err:
            print(f"   Error al abrir/verificar imagen {os.path.basename(image_path)}: {img_err}")
            return None
        except Exception as img_open_err:
            print(f"   Error inesperado al abrir imagen {os.path.basename(image_path)}: {img_open_err}")
            return None

        # Extracción inicial de texto usando pytesseract
        raw_text = pytesseract.image_to_string(img, lang='spa')
        raw_text = raw_text.strip()
        if not raw_text:
            print("   Advertencia: No se extrajo texto inicial con pytesseract.")
            return ""

        # Preparar mensaje para OpenAI
        # Se envía el prompt predefinido junto con el texto extraído para que el modelo lo refine según las indicaciones.
        messages = [
            {"role": "system", "content": "Eres un asistente que ayuda a refinar textos extraídos de imágenes mediante OCR."},
            {"role": "user", "content": f"{prompt}\n\nTexto extraído inicialmente:\n{raw_text}"}
        ]

        print(f"   Enviando texto a OpenAI para refinamiento: {os.path.basename(image_path)} ...")
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # O "gpt-4" si tienes acceso
            messages=messages,
            temperature=0.0,
            timeout=180
        )

        refined_text = response.choices[0].message.get("content", "").strip()
        return refined_text

    except Exception as e:
        print(f"   Error en API OpenAI o al procesar {os.path.basename(image_path)}: {type(e).__name__} - {e}")
        return None

# --- Función para parsear fechas ---
def parse_date_str(date_str: str) -> datetime | None:
    """Intenta parsear una fecha en formato DDMMYYYY."""
    try:
        return datetime.strptime(date_str, "%d%m%Y")
    except ValueError:
        return None

# --- Bloque Principal de Ejecución ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extrae texto de imágenes (JSON por fecha/rango) y guarda resultados en un archivo JSON.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    # --- NUEVOS Argumentos para Fecha / Rango ---
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Procesa un día específico (formato DDMMYYYY). Ej: --date 10032025"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Inicio del rango de fechas a procesar (formato DDMMYYYY)."
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Fin del rango de fechas a procesar (formato DDMMYYYY, inclusivo)."
    )
    # --- Argumentos Anteriores ---
    parser.add_argument(
        "--output_json_name",
        type=str,
        default=None,
        help="Nombre del archivo JSON de salida. Si se omite, se genera con fecha(s)."
    )
    parser.add_argument(
        "-pk", "--prompt_key",
        choices=PREDEFINED_PROMPTS.keys(),
        default='simple',
        help="Clave del prompt predefinido a usar."
    )
    parser.add_argument(
        "-cp", "--custom_prompt",
        type=str,
        default=None,
        help="Prompt personalizado (ignora -pk si se usa)."
    )

    args = parser.parse_args()

    # --- Determinar Fecha(s) a Procesar ---
    dates_to_process = []
    date_range_str = ""  # Para nombre de archivo de salida si es rango

    if args.date:
        if args.start_date or args.end_date:
            print("Error: No puedes usar --date junto con --start-date o --end-date.")
            exit()
        date_obj = parse_date_str(args.date)
        if not date_obj:
            print(f"Error: Formato de fecha inválido para --date: '{args.date}'. Usa DDMMYYYY.")
            exit()
        dates_to_process.append(date_obj)
        date_range_str = date_obj.strftime("%d%m%Y")
        print(f"Procesando fecha específica: {date_range_str}")

    elif args.start_date and args.end_date:
        start_date_obj = parse_date_str(args.start_date)
        end_date_obj = parse_date_str(args.end_date)
        if not start_date_obj:
            print(f"Error: Formato de fecha inválido para --start-date: '{args.start_date}'. Usa DDMMYYYY.")
            exit()
        if not end_date_obj:
            print(f"Error: Formato de fecha inválido para --end-date: '{args.end_date}'. Usa DDMMYYYY.")
            exit()
        if start_date_obj > end_date_obj:
            print("Error: La fecha de inicio (--start-date) debe ser anterior o igual a la fecha de fin (--end-date).")
            exit()

        date_range_str = f"{start_date_obj.strftime('%d%m%Y')}_to_{end_date_obj.strftime('%d%m%Y')}"
        print(f"Procesando rango de fechas: {start_date_obj.strftime('%d/%m/%Y')} a {end_date_obj.strftime('%d/%m/%Y')}")

        current_date_in_range = start_date_obj
        while current_date_in_range <= end_date_obj:
            dates_to_process.append(current_date_in_range)
            current_date_in_range += timedelta(days=1)

    elif args.start_date or args.end_date:
         print("Error: Debes especificar --start-date y --end-date para usar un rango.")
         exit()
    else:
        # --- Comportamiento por defecto: Procesar día actual ---
        today = datetime.now()  # Puedes ajustar la zona horaria si es necesario
        dates_to_process.append(today)
        date_range_str = today.strftime("%d%m%Y")
        print(f"Procesando fecha actual (por defecto): {date_range_str}")

    # --- Cargar datos del JSON (o JSONs si es rango) ---
    combined_image_data = {}
    json_files_processed = []

    print(f"\nBuscando archivos JSON de entrada en: {input_images_base_dir}")
    for date_obj in dates_to_process:
        date_str = date_obj.strftime("%d%m%Y")
        json_filename = f"image_links_{date_str}.json"
        json_filepath = os.path.join(input_images_base_dir, json_filename)

        if os.path.exists(json_filepath):
            print(f"   Encontrado: {json_filename}. Cargando...")
            try:
                with open(json_filepath, 'r', encoding='utf-8-sig') as f:
                    loaded_data = json.load(f)
                if not isinstance(loaded_data, dict):
                    print(f"   Advertencia: {json_filename} no contiene un diccionario válido. Saltando archivo.")
                    continue

                # Fusionar datos (sobrescribe duplicados si existen en fechas posteriores)
                combined_image_data.update(loaded_data)
                json_files_processed.append(json_filename)
                print(f"      -> {len(loaded_data)} entradas añadidas/actualizadas.")

            except json.JSONDecodeError as json_err:
                print(f"   Advertencia: Error al decodificar JSON de '{json_filename}'. Saltando archivo. Error: {json_err}")
            except Exception as e:
                 print(f"   Advertencia: Error inesperado al cargar '{json_filename}'. Saltando archivo. Error: {e}")
        else:
            print(f"   No encontrado: {json_filename}. Saltando fecha.")

    if not combined_image_data:
        print("\nError Crítico: No se encontraron datos de imágenes en los archivos JSON para las fechas especificadas. Terminando.")
        exit()

    print(f"\nDatos cargados de {len(json_files_processed)} archivo(s) JSON. Total entradas a procesar: {len(combined_image_data)}")

    # --- Preparar para la salida ---
    output_json_filename = args.output_json_name
    if not output_json_filename:
        output_json_filename = f"extraction_results_{date_range_str}.json"
    elif not output_json_filename.lower().endswith('.json'):
        output_json_filename += '.json'

    output_json_path = os.path.join(script_dir, output_json_filename)
    print(f"Los resultados se guardarán en: {output_json_path}")

    all_results = []
    processed_date_str_output = datetime.now().strftime("%d%m%Y")  # Fecha de hoy para el campo "processed_date"

    # --- Determinar el prompt a usar ---
    if args.custom_prompt:
        selected_prompt = args.custom_prompt
        print(f"Usando prompt personalizado.")
    else:
        selected_prompt = PREDEFINED_PROMPTS[args.prompt_key]
        print(f"Usando prompt predefinido (clave: '{args.prompt_key}')")

    # --- Bucle de Procesamiento (sobre datos combinados) ---
    total_images_to_process = len(combined_image_data)
    processed_count = 0
    success_count = 0

    print(f"\n--- Iniciando procesamiento de {total_images_to_process} imágenes ---")

    for url_key, item_data in combined_image_data.items():
        processed_count += 1

        if not isinstance(item_data, dict):
            print(f"   Error Interno: La entrada para URL '{url_key}' no es un diccionario. Saltando.")
            continue

        filepath = item_data.get('filepath')
        original_filename = item_data.get('filename')

        if not filepath or not isinstance(filepath, str):
            print(f"   Error: Falta 'filepath' o no es válido para URL '{url_key}'. Saltando.")
            continue
        if not original_filename or not isinstance(original_filename, str):
            print(f"   Advertencia: Falta 'filename' para URL '{url_key}'. Usando placeholder.")
            original_filename = f"unknown_filename_for_{url_key[:50]}"

        print(f"[{processed_count}/{total_images_to_process}] Procesando archivo: {original_filename}")
        extracted_text = extract_text_from_image(filepath, selected_prompt)

        result_entry = {
            "image_filename": original_filename,
            "processed_date": processed_date_str_output,
            "extracted_text": extracted_text if extracted_text else ""
        }
        all_results.append(result_entry)

        if extracted_text is not None:
            success_count += 1

    # --- Guardar Resultados Consolidados en JSON ---
    print(f"\n--- Guardando {len(all_results)} resultados en {output_json_filename} ---")
    try:
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=4)
        print("Archivo JSON guardado exitosamente.")
    except Exception as e:
        print(f"Error Crítico al guardar el archivo JSON final '{output_json_path}': {e}")

    # --- Resumen Final ---
    print(f"\n--- Procesamiento Completado ---")
    print(f"Se procesaron {processed_count} entradas de {len(json_files_processed)} archivo(s) JSON fuente.")
    print(f"Se extrajo texto exitosamente de {success_count} imágenes.")
    print(f"Resultados completos guardados en: {output_json_path}")

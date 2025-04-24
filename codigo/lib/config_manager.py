# codigo/lib/config_manager.py
import os
import yaml
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "base_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')), # Default to project root
    "keywords": ["agua", "alcantarillado", "saneamiento", "SUNASS", "sedapal", "regulación", "servicios públicos"],
    "max_workers": 10,
    "cache_expiry": 86400,  # 24 horas en segundos
    "api": {
        # Nueva configuración para Gemini API
        "model": "gemini-1.5-pro-latest",
        "prompt_key": "detallado",
        "key": None # Se cargará desde credenciales o .env
    },
    "headers": {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124"
    }
}

# Modificar la función load_config para cargar la clave API de Gemini
def load_config(project_root, config_path="config.yaml", credentials_path="credentials/api_keys.yaml"):
    """
    Carga la configuración desde archivos YAML, fusionando con la configuración por defecto.
    Prioriza las credenciales de api_keys.yaml o .env para la clave API.
    """
    # Establecer base_dir en la configuración por defecto basado en project_root
    default_config = DEFAULT_CONFIG.copy()
    default_config["base_dir"] = project_root

    config = default_config.copy()

    # Cargar configuración general si existe
    full_config_path = os.path.join(project_root, config_path)
    if os.path.exists(full_config_path):
        try:
            with open(full_config_path, 'r', encoding='utf-8') as f:
                user_config = yaml.safe_load(f)
                if user_config:
                    # Fusiona diccionarios anidados correctamente
                    for key, value in user_config.items():
                        if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                            config[key].update(value)
                        else:
                            config[key] = value
            logger.info(f"Configuración cargada desde {full_config_path}")
        except Exception as e:
            logger.warning(f"No se pudo cargar {full_config_path}: {e}. Usando configuración por defecto.")

    # PRIMERA OPCIÓN: Cargar credenciales desde api_keys.yaml
    full_credentials_path = os.path.join(project_root, credentials_path)
    if os.path.exists(full_credentials_path):
        try:
            with open(full_credentials_path, 'r', encoding='utf-8') as f:
                api_keys = yaml.safe_load(f)
                if api_keys:
                    # Buscar Google API Key primero
                    if 'google_api_key' in api_keys:
                        config['api']['key'] = api_keys['google_api_key']
                        logger.info(f"Clave API de Google cargada desde {full_credentials_path}")
                    # Alternativamente, buscar API key genérica    
                    elif 'api_key' in api_keys:
                        config['api']['key'] = api_keys['api_key']
                        logger.info(f"Clave API cargada desde {full_credentials_path}")
                    else:
                        logger.warning(f"No se encontró 'google_api_key' o 'api_key' en {full_credentials_path}")
        except Exception as e:
            logger.warning(f"No se pudo cargar {full_credentials_path}: {e}")
    else:
        logger.warning(f"Archivo de credenciales no encontrado en {full_credentials_path}")

    # SEGUNDA OPCIÓN: Si no se encontró clave API en yaml, buscar en .env
    if not config['api']['key']:
        try:
            from dotenv import load_dotenv
            
            # Buscar archivo .env en varias ubicaciones posibles
            dotenv_paths = [
                os.path.join(project_root, 'credentials', '.env'),
                os.path.join(project_root, '.env')
            ]
            
            env_loaded = False
            for dotenv_path in dotenv_paths:
                if os.path.exists(dotenv_path):
                    load_dotenv(dotenv_path=dotenv_path)
                    env_loaded = True
                    logger.info(f"Archivo .env cargado desde: {dotenv_path}")
                    break
            
            if env_loaded:
                import os as os_env  # Evitar conflicto con os
                
                # Buscar GOOGLE_API_KEY
                api_key = os_env.getenv("GOOGLE_API_KEY")
                if api_key:
                    config['api']['key'] = api_key
                    logger.info("Clave API de Google cargada desde variables de entorno")
                else:
                    logger.warning("No se encontró GOOGLE_API_KEY en variables de entorno")
        except ImportError:
            logger.warning("python-dotenv no está instalado. No se pueden cargar variables de .env")
        except Exception as e:
            logger.warning(f"Error cargando .env: {e}")

    if not config['api']['key']:
        logger.warning("Clave API de Gemini no configurada. La funcionalidad de API de imágenes fallará.")


    return config

def get_paths(config, custom_date=None):
    """
    Genera las rutas de archivos basadas en la configuración.
    
    Args:
        config: Diccionario de configuración
        custom_date: Fecha personalizada (ddmmyyyy)
        
    Returns:
        dict: Diccionario con todas las rutas de archivos del proyecto
    """
    base_dir = config.get('project_root', os.getcwd())
    
    # Determinar la fecha para los nombres de archivo
    if custom_date:
        # Fecha personalizada proporcionada
        today_str = custom_date  # Asumimos formato ddmmyyyy
    else:
        # Fecha actual
        today_str = datetime.now().strftime("%d%m%Y")
    
    # Configurar directorios principales
    input_dir = os.path.join(base_dir, "input")
    image_base_dir = os.path.join(input_dir, "Images")
    output_dir = os.path.join(base_dir, "output")
    
    # ESTANDARIZACIÓN DE RUTAS: Unificar la ubicación del archivo de resultados de imágenes
    # Siempre colocarlo en output/{fecha}/images/texto_imagenes_api.json
    # Esto garantiza consistencia en todo el sistema
    image_output_dir = os.path.join(output_dir, today_str, "images")

    paths = {
        "project_root": base_dir,
        "pdf_input": os.path.join(base_dir, "base", f"{today_str}.pdf"),
        "links_extracted_csv": os.path.join(input_dir, "In", f"links_extracted_{today_str}.csv"),
        "scraped_texts_json": os.path.join(input_dir, "Out", f"scraped_texts_{today_str}.json"),
        "image_links_json": os.path.join(image_base_dir, f"image_links_{today_str}.json"),
        "image_download_dir": image_output_dir,  # MODIFICADO para usar output/fecha/images en vez de input/Images/downloads/fecha
        "image_api_results_json": os.path.join(image_output_dir, "texto_imagenes_api.json"),  # ESTANDARIZADO
        "social_links_json": os.path.join(input_dir, "Social", f"social_links_{today_str}.json"), # Añadido para guardar links sociales
        "processing_stats_json": os.path.join(input_dir, "Stats", f"stats_{today_str}.json"),
        "history_file": os.path.join(base_dir, "codigo", "lib", "history", "processed_urls.json"), # Mover historial a lib/history
        "cache_dir": os.path.join(base_dir, "cache")
    }

    # Crear directorios necesarios (excepto cache y history que se crean bajo demanda)
    for key, path in paths.items():
        if key.endswith('_dir') or key.endswith('_csv') or key.endswith('_json'):
             # Asegura que exista el directorio padre del archivo/directorio
            dir_to_create = os.path.dirname(path) if '.' in os.path.basename(path) else path
            if not os.path.exists(dir_to_create):
                 try:
                    os.makedirs(dir_to_create, exist_ok=True)
                    logger.debug(f"Directorio creado o ya existente: {dir_to_create}")
                 except OSError as e:
                    logger.error(f"Error creando directorio {dir_to_create}: {e}")

    return paths

# Ejemplo de uso (si se ejecuta directamente)
if __name__ == '__main__':
    # Asume que este archivo está en scrap_1402/codigo/lib
    project_root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    logging.basicConfig(level=logging.INFO) # Configuración básica para prueba
    cfg = load_config(project_root_dir)
    print("Configuración cargada:")
    import json
    print(json.dumps(cfg, indent=2))
    paths = get_paths(cfg)
    print("\nRutas generadas:")
    print(json.dumps(paths, indent=2))
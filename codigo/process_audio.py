#!/usr/bin/env python3
"""
Script para procesar archivos de audio utilizando los componentes del sistema NewsAgent.
Implementa funcionalidades para transcribir y analizar archivos de audio.
"""

import os
import sys
import logging
import json
import argparse
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ajustar path para importaciones
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("audio_processor")

# Importar componentes del sistema
from codigo.lib.component_loader import get_component_loader
from codigo.lib.config_unified import get_config

def parse_args() -> argparse.Namespace:
    """
    Analiza los argumentos de línea de comandos.
    
    Returns:
        Argumentos parseados
    """
    parser = argparse.ArgumentParser(description="Procesa archivos de audio")
    
    # Argumentos principales
    parser.add_argument("--input", "-i", type=str, help="Directorio o archivo de entrada")
    parser.add_argument("--output", "-o", type=str, help="Directorio de salida")
    
    # Modos de procesamiento
    parser.add_argument(
        "--mode", "-m", 
        choices=["all", "new", "missing"], 
        default="new",
        help="Modo de procesamiento: 'all' para procesar todos los archivos, 'new' para solo nuevos, 'missing' para archivos sin transcripción"
    )
    
    # Opciones de procesamiento
    parser.add_argument("--batch-size", "-b", type=int, default=5, help="Número de archivos a procesar en paralelo")
    parser.add_argument("--pause", "-p", type=int, default=1, help="Segundos de pausa entre lotes")
    parser.add_argument("--test", "-t", action="store_true", help="Modo de prueba (no realiza cambios)")
    parser.add_argument("--analyze", "-a", action="store_true", help="Analizar transcripciones después de transcribir")
    
    return parser.parse_args()

def get_audio_files(input_path: str, mode: str) -> List[Path]:
    """
    Obtiene la lista de archivos de audio a procesar.
    
    Args:
        input_path: Ruta al directorio o archivo de entrada
        mode: Modo de procesamiento (all, new, missing)
        
    Returns:
        Lista de rutas a archivos de audio
    """
    input_path = Path(input_path)
    audio_files = []
    
    # Extensiones de archivos de audio soportadas
    audio_extensions = ['.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac']
    
    # Procesar un solo archivo
    if input_path.is_file() and input_path.suffix.lower() in audio_extensions:
        audio_files.append(input_path)
        logger.info(f"Se procesará un único archivo: {input_path}")
        return audio_files
    
    # Procesar directorio
    if not input_path.is_dir():
        logger.error(f"La ruta de entrada no existe o no es válida: {input_path}")
        return []
    
    # Recopilar archivos de audio
    all_audio_files = []
    for root, _, files in os.walk(input_path):
        for file in files:
            file_path = Path(root) / file
            if file_path.suffix.lower() in audio_extensions:
                all_audio_files.append(file_path)
    
    # Filtrar según el modo
    if mode == "all":
        audio_files = all_audio_files
    elif mode == "new" or mode == "missing":
        # Obtener historial de procesamiento
        history_file = Path(current_dir) / "cache" / "audio_processing_history.json"
        processed_files = set()
        
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                    processed_files = set(history.get("processed_files", []))
            except Exception as e:
                logger.warning(f"Error leyendo historial: {e}")
        
        # Filtrar archivos nuevos
        if mode == "new":
            audio_files = [f for f in all_audio_files if str(f.absolute()) not in processed_files]
        
        # Filtrar archivos sin transcripción
        elif mode == "missing":
            for audio_file in all_audio_files:
                # Comprobar si existe el archivo de transcripción correspondiente
                expected_output = Path(str(audio_file).replace(str(input_path), str(Path(args.output)))) 
                expected_output = expected_output.with_suffix('.json')
                if not expected_output.exists():
                    audio_files.append(audio_file)
    
    logger.info(f"Se encontraron {len(audio_files)} archivos de audio para procesar en modo '{mode}'")
    return audio_files

def update_processing_history(processed_files: List[str]) -> None:
    """
    Actualiza el historial de procesamiento.
    
    Args:
        processed_files: Lista de archivos procesados
    """
    history_file = Path(current_dir) / "cache" / "audio_processing_history.json"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    
    history = {"processed_files": []}
    
    # Leer historial existente
    if history_file.exists():
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception as e:
            logger.warning(f"Error leyendo historial existente: {e}")
    
    # Actualizar historial
    existing_files = set(history.get("processed_files", []))
    existing_files.update(processed_files)
    history["processed_files"] = list(existing_files)
    history["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    
    # Guardar historial actualizado
    try:
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
        logger.debug(f"Historial actualizado: {len(history['processed_files'])} archivos en total")
    except Exception as e:
        logger.error(f"Error guardando historial: {e}")

def process_audio_files(input_dir: str, output_dir: str, batch_size: int = 5, 
                        pause_seconds: int = 1, mode: str = "new", 
                        test_mode: bool = False, analyze: bool = False) -> Dict[str, Any]:
    """
    Procesa archivos de audio en lotes.
    
    Args:
        input_dir: Directorio o archivo de entrada
        output_dir: Directorio de salida
        batch_size: Tamaño del lote
        pause_seconds: Segundos de pausa entre lotes
        mode: Modo de procesamiento (all, new, missing)
        test_mode: Si es True, no realiza cambios reales
        analyze: Si es True, analiza las transcripciones
        
    Returns:
        Resultados del procesamiento
    """
    # Cargar configuración y componentes
    config_manager = get_config()
    # Generar rutas para asegurar que existan los directorios
    paths = config_manager.generate_paths()
    
    # Cargar componentes
    loader = get_component_loader()
    loader.load_all_components()  # Cargar todos los componentes disponibles
    
    # Crear instancias de los componentes necesarios
    transcriber = None
    analyzer = None
    
    try:
        transcriber = loader.create_component('transcriber', 'audio_transcriber')
        if analyze:
            analyzer = loader.create_component('analyzer', 'text_analyzer')
    except Exception as e:
        logger.error(f"Error cargando componentes: {e}")
        if not transcriber:
            return {"error": f"No se pudo cargar el componente transcriber: {e}"}
    
    # Obtener archivos a procesar
    audio_files = get_audio_files(input_dir, mode)
    if not audio_files:
        logger.warning("No hay archivos de audio para procesar")
        return {"processed": 0, "success": 0, "failed": 0, "files": []}
    
    # Preparar directorio de salida
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Inicializar resultados
    results = {
        "total": len(audio_files),
        "success": 0,
        "failed": 0,
        "files": [],
        "start_time": time.time()
    }
    
    # Procesar archivos en lotes
    for i in range(0, len(audio_files), batch_size):
        batch = audio_files[i:i+batch_size]
        logger.info(f"Procesando lote {i//batch_size + 1}/{len(audio_files)//batch_size + 1} ({len(batch)} archivos)")
        
        for audio_file in batch:
            file_result = {
                "file": str(audio_file),
                "success": False,
                "output_files": []
            }
            
            try:
                # Determinar ruta de salida de la transcripción
                rel_path = audio_file.relative_to(Path(input_dir)) if Path(input_dir).is_dir() else audio_file.name
                transcript_output = output_path / rel_path.with_suffix('.json')
                transcript_output.parent.mkdir(parents=True, exist_ok=True)
                
                logger.info(f"Procesando archivo: {audio_file}")
                
                # Modo de prueba: solo simular
                if test_mode:
                    logger.info(f"[MODO PRUEBA] Se procesaría: {audio_file} -> {transcript_output}")
                    file_result["success"] = True
                    file_result["test_mode"] = True
                    continue
                
                # Transcribir archivo
                success, transcript_data = transcriber.transcribe_file(
                    audio_file=audio_file,
                    output_file=transcript_output,
                    metadata={"source": "process_audio.py", "batch": i//batch_size + 1}
                )
                
                file_result["success"] = success
                file_result["output_files"].append(str(transcript_output))
                
                if not success:
                    logger.error(f"Error transcribiendo {audio_file}: {transcript_data.get('error', 'Desconocido')}")
                    file_result["error"] = transcript_data.get("error", "Error desconocido")
                    results["failed"] += 1
                else:
                    logger.info(f"Transcripción exitosa: {audio_file} -> {transcript_output}")
                    results["success"] += 1
                    
                    # Analizar transcripción si se solicitó
                    if analyze and analyzer and success:
                        analysis_output = transcript_output.with_name(f"{transcript_output.stem}_analysis.json")
                        logger.info(f"Analizando transcripción: {transcript_output}")
                        
                        analysis_result = analyzer.analyze_transcription(
                            transcription_data=transcript_data,
                            source_id=transcript_output.stem
                        )
                        
                        if analysis_result.get("success", False):
                            with open(analysis_output, 'w', encoding='utf-8') as f:
                                json.dump(analysis_result, f, ensure_ascii=False, indent=2)
                            file_result["output_files"].append(str(analysis_output))
                            file_result["analysis_success"] = True
                            logger.info(f"Análisis completado: {analysis_output}")
                        else:
                            file_result["analysis_success"] = False
                            file_result["analysis_error"] = analysis_result.get("error", "Error desconocido")
                            logger.warning(f"Error en análisis: {analysis_result.get('error', 'Desconocido')}")
            
            except Exception as e:
                logger.error(f"Error procesando {audio_file}: {e}")
                file_result["error"] = str(e)
                file_result["success"] = False
                results["failed"] += 1
            
            results["files"].append(file_result)
            
            # Actualizar historial solo para archivos procesados con éxito
            if file_result["success"]:
                update_processing_history([str(audio_file.absolute())])
        
        # Pausa entre lotes
        if i + batch_size < len(audio_files) and pause_seconds > 0:
            logger.info(f"Pausa de {pause_seconds} segundos antes del siguiente lote...")
            time.sleep(pause_seconds)
    
    # Estadísticas finales
    results["end_time"] = time.time()
    results["duration"] = results["end_time"] - results["start_time"]
    
    logger.info(f"Procesamiento completado en {results['duration']:.2f} segundos")
    logger.info(f"Total: {results['total']}, Éxitos: {results['success']}, Fallos: {results['failed']}")
    
    return results

def main():
    """Función principal"""
    # Analizar argumentos
    args = parse_args()
    
    if not args.input:
        logger.error("Debe especificar un directorio o archivo de entrada")
        return 1
    
    if not args.output:
        logger.error("Debe especificar un directorio de salida")
        return 1
    
    logger.info(f"Iniciando procesamiento de audio en modo: {args.mode}")
    if args.test:
        logger.info("MODO DE PRUEBA ACTIVADO - No se realizarán cambios")
    
    # Procesar archivos
    results = process_audio_files(
        input_dir=args.input,
        output_dir=args.output,
        batch_size=args.batch_size,
        pause_seconds=args.pause,
        mode=args.mode,
        test_mode=args.test,
        analyze=args.analyze
    )
    
    # Guardar resultados
    summary_file = Path(args.output) / "processing_results.json"
    try:
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Resultados guardados en: {summary_file}")
    except Exception as e:
        logger.error(f"Error guardando resultados: {e}")
    
    # Salir con código apropiado
    if "error" in results or results.get("failed", 0) == results.get("total", 0):
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main()) 
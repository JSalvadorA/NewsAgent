#!/usr/bin/env python3
"""
Componente Transcriptor para el sistema NewsAgent.
Implementa la funcionalidad para transcribir archivos de audio mediante servicios externos.
"""

import os
import logging
import time
import json
from typing import Dict, Any, List, Optional, Tuple, Union
from pathlib import Path

from lib.api_client import APIClient

logger = logging.getLogger(__name__)

class Transcriber:
    """
    Componente que se encarga de la transcripción de archivos de audio.
    Utiliza un cliente API para comunicarse con servicios externos de transcripción.
    """
    
    # Identificador para el registro automático en la fábrica
    COMPONENT_TYPE = "transcriber"
    
    def __init__(self, config: Dict[str, Any], api_client: Optional[APIClient] = None):
        """
        Inicializa el transcriptor con la configuración proporcionada.
        
        Args:
            config: Configuración para el transcriptor
            api_client: Cliente API opcional, se creará uno nuevo si no se proporciona
        """
        self.config = config
        self.transcriber_config = config.get('transcriber', {})
        
        # Configuración específica
        self.output_format = self.transcriber_config.get('output_format', 'json')
        self.language = self.transcriber_config.get('language', 'es')
        self.timeout = self.transcriber_config.get('timeout', 300)  # Tiempo máximo de espera en segundos
        self.max_retries = self.transcriber_config.get('max_retries', 3)
        self.retry_delay = self.transcriber_config.get('retry_delay', 5)  # Segundos entre reintentos
        
        # Cliente API
        self.api_client = api_client
        if self.api_client is None:
            self.api_client = APIClient(config)
            
        logger.info(f"Transcriptor inicializado con formato de salida: {self.output_format}")
    
    def transcribe_file(self, audio_file: Union[str, Path], 
                        output_file: Optional[Union[str, Path]] = None,
                        metadata: Optional[Dict[str, Any]] = None) -> Tuple[bool, Dict[str, Any]]:
        """
        Transcribe un archivo de audio y opcionalmente guarda el resultado.
        
        Args:
            audio_file: Ruta al archivo de audio a transcribir
            output_file: Ruta donde guardar la transcripción (opcional)
            metadata: Metadatos adicionales para la transcripción
            
        Returns:
            Tupla con (éxito, resultado), donde éxito es un booleano y resultado contiene
            la transcripción o información de error
        """
        audio_file = Path(audio_file)
        if not audio_file.exists():
            logger.error(f"El archivo de audio no existe: {audio_file}")
            return False, {"error": "Archivo no encontrado"}
            
        if not audio_file.is_file():
            logger.error(f"La ruta no corresponde a un archivo: {audio_file}")
            return False, {"error": "La ruta no es un archivo"}
        
        logger.info(f"Iniciando transcripción de archivo: {audio_file}")
        
        # Preparar metadatos
        if metadata is None:
            metadata = {}
            
        # Agregar información básica a los metadatos
        metadata.update({
            "file_name": audio_file.name,
            "file_size": audio_file.stat().st_size,
            "language": self.language,
            "timestamp": time.time()
        })
        
        # Realizar la transcripción
        try:
            response_data = self._transcribe_with_retry(audio_file, metadata)
            
            # Verificar si la respuesta es válida
            if not response_data or "transcription" not in response_data:
                logger.error(f"Respuesta de transcripción inválida: {response_data}")
                return False, {"error": "Respuesta de API inválida", "api_response": response_data}
            
            # Extraer y procesar la transcripción
            transcription_result = self._process_transcription(response_data)
            
            # Guardar resultado si se especificó un archivo de salida
            if output_file:
                success = self._save_transcription(transcription_result, output_file)
                if not success:
                    logger.warning(f"No se pudo guardar la transcripción en {output_file}")
            
            logger.info(f"Transcripción completada para: {audio_file.name}")
            return True, transcription_result
            
        except Exception as e:
            logger.error(f"Error durante la transcripción de {audio_file.name}: {str(e)}")
            return False, {"error": str(e), "file": str(audio_file)}
    
    def _transcribe_with_retry(self, audio_file: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Realiza la transcripción con reintentos en caso de error.
        
        Args:
            audio_file: Archivo a transcribir
            metadata: Metadatos adicionales
            
        Returns:
            Datos de la respuesta de la API
            
        Raises:
            Exception: Si todos los reintentos fallan
        """
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Preparar parámetros adicionales
                params = {
                    "format": self.output_format,
                    "language": self.language,
                    "metadata": metadata
                }
                
                # Realizar la petición
                # Crear datos adicionales para subir junto al archivo
                additional_data = {
                    "format": self.output_format,
                    "language": self.language,
                    "metadata": json.dumps(metadata)
                }
                
                response = self.api_client.transcribe_audio(str(audio_file))
                
                # Verificar respuesta
                if response and isinstance(response, dict):
                    return response
                    
                logger.warning(f"Respuesta de transcripción inválida en intento {attempt}: {response}")
                
            except Exception as e:
                last_error = e
                logger.warning(f"Error en intento {attempt} de transcripción: {str(e)}")
                
            # Esperar antes de reintentar (excepto en el último intento)
            if attempt < self.max_retries:
                time.sleep(self.retry_delay)
        
        # Si llegamos aquí, todos los intentos han fallado
        error_msg = f"Transcripción fallida después de {self.max_retries} intentos"
        if last_error:
            error_msg += f": {str(last_error)}"
            
        raise Exception(error_msg)
    
    def _process_transcription(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa la respuesta de la API para extraer y estructurar la transcripción.
        
        Args:
            response_data: Datos de respuesta de la API
            
        Returns:
            Datos de transcripción procesados
        """
        result = {
            "transcription": response_data.get("transcription", ""),
            "confidence": response_data.get("confidence", 0.0),
            "duration": response_data.get("duration", 0.0),
            "segments": []
        }
        
        # Procesar segmentos si existen
        if "segments" in response_data:
            result["segments"] = response_data["segments"]
        
        # Extraer entidades si están disponibles
        if "entities" in response_data:
            result["entities"] = response_data["entities"]
            
        # Extraer metadatos si están disponibles
        if "metadata" in response_data:
            result["metadata"] = response_data["metadata"]
            
        return result
    
    def _save_transcription(self, transcription: Dict[str, Any], output_file: Union[str, Path]) -> bool:
        """
        Guarda la transcripción en un archivo.
        
        Args:
            transcription: Datos de la transcripción
            output_file: Ruta del archivo de salida
            
        Returns:
            True si se guardó correctamente, False en caso contrario
        """
        import json
        
        output_file = Path(output_file)
        
        # Crear directorio si no existe
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(transcription, f, ensure_ascii=False, indent=2)
            logger.debug(f"Transcripción guardada en: {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error guardando transcripción en {output_file}: {e}")
            return False
    
    def batch_transcribe(self, audio_files: List[Union[str, Path]], 
                        output_dir: Union[str, Path],
                        metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Transcribe un lote de archivos de audio.
        
        Args:
            audio_files: Lista de rutas a archivos de audio
            output_dir: Directorio donde guardar las transcripciones
            metadata: Metadatos compartidos por todos los archivos
            
        Returns:
            Diccionario con resultados de transcripción
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        results = {
            "success": [],
            "failed": [],
            "total": len(audio_files),
            "success_count": 0,
            "failed_count": 0
        }
        
        for audio_file in audio_files:
            audio_path = Path(audio_file)
            output_file = output_dir / f"{audio_path.stem}.json"
            
            # Metadatos específicos para este archivo
            file_metadata = metadata.copy() if metadata else {}
            file_metadata["batch_processing"] = True
            
            # Transcribir archivo
            success, result = self.transcribe_file(
                audio_file=audio_path,
                output_file=output_file,
                metadata=file_metadata
            )
            
            if success:
                results["success"].append({
                    "file": str(audio_path),
                    "output": str(output_file)
                })
                results["success_count"] += 1
            else:
                results["failed"].append({
                    "file": str(audio_path),
                    "error": result.get("error", "Unknown error")
                })
                results["failed_count"] += 1
                
        logger.info(f"Transcripción por lotes completada: {results['success_count']} éxitos, {results['failed_count']} fallos")
        return results
        

# Ejemplo de uso directo
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Configuración de ejemplo
    config = {
        "api": {
            "url": "https://api.example.com/v1",
            "key": "api-key-example",
            "retry_attempts": 3,
            "retry_delay": 2
        },
        "transcriber": {
            "output_format": "json",
            "language": "es",
            "timeout": 180
        }
    }
    
    # Crear cliente API directamente para pruebas
    api_client = APIClient(config)
    
    # Crear transcriptor
    transcriber = Transcriber(config=config, api_client=api_client)
    
    # Ejemplo de uso
    try:
        test_file = Path("ruta/a/archivo/audio_prueba.mp3")
        if test_file.exists():
            success, result = transcriber.transcribe_file(
                audio_file=test_file,
                output_file="ruta/salida/transcripcion_prueba.json"
            )
            print(f"Resultado de transcripción: {'Éxito' if success else 'Fallo'}")
            print(f"Datos: {result}")
        else:
            print(f"Archivo de prueba no encontrado: {test_file}")
    except Exception as e:
        print(f"Error en prueba: {e}") 
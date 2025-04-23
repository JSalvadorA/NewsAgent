#!/usr/bin/env python3
"""
Componente Analizador para el sistema NewsAgent.
Implementa la funcionalidad para analizar texto y extraer información estructurada.
"""

import logging
import json
import re
from typing import Dict, Any, List, Optional, Tuple, Union
from pathlib import Path
from datetime import datetime

from lib.api_client import APIClient

logger = logging.getLogger(__name__)

class Analyzer:
    """
    Componente que analiza textos de diferentes fuentes y extrae información estructurada.
    Utiliza un cliente API para comunicarse con servicios externos de análisis.
    """
    
    # Identificador para el registro automático en la fábrica
    COMPONENT_TYPE = "analyzer"
    
    def __init__(self, config: Dict[str, Any], api_client: Optional[APIClient] = None):
        """
        Inicializa el analizador con la configuración proporcionada.
        
        Args:
            config: Configuración para el analizador
            api_client: Cliente API opcional, se creará uno nuevo si no se proporciona
        """
        self.config = config
        self.analyzer_config = config.get('analyzer', {})
        
        # Configuración específica
        self.min_confidence = self.analyzer_config.get('min_confidence', 0.6)
        self.language = self.analyzer_config.get('language', 'es')
        self.max_retries = self.analyzer_config.get('max_retries', 3)
        self.cache_results = self.analyzer_config.get('cache_results', True)
        
        # Opciones de extracción
        self.extract_entities = self.analyzer_config.get('extract_entities', True)
        self.extract_sentiment = self.analyzer_config.get('extract_sentiment', True)
        self.extract_keywords = self.analyzer_config.get('extract_keywords', True)
        self.extract_categories = self.analyzer_config.get('extract_categories', True)
        
        # Cliente API
        self.api_client = api_client
        if self.api_client is None:
            self.api_client = APIClient(config)
            
        logger.info(f"Analizador inicializado con nivel de confianza mínimo: {self.min_confidence}")
    
    def analyze_text(self, text: str, source_id: Optional[str] = None,
                    options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Analiza un texto y extrae información estructurada.
        
        Args:
            text: Texto a analizar
            source_id: Identificador de la fuente (opcional)
            options: Opciones específicas para este análisis
            
        Returns:
            Diccionario con los resultados del análisis
        """
        if not text:
            logger.warning("Texto vacío enviado para análisis")
            return {"error": "Texto vacío", "success": False}
            
        # Combinar opciones por defecto con las proporcionadas
        merged_options = {
            "extract_entities": self.extract_entities,
            "extract_sentiment": self.extract_sentiment,
            "extract_keywords": self.extract_keywords,
            "extract_categories": self.extract_categories,
            "language": self.language,
            "min_confidence": self.min_confidence
        }
        
        if options:
            merged_options.update(options)
            
        logger.info(f"Analizando texto{f' de {source_id}' if source_id else ''} ({len(text)} caracteres)")
        
        try:
            # Verificar caché si está habilitada
            if self.cache_results and source_id:
                cached_result = self._check_cache(source_id)
                if cached_result:
                    logger.info(f"Usando resultado en caché para {source_id}")
                    return cached_result
            
            # Preparar solicitud
            params = {
                **merged_options,
                "timestamp": datetime.now().isoformat()
            }
            
            if source_id:
                params["source_id"] = source_id
                
            # Realizar análisis
            response = self._analyze_with_retry(text, params)
            
            # Procesar y enriquecer respuesta
            result = self._process_analysis_response(response)
            
            # Guardar en caché si está habilitado
            if self.cache_results and source_id:
                self._save_to_cache(source_id, result)
                
            return result
                
        except Exception as e:
            logger.error(f"Error durante el análisis: {str(e)}")
            return {"error": str(e), "success": False}
    
    def _analyze_with_retry(self, text: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Realiza el análisis con reintentos en caso de error.
        
        Args:
            text: Texto a analizar
            params: Parámetros de análisis
            
        Returns:
            Respuesta del servicio de análisis
            
        Raises:
            Exception: Si todos los reintentos fallan
        """
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                # Truncar texto muy largo para evitar errores de API
                truncated_text = text[:50000] if len(text) > 50000 else text
                
                # Realizar la petición al endpoint de análisis
                response = self.api_client.post(
                    endpoint="analyze",
                    json_data={
                        "text": truncated_text,
                        "params": params
                    }
                )
                
                # Verificar respuesta
                if response and isinstance(response, dict):
                    return response
                    
                logger.warning(f"Respuesta de análisis inválida en intento {attempt}")
                
            except Exception as e:
                last_error = e
                logger.warning(f"Error en intento {attempt} de análisis: {str(e)}")
                
            # Esperar antes de reintentar (excepto en el último intento)
            if attempt < self.max_retries:
                import time
                time.sleep(2 ** attempt)  # Backoff exponencial: 2, 4, 8... segundos
        
        # Si llegamos aquí, todos los intentos han fallado
        error_msg = f"Análisis fallido después de {self.max_retries} intentos"
        if last_error:
            error_msg += f": {str(last_error)}"
            
        raise Exception(error_msg)
    
    def _process_analysis_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa y enriquece la respuesta del servicio de análisis.
        
        Args:
            response: Respuesta original del servicio
            
        Returns:
            Respuesta procesada y enriquecida
        """
        # Verificar si hay error en la respuesta
        if "error" in response:
            return {"success": False, "error": response.get("error"), "raw_response": response}
            
        result = {
            "success": True,
            "timestamp": datetime.now().isoformat()
        }
        
        # Transferir componentes principales
        for key in ["entities", "sentiment", "keywords", "categories"]:
            if key in response:
                result[key] = response[key]
                
        # Filtrar entidades por confianza
        if "entities" in result:
            result["entities"] = [
                entity for entity in result["entities"] 
                if entity.get("confidence", 0) >= self.min_confidence
            ]
            
        # Agrupar entidades por tipo
        if "entities" in result:
            entity_types = {}
            for entity in result["entities"]:
                entity_type = entity.get("type", "UNKNOWN")
                if entity_type not in entity_types:
                    entity_types[entity_type] = []
                entity_types[entity_type].append(entity)
                
            result["entity_types"] = entity_types
        
        # Resumen de resultados
        result["summary"] = self._generate_summary(result)
        
        return result
    
    def _generate_summary(self, analysis_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Genera un resumen del análisis para facilitar el acceso a los datos clave.
        
        Args:
            analysis_result: Resultado completo del análisis
            
        Returns:
            Diccionario con el resumen
        """
        summary = {}
        
        # Contar entidades por tipo
        if "entities" in analysis_result:
            entity_counts = {}
            for entity in analysis_result["entities"]:
                entity_type = entity.get("type", "UNKNOWN")
                entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
                
            summary["entity_counts"] = entity_counts
            summary["total_entities"] = len(analysis_result["entities"])
            
        # Incluir sentimiento global
        if "sentiment" in analysis_result:
            summary["sentiment"] = analysis_result["sentiment"].get("score", 0)
            summary["sentiment_label"] = analysis_result["sentiment"].get("label", "NEUTRAL")
            
        # Palabras clave principales
        if "keywords" in analysis_result and analysis_result["keywords"]:
            top_keywords = sorted(
                analysis_result["keywords"], 
                key=lambda k: k.get("relevance", 0), 
                reverse=True
            )[:5]
            summary["top_keywords"] = [k.get("text", "") for k in top_keywords]
            
        # Categorías principales
        if "categories" in analysis_result and analysis_result["categories"]:
            top_categories = sorted(
                analysis_result["categories"], 
                key=lambda c: c.get("confidence", 0), 
                reverse=True
            )[:3]
            summary["top_categories"] = [c.get("label", "") for c in top_categories]
            
        return summary
    
    def _check_cache(self, source_id: str) -> Optional[Dict[str, Any]]:
        """
        Verifica si hay un resultado en caché para la fuente especificada.
        
        Args:
            source_id: Identificador de la fuente
            
        Returns:
            Resultado en caché o None si no existe
        """
        try:
            # Construir ruta de caché
            cache_dir = self.config.get('paths', {}).get('cache_dir')
            if not cache_dir:
                return None
                
            cache_file = Path(cache_dir) / "analyzer" / f"{source_id}.json"
            
            if cache_file.exists():
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Error accediendo a caché para {source_id}: {e}")
            
        return None
    
    def _save_to_cache(self, source_id: str, result: Dict[str, Any]) -> bool:
        """
        Guarda un resultado en la caché.
        
        Args:
            source_id: Identificador de la fuente
            result: Resultado a guardar
            
        Returns:
            True si se guardó correctamente
        """
        try:
            # Construir ruta de caché
            cache_dir = self.config.get('paths', {}).get('cache_dir')
            if not cache_dir:
                return False
                
            cache_path = Path(cache_dir) / "analyzer"
            cache_path.mkdir(parents=True, exist_ok=True)
            
            cache_file = cache_path / f"{source_id}.json"
            
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
                
            return True
            
        except Exception as e:
            logger.warning(f"Error guardando en caché para {source_id}: {e}")
            return False
    
    def analyze_file(self, file_path: Union[str, Path], 
                    output_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """
        Analiza el contenido de un archivo de texto.
        
        Args:
            file_path: Ruta al archivo a analizar
            output_path: Ruta donde guardar el resultado (opcional)
            
        Returns:
            Resultados del análisis
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"El archivo no existe: {file_path}")
            return {"error": "Archivo no encontrado", "success": False}
            
        try:
            # Leer contenido del archivo
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Usar el nombre de archivo como ID de fuente
            source_id = file_path.stem
            
            # Analizar contenido
            result = self.analyze_text(content, source_id)
            
            # Guardar resultado si se especificó una ruta
            if output_path and result.get("success", False):
                output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                    
                logger.info(f"Resultado guardado en {output_path}")
                
            return result
            
        except Exception as e:
            logger.error(f"Error analizando archivo {file_path}: {e}")
            return {"error": str(e), "success": False}
    
    def analyze_transcription(self, transcription_data: Dict[str, Any], 
                             source_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Analiza los datos de una transcripción.
        
        Args:
            transcription_data: Datos de transcripción (generalmente de un componente Transcriber)
            source_id: Identificador opcional de la fuente
            
        Returns:
            Resultados del análisis
        """
        # Extraer texto transcrito del formato de transcripción
        if not isinstance(transcription_data, dict):
            logger.error("Los datos de transcripción deben ser un diccionario")
            return {"error": "Formato de transcripción inválido", "success": False}
            
        # Extraer el texto de la transcripción
        text = transcription_data.get("transcription", "")
        
        if not text:
            logger.warning("Transcripción vacía enviada para análisis")
            return {"error": "Transcripción vacía", "success": False}
            
        # Derivar source_id si no se proporciona
        if not source_id and "metadata" in transcription_data:
            metadata = transcription_data["metadata"]
            if "file_name" in metadata:
                source_id = f"transcript_{metadata['file_name']}"
                
        # Opciones específicas para transcripciones
        options = {
            "is_transcription": True,
            # Incluir metadatos de audio si están disponibles
            "audio_metadata": transcription_data.get("metadata", {})
        }
        
        # Realizar análisis
        result = self.analyze_text(text, source_id, options)
        
        # Enriquecer resultado con datos de la transcripción
        if result.get("success", False):
            if "segments" in transcription_data:
                result["transcript_segments"] = transcription_data["segments"]
                
            if "confidence" in transcription_data:
                result["transcript_confidence"] = transcription_data["confidence"]
                
            if "duration" in transcription_data:
                result["audio_duration"] = transcription_data["duration"]
                
        return result

# Ejemplo de uso directo
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Configuración de ejemplo
    config = {
        "api": {
            "url": "https://api.example.com/v1",
            "key": "api-key-example"
        },
        "analyzer": {
            "min_confidence": 0.7,
            "language": "es",
            "extract_entities": True,
            "extract_sentiment": True
        },
        "paths": {
            "cache_dir": "./cache"
        }
    }
    
    # Crear cliente API directamente para pruebas
    api_client = APIClient(config)
    
    # Crear analizador
    analyzer = Analyzer(config=config, api_client=api_client)
    
    # Ejemplo de uso
    try:
        # Texto de ejemplo
        test_text = """
        El presidente del Gobierno, Pedro Sánchez, ha anunciado hoy en el Congreso un nuevo paquete 
        de medidas económicas por valor de 5.000 millones de euros para hacer frente a la crisis del 
        coronavirus. Entre las principales medidas destacan la suspensión del pago de hipotecas para 
        los afectados por la crisis y un plan de apoyo para autónomos y pymes.
        """
        
        # Analizar texto
        result = analyzer.analyze_text(test_text, "test_source")
        
        print("Resultado del análisis:")
        print(f"Éxito: {result.get('success', False)}")
        print(f"Entidades encontradas: {len(result.get('entities', []))}")
        print(f"Sentimiento: {result.get('summary', {}).get('sentiment_label', 'N/A')}")
        
        if result.get('entity_types'):
            print("\nTipos de entidades:")
            for entity_type, entities in result.get('entity_types', {}).items():
                print(f"  {entity_type}: {len(entities)} entidades")
                
        print("\nResumen:")
        for key, value in result.get('summary', {}).items():
            print(f"  {key}: {value}")
            
    except Exception as e:
        print(f"Error en prueba: {e}") 
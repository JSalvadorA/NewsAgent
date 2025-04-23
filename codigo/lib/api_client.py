#!/usr/bin/env python3
"""
Cliente API para comunicación con servicios externos.
Proporciona una interfaz unificada para realizar llamadas a APIs.
"""

import os
import time
import json
import logging
import requests
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)

class APIClient:
    """
    Cliente API genérico para realizar peticiones a servicios externos.
    Incluye manejo de reintentos, autenticación y formateo de respuestas.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Inicializa el cliente API con la configuración proporcionada.
        
        Args:
            config: Diccionario de configuración con parámetros como:
                   - api.key: Clave de API para autenticación
                   - api.url: URL base para las peticiones
                   - api.retry_attempts: Número de reintentos en caso de fallo
                   - api.retry_delay: Segundos de espera entre reintentos
        """
        self.config = config or {}
        self.api_key = self.config.get('api', {}).get('key')
        self.base_url = self.config.get('api', {}).get('url', 'https://api.example.com/v1')
        self.retry_attempts = self.config.get('api', {}).get('retry_attempts', 3)
        self.retry_delay = self.config.get('api', {}).get('retry_delay', 2)
        self.session = requests.Session()
        
        # Configurar headers por defecto
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'NewsAgent/1.0'
        })
        
        if self.api_key:
            self.session.headers.update({'Authorization': f'Bearer {self.api_key}'})
            logger.debug("Cliente API inicializado con clave de autenticación")
        else:
            logger.warning("Cliente API inicializado sin clave de autenticación")
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Realiza una petición HTTP con reintentos en caso de fallo.
        
        Args:
            method: Método HTTP (GET, POST, etc.)
            endpoint: Endpoint relativo a la URL base
            **kwargs: Argumentos adicionales para la petición
            
        Returns:
            Objeto Response de la petición
            
        Raises:
            requests.exceptions.RequestException: Si todos los reintentos fallan
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        attempts = 0
        last_exception = None
        
        while attempts < self.retry_attempts:
            try:
                response = self.session.request(method, url, **kwargs)
                
                # Comprobar si la petición fue exitosa
                if response.status_code < 400:
                    return response
                
                # Manejar errores específicos
                if response.status_code == 429:  # Too Many Requests
                    retry_after = int(response.headers.get('Retry-After', self.retry_delay * 2))
                    logger.warning(f"Rate limit alcanzado. Esperando {retry_after} segundos")
                    time.sleep(retry_after)
                    attempts += 1
                    continue
                    
                # Para otros errores, registrar y reintentar
                logger.error(f"Error en petición HTTP: {response.status_code} - {response.text}")
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Error de conexión: {str(e)}")
                last_exception = e
            
            # Incrementar contador y esperar antes de reintentar
            attempts += 1
            if attempts < self.retry_attempts:
                time.sleep(self.retry_delay * attempts)  # Backoff exponencial
        
        # Si llegamos aquí, todos los reintentos fallaron
        if last_exception:
            raise last_exception
        raise requests.exceptions.RequestException(f"Máximo de reintentos alcanzado para {url}")
    
    def get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Realiza una petición GET."""
        response = self._make_request("GET", endpoint, params=params)
        return response.json()
    
    def post(self, endpoint: str, data: Optional[Dict[str, Any]] = None, 
             json_data: Optional[Dict[str, Any]] = None, 
             files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Realiza una petición POST."""
        response = self._make_request("POST", endpoint, data=data, json=json_data, files=files)
        return response.json()
    
    def put(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Realiza una petición PUT."""
        response = self._make_request("PUT", endpoint, json=data)
        return response.json()
    
    def delete(self, endpoint: str) -> Dict[str, Any]:
        """Realiza una petición DELETE."""
        response = self._make_request("DELETE", endpoint)
        return response.json()
    
    def upload_file(self, endpoint: str, file_path: str, 
                   additional_data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Sube un archivo al servidor.
        
        Args:
            endpoint: Endpoint relativo a la URL base
            file_path: Ruta al archivo a subir
            additional_data: Datos adicionales para enviar junto con el archivo
            
        Returns:
            Respuesta JSON del servidor
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"No se encuentra el archivo: {file_path}")
        
        file_name = os.path.basename(file_path)
        files = {'file': (file_name, open(file_path, 'rb'))}
        
        try:
            response = self._make_request("POST", endpoint, data=additional_data, files=files)
            return response.json()
        finally:
            # Cerrar el archivo abierto
            files['file'][1].close()
    
    def transcribe_audio(self, audio_file_path: str) -> Dict[str, Any]:
        """
        Transcribe un archivo de audio utilizando el servicio configurado.
        
        Args:
            audio_file_path: Ruta al archivo de audio
            
        Returns:
            Diccionario con la transcripción y metadatos
        """
        logger.info(f"Transcribiendo archivo de audio: {audio_file_path}")
        return self.upload_file("transcribe", audio_file_path)

# Ejemplo de uso
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Configuración mock para pruebas
    mock_config = {
        'api': {
            'key': 'test-api-key',
            'url': 'https://api.example.com'
        }
    }
    
    client = APIClient(mock_config)
    try:
        result = client.get("test-endpoint")
        print(f"Resultado: {result}")
    except Exception as e:
        print(f"Error en la prueba: {e}")
"""
Utilidades para verificar dependencias y recursos del sistema.
"""

import subprocess
import sys
import os
import importlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def check_dependency(module_name, pip_package=None):
    """
    Verifica si un módulo de Python está disponible.
    
    Args:
        module_name (str): Nombre del módulo a verificar
        pip_package (str, optional): Nombre del paquete pip (si es diferente del nombre del módulo)
        
    Returns:
        bool: True si el módulo está disponible, False si no
    """
    if pip_package is None:
        pip_package = module_name
        
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        logger.warning(f"Dependencia '{module_name}' no encontrada. Instálela con: pip install {pip_package}")
        return False

def check_tesseract_installed():
    """
    Verifica si Tesseract OCR está instalado y disponible en el sistema.
    
    Returns:
        tuple: (bool, str) - (está_instalado, ruta_o_mensaje_de_error)
    """
    tesseract_cmd = None
    
    try:
        # Intentar ejecutar tesseract para verificar si está instalado
        result = subprocess.run(['tesseract', '--version'], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE, 
                              text=True,
                              timeout=2)
        if result.returncode == 0:
            version = result.stdout.strip().split('\n')[0]
            logger.info(f"Tesseract encontrado: {version}")
            return True, 'tesseract'
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        logger.debug(f"Tesseract no encontrado en PATH: {str(e)}")
        
    # Verificar rutas comunes en diferentes sistemas operativos
    common_paths = []
    
    if sys.platform.startswith('win'):
        common_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Tesseract-OCR\tesseract.exe'
        ]
    elif sys.platform.startswith('linux'):
        common_paths = [
            '/usr/bin/tesseract',
            '/usr/local/bin/tesseract'
        ]
    elif sys.platform == 'darwin':
        common_paths = [
            '/usr/local/bin/tesseract',
            '/opt/homebrew/bin/tesseract'
        ]
    
    for path in common_paths:
        if os.path.isfile(path):
            logger.info(f"Tesseract encontrado en: {path}")
            return True, path
    
    # Si no se encontró, proporcionar instrucciones de instalación
    instructions = """
Para instalar Tesseract OCR:

1. Windows:
   - Descargue e instale desde: https://github.com/UB-Mannheim/tesseract/wiki
   - Añada la ruta de instalación a las variables de entorno PATH

2. Linux:
   - Ubuntu/Debian: sudo apt-get install tesseract-ocr
   - Fedora: sudo dnf install tesseract
   
3. macOS:
   - Con Homebrew: brew install tesseract

4. Después de instalar, reinicie la aplicación
"""
    return False, instructions

def get_tesseract_languages():
    """
    Obtiene la lista de idiomas disponibles para Tesseract OCR.
    
    Returns:
        list: Lista de códigos de idioma disponibles
    """
    languages = []
    try:
        result = subprocess.run(['tesseract', '--list-langs'], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE,
                              text=True,
                              timeout=2)
        
        # Tesseract puede devolver la lista en stdout o stderr dependiendo de la versión
        output = result.stdout.strip() + "\n" + result.stderr.strip()
        
        # Filtrar y procesar la salida para obtener solo los códigos de idioma
        for line in output.split('\n'):
            line = line.strip()
            if line and not line.startswith('List of available'):
                languages.append(line)
                
    except Exception as e:
        logger.warning(f"No se pudo obtener la lista de idiomas de Tesseract: {e}")
        # Devolver idiomas comunes como fallback
        languages = ['eng']
        
    return languages

def check_ffmpeg_installed():
    """
    Verifica si FFmpeg está instalado en el sistema.
    
    Returns:
        bool: True si está instalado, False si no
    """
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE, 
                              text=True,
                              timeout=2)
        if result.returncode == 0:
            logger.info(f"FFmpeg encontrado: {result.stdout.splitlines()[0]}")
            return True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    return False

def ensure_torch_available(force_cpu=False):
    """
    Verifica que PyTorch esté instalado y funcionando correctamente.
    
    Args:
        force_cpu (bool): Si es True, fuerza el uso de CPU aunque haya GPU disponible
        
    Returns:
        tuple: (bool, str) - (está_disponible, dispositivo_o_error)
    """
    if not check_dependency('torch'):
        return False, "PyTorch no está instalado"
    
    import torch
    
    if force_cpu:
        return True, "cpu"
    
    try:
        if torch.cuda.is_available():
            device = "cuda"
            device_name = torch.cuda.get_device_name(0)
            logger.info(f"CUDA disponible: {device_name}")
        elif hasattr(torch, 'mps') and torch.backends.mps.is_available():
            device = "mps"  # Apple Silicon GPU
            logger.info("MPS (Apple Silicon GPU) disponible")
        else:
            device = "cpu"
            logger.info("Usando CPU para procesamiento")
            
        return True, device
    except Exception as e:
        logger.warning(f"Error al verificar dispositivos PyTorch: {e}")
        return True, "cpu"  # Fallback a CPU en caso de error

def check_required_directories():
    """
    Verifica y crea directorios necesarios para el funcionamiento del sistema.
    
    Returns:
        list: Lista de directorios creados
    """
    required_dirs = [
        'data',
        'data/processed',
        'data/raw',
        'logs',
        'output',
        'models'
    ]
    
    created_dirs = []
    base_dir = Path.cwd()
    
    for dir_name in required_dirs:
        dir_path = base_dir / dir_name
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(dir_path))
            logger.info(f"Directorio creado: {dir_path}")
            
    return created_dirs 
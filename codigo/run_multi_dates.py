# codigo/run_multi_dates.py
"""
Script para ejecutar el orquestador con múltiples fechas.
Permite procesar varios días a la vez, útil para fechas pasadas o reprocesamiento.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
import subprocess

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("multi_date_runner")

def is_valid_date(date_str):
    """Valida si una cadena tiene formato ddmmyyyy."""
    try:
        datetime.strptime(date_str, '%d%m%Y')
        return True
    except ValueError:
        return False

def run_for_single_date(date_str, only_facebook=False):
    """
    Ejecuta el orquestador para una fecha específica.
    
    Args:
        date_str: Fecha en formato ddmmyyyy
        only_facebook: Si es True, solo procesa URLs de Facebook
    
    Returns:
        bool: True si la ejecución fue exitosa, False en caso contrario
    """
    if not is_valid_date(date_str):
        logger.error(f"Formato de fecha inválido: {date_str}. Debe ser ddmmyyyy.")
        return False
    
    # Determinar qué script ejecutar
    script_path = os.path.join(os.path.dirname(__file__), 
                               "process_facebook.py" if only_facebook else "main.py")
    
    # Ejecutar el script correspondiente
    try:
        logger.info(f"Ejecutando {'procesamiento de Facebook' if only_facebook else 'orquestador completo'} para fecha: {date_str}")
        # Usar sys.executable para asegurar que se use el mismo intérprete de Python
        command = [sys.executable, script_path, date_str]
        
        # Ejecutar el proceso
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()
        
        # Verificar el resultado
        if process.returncode == 0:
            logger.info(f"Procesamiento exitoso para fecha {date_str}")
            return True
        else:
            logger.error(f"Error procesando fecha {date_str}. Código de error: {process.returncode}")
            if stdout:
                logger.debug(f"Salida estándar: {stdout}")
            if stderr:
                logger.error(f"Error: {stderr}")
            return False
            
    except Exception as e:
        logger.error(f"Error inesperado ejecutando script para fecha {date_str}: {e}")
        return False

def run_date_range(start_date, end_date, only_facebook=False):
    """
    Ejecuta el orquestador para un rango de fechas.
    
    Args:
        start_date: Fecha inicial en formato ddmmyyyy
        end_date: Fecha final en formato ddmmyyyy
        only_facebook: Si es True, solo procesa URLs de Facebook
    
    Returns:
        dict: Resultados para cada fecha procesada
    """
    if not is_valid_date(start_date) or not is_valid_date(end_date):
        logger.error("Formato de fecha inválido. Debe ser ddmmyyyy.")
        return {}
    
    # Convertir a objetos datetime
    start_dt = datetime.strptime(start_date, '%d%m%Y')
    end_dt = datetime.strptime(end_date, '%d%m%Y')
    
    # Verificar que start_date <= end_date
    if start_dt > end_dt:
        logger.error(f"La fecha inicial ({start_date}) debe ser anterior o igual a la fecha final ({end_date}).")
        return {}
    
    results = {}
    current_dt = start_dt
    
    # Procesar cada fecha en el rango
    while current_dt <= end_dt:
        current_date_str = current_dt.strftime('%d%m%Y')
        success = run_for_single_date(current_date_str, only_facebook)
        results[current_date_str] = "Éxito" if success else "Error"
        
        # Avanzar al siguiente día
        current_dt += timedelta(days=1)
    
    return results

def parse_args():
    """Analiza los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(description="Ejecutar el orquestador para múltiples fechas.")
    
    # Grupo de opciones de fecha (mutuamente excluyentes)
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument("--fecha", type=str, help="Fecha única en formato ddmmyyyy")
    date_group.add_argument("--rango", type=str, nargs=2, metavar=("INICIO", "FIN"), 
                           help="Rango de fechas en formato ddmmyyyy, ejemplo: 01012025 31012025")
    date_group.add_argument("--dias", type=int, help="Número de días anteriores a procesar (incluyendo hoy)")
    
    # Otras opciones
    parser.add_argument("--solo-facebook", action="store_true", 
                       help="Ejecutar solo el procesamiento de URLs de Facebook")
    
    return parser.parse_args()

def main():
    """Función principal."""
    args = parse_args()
    
    if args.fecha:
        # Procesar una única fecha
        success = run_for_single_date(args.fecha, args.solo_facebook)
        logger.info(f"Procesamiento {'exitoso' if success else 'fallido'} para fecha {args.fecha}")
    
    elif args.rango:
        # Procesar un rango de fechas
        start_date, end_date = args.rango
        results = run_date_range(start_date, end_date, args.solo_facebook)
        
        # Mostrar resumen
        logger.info("\n=== RESUMEN DE PROCESAMIENTO ===")
        success_count = sum(1 for status in results.values() if status == "Éxito")
        logger.info(f"Total de fechas: {len(results)}")
        logger.info(f"Exitosas: {success_count}")
        logger.info(f"Fallidas: {len(results) - success_count}")
        
        # Detalles
        logger.info("\nDetalle por fecha:")
        for date_str, status in sorted(results.items()):
            logger.info(f"{date_str}: {status}")
    
    elif args.dias:
        # Procesar los últimos N días
        if args.dias <= 0:
            logger.error("El número de días debe ser mayor que cero.")
            return
        
        today = datetime.now()
        start_date = today - timedelta(days=args.dias - 1)  # Restamos días-1 para incluir hoy
        
        # Convertir a formato ddmmyyyy
        start_date_str = start_date.strftime('%d%m%Y')
        today_str = today.strftime('%d%m%Y')
        
        # Procesar el rango
        results = run_date_range(start_date_str, today_str, args.solo_facebook)
        
        # Mostrar resumen
        logger.info("\n=== RESUMEN DE PROCESAMIENTO ===")
        success_count = sum(1 for status in results.values() if status == "Éxito")
        logger.info(f"Total de fechas: {len(results)}")
        logger.info(f"Exitosas: {success_count}")
        logger.info(f"Fallidas: {len(results) - success_count}")
        
        # Detalles
        logger.info("\nDetalle por fecha:")
        for date_str, status in sorted(results.items()):
            logger.info(f"{date_str}: {status}")

if __name__ == "__main__":
    main()


import sys
import os

# Asegurar que los directorios estén en el path
current_dir = os.path.dirname(os.path.abspath(__file__))
codigo_path = os.path.join(current_dir, 'codigo')
if codigo_path not in sys.path:
    sys.path.insert(0, codigo_path)

print("Probando importaciones...")

try:
    # Intentar importar los módulos problemáticos
    from codigo.lib.image_processor import ImageProcessor
    print("✓ Importación exitosa de ImageProcessor")
    
    from codigo.lib.image_text_extractor_api import ImageTextExtractorAPI
    print("✓ Importación exitosa de ImageTextExtractorAPI")
    
    # Probar creación de instancias (sin iniciarlas completamente)
    print("\nProbando creación de clases (sin inicializar)...")
    image_processor_class = ImageProcessor
    image_extractor_class = ImageTextExtractorAPI
    print("✓ Referencias a clases obtenidas correctamente")
    
    # Probando importaciones del main.py
    print("\nProbando importaciones de main.py...")
    from codigo.lib.config_unified import get_config
    print("✓ Importación exitosa de get_config desde config_unified")
    
    from codigo.lib.file_manager import save_to_csv, save_to_json, save_stats
    print("✓ Importación exitosa de file_manager")
    
    from codigo.lib.pdf_processor import extract_links_from_pdf
    print("✓ Importación exitosa de pdf_processor")
    
    from codigo.lib.url_manager import classify_urls
    print("✓ Importación exitosa de url_manager")
    
    from codigo.lib.history_tracker import HistoryTracker
    print("✓ Importación exitosa de history_tracker")
    
    from codigo.lib.html_scraper import HTMLScraper
    print("✓ Importación exitosa de html_scraper")
    
    print("\nTodas las importaciones funcionaron correctamente.")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

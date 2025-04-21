# test_api_key.py
import os
from dotenv import load_dotenv
import google.generativeai as genai

# Intenta cargar desde .env
load_dotenv("C:/Jerson/SUNASS/2025/4_April/gem/scr1403/credentials/.env")
api_key = os.getenv("GOOGLE_API_KEY")

print(f"API key encontrada: {api_key[:5]}..." if api_key else "No se encontró API key")

# Intenta configurar Gemini con esta clave
if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        response = model.generate_content("Hola mundo")
        print("API funcionando correctamente. Respuesta:", response.text)
    except Exception as e:
        print(f"Error al usar la API: {e}")
import sys
import os

# Добавляем текущую папку в путь, чтобы Python видел соседние файлы
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from llm_client import AnythingLLMClient

# ВАШИ НАСТРОЙКИ
API_KEY = "K90ZAK7-VEMMVAN-KCF11C4-QG5A1VF"
WORKSPACE = "moya-rabochaya-oblast" 

print(f"Подключаемся к воркспейсу: {WORKSPACE}...")

try:
    llm = AnythingLLMClient(
        base_url="http://localhost:3001",
        api_key=API_KEY,
        workspace=WORKSPACE,
    )

    prompt = "Сформулируй короткую фермерскую запись для журнала. Ответ строго в JSON."
    
    print(f"Отправляем запрос: {prompt}")
    response = llm.ask(prompt)
    
    print("\n" + "="*30)
    print("ОТВЕТ ОТ ANYTHINGLLM:")
    print("="*30)
    print(response)
    print("="*30)

except Exception as e:
    print(f"\nОШИБКА: {e}")

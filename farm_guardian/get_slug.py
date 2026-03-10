import requests
import json

# ВАШИ НАСТРОЙКИ
API_KEY = "K90ZAK7-VEMMVAN-KCF11C4-QG5A1VF"
BASE_URL = "http://localhost:3001"

url = f"{BASE_URL}/api/v1/workspaces"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        print("\n" + "="*30)
        print("ВАШИ WORKSPACES:")
        print("="*30)
        for ws in data.get('workspaces', []):
            print(f"ИМЯ:  {ws.get('name')}")
            print(f"SLUG: {ws.get('slug')}  <-- КОПИРУЙ ЭТО В КОД")
            print("-" * 30)
    else:
        print(f"Ошибка API: {response.status_code}")
        print(response.text)
        
except Exception as e:
    print(f"Критическая ошибка: {e}")
